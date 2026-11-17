"""Headless DPT API service.

本模块是协议的能力内核，**不 import 任何 Qt 符号**，因此可以：

- 由 GUI 主进程挂在后台线程里跑（见 :func:`dpt_extractor.api.server.start_in_thread`）；
- 通过 ``python -m dpt_extractor.api.server`` 独立启动，长期供自动化代理调用。

设计约束（重要）：

1. **零数值重造**。加载走 ``load_waveform``，提取走 ``run_extraction``，导出走
   ``export_to_excel``；斜率/损耗的默认上下文直接读 ``ExtractResult`` 里
   ``didt_contexts`` / ``dvdt_contexts`` / ``energy_contexts`` / ``power_contexts``
   已算好的权威对象。协议层只做搬运，不复制第二套算法。
2. **线程安全**。GUI 线程和 API 线程可能同时访问同一个 service，所有状态读写
   走同一把 ``RLock``。
3. **可查询状态**。每个耗时操作都写入 ``_status``，供 ``status()`` 轮询。
"""

from __future__ import annotations

import json
import math
import threading
import time
import traceback
import warnings
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from dpt_extractor.api.serialization import result_to_dict, to_jsonable
from dpt_extractor.config.loader import AppConfig, load_config
from dpt_extractor.export.excel_export import default_export_path, export_to_excel
from dpt_extractor.io.waveform_loader import load_waveform
from dpt_extractor.models.bridge_profile import (
    BridgeProfile,
    guess_profile_from_path,
    make_profile,
    make_short_circuit_profile,
)
from dpt_extractor.models.channel_mapping import (
    ChannelMapping,
    ChannelMappingStore,
    apply_mapping,
    validate_mapping,
)
from dpt_extractor.models.results import ExtractResult
from dpt_extractor.models.slope_range import (
    AUTO_MAX_SLOPE_MODE,
    SLOPE_ROW_KEYS,
    SlopeRange,
    default_slope_ranges,
    normalize_slope_range,
)
from dpt_extractor.models.test_mode import TestMode, parse_test_mode
from dpt_extractor.models.waveform import WaveformBundle
from dpt_extractor.models.wiring import (
    detect_wiring,
    validate_profile_against_wiring,
)
from dpt_extractor.pipeline.run_extract import run_extraction
from dpt_extractor.utils.sample_corpus import discover_sample_waveforms


class ApiError(Exception):
    """协议层可预期的业务错误，携带稳定错误码供调用方分支处理。"""

    def __init__(self, code: str, message: str, *, detail: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.detail:
            payload["detail"] = self.detail
        return payload


#: 斜率类参数 -> 计算该斜率所依据的逻辑通道角色。
#: 与 ``main_window._channel_for_param`` 的口径一致，仅用于手动光标重算。
_SLOPE_CHANNEL_ROLE: dict[tuple[str, str], str] = {
    ("关断过程", "dv/dt"): "vce",
    ("关断过程", "di/dt"): "ic",
    ("开通", "dv/dt"): "vce",
    ("开通", "di/dt"): "ic",
    ("反向恢复", "dv/dt"): "v_diode",
    ("反向恢复", "di/dt"): "irr",
}

#: 反向恢复 dv/dt 以 |Vd| 幅值定义，其余 dv/dt 取带符号原始电压。
_ABSOLUTE_VALUE_METRICS: frozenset[tuple[str, str]] = frozenset({("反向恢复", "dv/dt")})

_CONTEXT_FIELD_BY_SECTION: dict[str, str] = {
    "didt_contexts": "di/dt",
    "dvdt_contexts": "dv/dt",
    "energy_contexts": "energy",
    "power_contexts": "power",
}

#: 温度工况码与温度值域，口径同 ``main_window.TEMP_CONDITION_DEFAULTS`` 与
#: ``spin_temp_value`` 的 ``setRange(-100, 250)``。协议层先校验一遍是因为
#: 本机 HTTP 直连可以绕过界面，非法值一旦写进 QSettings 会污染后续每份报告。
_GUI_TEMPERATURE_CODES: tuple[str, ...] = ("RT", "HT", "LT")
_GUI_TEMPERATURE_MIN_C = -100.0
_GUI_TEMPERATURE_MAX_C = 250.0

#: 报告工况字段集随测试模式切换，口径同 ``main_window.DPT/SHORT_REPORT_CONDITION_FIELDS``。
#: 服务层不能 import Qt，因此这里保留一份同名字段表，只用于协议侧校验。
_GUI_DPT_REPORT_CONDITION_FIELDS: tuple[str, ...] = (
    "voltage_v",
    "current_a",
    "rg_on_ohm",
    "rg_off_ohm",
    "cg_nf",
)
_GUI_SHORT_REPORT_CONDITION_FIELDS: tuple[str, ...] = (
    "vce_v",
    "imax_a",
    "cdesat_pf",
    "rdesat_kohm",
    "vdesat_v",
)

#: 工况输入框的 QDoubleValidator 上限；超过它的值在界面上无法表示，协议侧直接拒。
_GUI_REPORT_CONDITION_VALUE_MAX = 1_000_000_000.0


def _slope_row_key(section: str, name: str) -> str | None:
    return SLOPE_ROW_KEYS.get((section, name))


def _as_us(seconds: float) -> float:
    return float(seconds) * 1e6


def _gui_report_mode_key(test_mode: Any) -> str:
    """把测试模式收敛成报告工况的两套口径：``dpt`` / ``short``。

    与 ``main_window._report_condition_mode_key`` 同一判据：只有短路模式
    换成短路字段表，其余（含偏移测量）都沿用双脉冲字段表。
    """
    return (
        "short"
        if str(test_mode or "").strip().lower() == "short_circuit"
        else "dpt"
    )


def _gui_condition_value(field: str, raw: Any) -> float | None:
    """校验单个工况字段值：``None`` 表示清空，否则必须是非负有限数。

    负值必须在这里拒掉：界面 ``ReportConditionEdit.numeric_value()`` 会把
    负文本读成 ``None``，放过去就会变成「静默清空」，报告 C 列凭空少一项。
    """
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ApiError(
            "invalid_condition_value",
            f"工况字段 {field} 需要数字或 null，收到 {raw!r}",
        )
    value = float(raw)
    if not math.isfinite(value):
        raise ApiError(
            "invalid_condition_value", f"工况字段 {field} 必须是有限数，收到 {raw!r}"
        )
    if not 0.0 <= value <= _GUI_REPORT_CONDITION_VALUE_MAX:
        raise ApiError(
            "invalid_condition_value",
            f"工况字段 {field} 必须落在 0~{_GUI_REPORT_CONDITION_VALUE_MAX:g}，"
            f"收到 {raw!r}",
        )
    return value


class ApiService:
    """无 GUI 的 DPT 操作句柄。

    典型用法::

        svc = ApiService()
        svc.load_session("sample.tss", phase="U", bridge="upper")
        svc.run_extraction()
        svc.set_slope_range("关断过程", "dv/dt", start_pct=20.0, end_pct=80.0)
        svc.export_xlsx("out.xlsx")
    """

    def __init__(self, config: AppConfig | None = None) -> None:
        self._lock = threading.RLock()
        self._cfg: AppConfig = config if config is not None else load_config()
        # 会话级配置增量：load_session 传了 test_mode/vdc_override 时，仅把这两个
        # 字段写入此处，绝不写回 self._cfg，避免跨请求粘滞（先后提取 short_circuit
        # 与 dpt 文件时串味）。空 dict 即无覆盖，_active_cfg() 直接返回 _cfg。
        self._session_overrides: dict[str, Any] = {}
        self._profile: BridgeProfile = make_profile("U", "upper")
        self._bundle: WaveformBundle | None = None
        self._result: ExtractResult | None = None
        self._source_path: str | None = None
        self._mapping_store = ChannelMappingStore()
        self._manual_cursors: dict[tuple[str, str], tuple[float, float]] = {}
        self._status: dict[str, Any] = {
            "state": "idle",
            "last_operation": None,
            "last_error": None,
            "last_duration_ms": None,
            "revision": 0,
        }

    def _active_cfg(self) -> AppConfig:
        """当前生效配置：在基础配置之上叠加会话级覆盖。

        语义约定（重要，与旧实现不同）：

        - 旧实现是「load 时刻的整份配置快照」，只有 slope_ranges / pulse_selection
          被特殊回绑，其余字段冻结在加载那一刻。新增全局设置字段会静默失同步。
        - 现实现是「增量覆盖」：``_session_overrides`` 只记录本次会话真正要覆盖的
          字段（当前是 ``test_mode`` / ``vdc_override``），其余字段**每次实时读取**
          ``self._cfg``。因此 ``set_slope_range`` 等全局改动会立即对当前会话生效，
          这是有意为之——它们本就属于全局运行时设置，不属于某次提取的一次性覆盖。
        - ``_session_overrides`` 内的值视为**只读快照**，调用方不得原地修改；
          需要改配置请走对应 setter，由 setter 写 ``self._cfg``。

        无覆盖时直接返回 ``self._cfg``（同一对象，零开销）；有覆盖时返回新对象，
        调用方不应依赖其身份稳定。
        """
        if not self._session_overrides:
            return self._cfg
        return replace(self._cfg, **self._session_overrides)

    # ------------------------------------------------------------------ 状态

    def _begin(self, operation: str) -> float:
        self._status.update(
            {
                "state": "running",
                "last_operation": operation,
                "last_error": None,
            }
        )
        return time.perf_counter()

    def _end(self, started: float) -> None:
        self._status.update(
            {
                "state": "idle",
                "last_duration_ms": round((time.perf_counter() - started) * 1000.0, 2),
                "revision": int(self._status.get("revision", 0)) + 1,
            }
        )

    def _fail(self, started: float, message: str) -> None:
        self._status.update(
            {
                "state": "failed",
                "last_error": message,
                "last_duration_ms": round((time.perf_counter() - started) * 1000.0, 2),
            }
        )

    def health(self) -> dict[str, Any]:
        """轻量健康检查：不触碰波形数据，可高频轮询。"""
        with self._lock:
            from dpt_extractor import __version__

            return {
                "ok": True,
                "service": "dpt-extractor-api",
                "version": __version__,
                "loaded": self._bundle is not None,
                "has_result": self._result is not None,
                "source_path": self._source_path,
                "test_mode": parse_test_mode(self._active_cfg().test_mode.mode).value,
            }

    def status(self) -> dict[str, Any]:
        """任务状态快照。"""
        with self._lock:
            payload = dict(self._status)
            payload["source_path"] = self._source_path
            payload["phase"] = self._profile.phase
            payload["bridge"] = self._profile.bridge
            payload["profile_code"] = self._profile.code
            payload["test_mode"] = parse_test_mode(self._active_cfg().test_mode.mode).value
            if self._bundle is not None:
                payload["sample_count"] = int(self._bundle.n)
                payload["dt_s"] = float(self._bundle.dt)
                payload["channels"] = sorted(self._bundle.channels.keys())
            if self._result is not None:
                payload["detected_pulse_count"] = int(self._result.detected_pulse_count)
                payload["single_pulse_mode"] = bool(self._result.single_pulse_mode)
                payload["short_circuit_mode"] = bool(self._result.short_circuit_mode)
            return payload

    # ------------------------------------------------------------- 样例与配置

    def list_samples(self, root: str | Path | None = None) -> dict[str, Any]:
        """枚举样例目录下的全部可用 .tss 会话。"""
        with self._lock:
            started = self._begin("list_samples")
            try:
                base = Path(root) if root is not None else self._default_sample_root()
                if not base.exists():
                    raise ApiError("sample_root_missing", f"样例目录不存在：{base}")
                found = discover_sample_waveforms(base)
                self._end(started)
                return {
                    "root": str(base),
                    "count": len(found),
                    "samples": [str(p) for p in found],
                }
            except ApiError as exc:
                self._fail(started, exc.message)
                raise
            except Exception as exc:  # pragma: no cover - 兜底
                self._fail(started, str(exc))
                raise ApiError("list_samples_failed", str(exc), detail=traceback.format_exc()) from exc

    def _default_sample_root(self) -> Path:
        from dpt_extractor.utils.app_paths import bundle_root

        candidate = bundle_root() / "示例文件"
        return candidate if candidate.exists() else bundle_root()

    def get_profile(self) -> dict[str, Any]:
        """当前通道映射 profile（相位 / 桥臂 / 逻辑通道分配）。"""
        with self._lock:
            return {
                "phase": self._profile.phase,
                "bridge": self._profile.bridge,
                "code": self._profile.code,
                "name": self._profile.name,
                "display_name": self._profile.display_name,
                "mapping": ChannelMapping.from_profile(self._profile).to_dict(),
                "profile": to_jsonable(self._profile),
            }

    def set_profile(
        self,
        *,
        phase: str | None = None,
        bridge: str | None = None,
        mapping: dict[str, Any] | None = None,
        persist: bool = False,
    ) -> dict[str, Any]:
        """切换相位/桥臂，并可选覆盖逻辑通道映射。

        覆盖映射时会先用 ``validate_mapping`` 校验；校验失败直接拒绝，不会把
        半套映射写进状态。
        """
        with self._lock:
            started = self._begin("set_profile")
            try:
                phase_value = (phase or self._profile.phase).upper()
                bridge_value = (bridge or self._profile.bridge).lower()
                test_mode = parse_test_mode(self._active_cfg().test_mode.mode)
                if test_mode == TestMode.SHORT_CIRCUIT:
                    profile = make_short_circuit_profile(phase_value, bridge_value)
                else:
                    profile = make_profile(phase_value, bridge_value)

                if mapping:
                    candidate = ChannelMapping.from_dict(mapping)
                    errors = validate_mapping(candidate, self._bundle)
                    if errors:
                        raise ApiError(
                            "invalid_mapping",
                            "通道映射校验未通过",
                            detail="；".join(errors),
                        )
                    profile = apply_mapping(profile, candidate)
                    if persist and self._bundle is not None:
                        self._mapping_store.set(
                            profile.phase,
                            profile.bridge,
                            candidate,
                            source_path=self._source_path,
                        )

                self._profile = profile
                self._end(started)
                return self.get_profile()
            except ApiError as exc:
                self._fail(started, exc.message)
                raise
            except Exception as exc:
                self._fail(started, str(exc))
                raise ApiError("set_profile_failed", str(exc), detail=traceback.format_exc()) from exc

    def get_slope_ranges(self) -> dict[str, Any]:
        """当前端点模式（各斜率行的百分比 / 电流基准 / 沿方向 / 自动最大）。"""
        with self._lock:
            ranges = dict(self._cfg.slope_ranges) or default_slope_ranges()
            return {
                key: {
                    "start_pct": sr.start_pct,
                    "end_pct": sr.end_pct,
                    "ic_reference": sr.ic_reference,
                    "ic_direction": sr.ic_direction,
                    "selection_mode": sr.selection_mode,
                    "label": sr.label(),
                }
                for key, sr in ranges.items()
            }

    def set_slope_range(
        self,
        section: str,
        name: str,
        *,
        start_pct: float | None = None,
        end_pct: float | None = None,
        ic_reference: str | None = None,
        ic_direction: str | None = None,
        auto_max: bool = False,
        recalculate: bool = True,
    ) -> dict[str, Any]:
        """设置某个斜率参数（dv/dt、di/dt）的端点模式。

        只改端点口径，不碰任何测量数值算法。``recalculate=True`` 时立即用当前
        已加载波形重跑提取，返回新的完整结果。
        """
        with self._lock:
            started = self._begin("set_slope_range")
            try:
                row_key = _slope_row_key(section, name)
                if row_key is None:
                    raise ApiError(
                        "unknown_slope_metric",
                        f"{section}-{name} 不是可设置端点模式的斜率参数",
                    )
                current = dict(self._cfg.slope_ranges) or default_slope_ranges()
                base = current.get(row_key) or default_slope_ranges()[row_key]
                updated = SlopeRange(
                    start_pct=float(base.start_pct if start_pct is None else start_pct),
                    end_pct=float(base.end_pct if end_pct is None else end_pct),
                    ic_reference=str(ic_reference or base.ic_reference),
                    ic_direction=str(ic_direction or base.ic_direction),
                    preset_label=base.preset_label,
                    selection_mode=(
                        AUTO_MAX_SLOPE_MODE if auto_max else base.selection_mode
                    ),
                )
                current[row_key] = normalize_slope_range(row_key, updated)
                self._cfg.slope_ranges = current
                self._end(started)
                payload: dict[str, Any] = {
                    "section": section,
                    "name": name,
                    "row_key": row_key,
                    "slope_ranges": self.get_slope_ranges(),
                }
                if recalculate and self._bundle is not None:
                    payload["result"] = self.run_extraction()
                return payload
            except ApiError as exc:
                self._fail(started, exc.message)
                raise
            except Exception as exc:
                self._fail(started, str(exc))
                raise ApiError("set_slope_range_failed", str(exc), detail=traceback.format_exc()) from exc

    # ------------------------------------------------------------------ 加载

    def load_session(
        self,
        path: str | Path,
        *,
        phase: str | None = None,
        bridge: str | None = None,
        test_mode: str | None = None,
        vdc_override: float | None = None,
        mapping: dict[str, Any] | None = None,
        auto_extract: bool = True,
    ) -> dict[str, Any]:
        """加载一个 .tss 会话并（默认）立即提取。

        相位/桥臂未显式给出时按文件名推断，与 CLI 行为一致。
        """
        with self._lock:
            started = self._begin("load_session")
            try:
                source = Path(path).expanduser()
                if not source.is_file():
                    raise ApiError("file_not_found", f"TSS 文件不存在：{source}")

                # 只记录本次会话真正要覆盖的字段，绝不写回 self._cfg：一次请求的
                # mode/override 不应残留给后续请求（否则先提取 short_circuit、再提取
                # dpt 不带 test_mode 时会沿用旧模式）。test_mode 是嵌套 dataclass，
                # 必须再 replace() 一层构造新对象，避免与基础配置共享同一实例。
                overrides: dict[str, Any] = {}
                if test_mode is not None:
                    overrides["test_mode"] = replace(
                        self._cfg.test_mode,
                        mode=parse_test_mode(test_mode).value,
                    )
                if vdc_override is not None:
                    overrides["vdc_override"] = float(vdc_override)
                # 未显式指定模式时 overrides 为空，等价于「回到基础配置」。
                self._session_overrides = overrides
                cfg = self._active_cfg()

                mode = parse_test_mode(cfg.test_mode.mode)
                if phase and bridge:
                    profile = (
                        make_short_circuit_profile(phase, bridge)
                        if mode == TestMode.SHORT_CIRCUIT
                        else make_profile(phase, bridge)
                    )
                else:
                    profile = guess_profile_from_path(source)
                    if mode == TestMode.SHORT_CIRCUIT:
                        from dpt_extractor.models.bridge_profile import (
                            as_short_circuit_profile,
                        )

                        profile = as_short_circuit_profile(profile)

                if mapping:
                    candidate = ChannelMapping.from_dict(mapping)
                    errors = validate_mapping(candidate, None, require_existing=False)
                    if errors:
                        raise ApiError(
                            "invalid_mapping",
                            "通道映射校验未通过",
                            detail="；".join(errors),
                        )
                    profile = apply_mapping(profile, candidate)

                bundle = load_waveform(source)

                # 接线一致性校验：必须在 assign self._bundle 之前完成。
                # auto_extract=False 时 run_extraction 不会执行，接线错配会潜伏到
                # 调用方下一次提取才爆；校验点前移到加载完成处才能提前拦住。
                # 判据是示波器 MATH 恒等式，不依赖文件名或目录名。
                wiring = detect_wiring(bundle)
                wiring_ok, wiring_severity, wiring_reason = validate_profile_against_wiring(
                    profile, wiring
                )
                wiring_warnings: list[str] = []
                if not wiring_ok:
                    if wiring_severity == "fatal":
                        raise ApiError(
                            "wiring_incompatible",
                            wiring_reason,
                            detail=json.dumps(wiring.to_dict(), ensure_ascii=False),
                        )
                    # mismatch：通道存在但语义对不上，程序能跑通而数值全错。
                    # 显式传 mapping 说明调用方已接管通道映射，此处降级为提示；
                    # 未传 mapping 则是静默错配，必须告警让人看见。
                    wiring_warnings.append(wiring_reason)
                    if not mapping:
                        warnings.warn(
                            f"[wiring] {source.name}: {wiring_reason}",
                            RuntimeWarning,
                            stacklevel=2,
                        )
                elif wiring_reason:
                    wiring_warnings.append(wiring_reason)

                self._bundle = bundle
                self._profile = profile
                self._source_path = str(source)
                self._result = None
                self._manual_cursors.clear()

                payload: dict[str, Any] = {
                    "source_path": self._source_path,
                    "profile": self.get_profile(),
                    "sample_count": int(bundle.n),
                    "dt_s": float(bundle.dt),
                    "channels": sorted(bundle.channels.keys()),
                    "wiring": {**wiring.to_dict(), "warnings": wiring_warnings},
                }
                if auto_extract:
                    payload["result"] = self.run_extraction()
                self._end(started)
                return payload
            except ApiError as exc:
                self._fail(started, exc.message)
                raise
            except Exception as exc:
                self._fail(started, str(exc))
                raise ApiError("load_session_failed", str(exc), detail=traceback.format_exc()) from exc

    def close_session(self) -> dict[str, Any]:
        """释放已加载波形与结果，并丢弃会话级配置覆盖。"""
        with self._lock:
            self._bundle = None
            self._result = None
            self._source_path = None
            self._session_overrides = {}
            self._manual_cursors.clear()
            return {"closed": True}

    # ------------------------------------------------------------------ 提取

    def run_extraction(self, *, array_mode: str = "summary") -> dict[str, Any]:
        """用当前波形 + profile + 配置执行一次完整提取，返回全量 JSON 结果。"""
        with self._lock:
            started = self._begin("run_extraction")
            try:
                if self._bundle is None:
                    raise ApiError("no_waveform", "尚未加载任何波形文件")
                result = run_extraction(self._bundle, self._profile, self._active_cfg())
                self._result = result
                self._manual_cursors.clear()
                self._end(started)
                return self._result_payload(result, array_mode=array_mode)
            except ApiError as exc:
                self._fail(started, exc.message)
                raise
            except KeyError as exc:
                # extract.py 内部对缺通道抛裸 KeyError，直接透出会让调用方只看到
                # 一句中文而拿不到错误码。这里升级为结构化 ApiError，附接线诊断。
                self._fail(started, str(exc))
                wiring_hint = ""
                if self._bundle is not None and self._profile is not None:
                    try:
                        report = detect_wiring(self._bundle)
                        wiring_hint = f"实测接线：{report.label}"
                        if report.note:
                            wiring_hint += f"；{report.note}"
                    except Exception:  # pragma: no cover - 诊断失败不影响主错误
                        wiring_hint = ""
                raise ApiError(
                    "wiring_incompatible",
                    str(exc).strip("'"),
                    detail=wiring_hint or traceback.format_exc(),
                ) from exc
            except Exception as exc:
                self._fail(started, str(exc))
                raise ApiError(
                    "extraction_failed", str(exc), detail=traceback.format_exc()
                ) from exc

    def extract_file(
        self,
        path: str | Path,
        *,
        phase: str | None = None,
        bridge: str | None = None,
        test_mode: str | None = None,
        vdc_override: float | None = None,
        mapping: dict[str, Any] | None = None,
        array_mode: str = "summary",
    ) -> dict[str, Any]:
        """一次性无状态提取：加载 + 提取，不改变当前会话（除加载缓存外）。"""
        self.load_session(
            path,
            phase=phase,
            bridge=bridge,
            test_mode=test_mode,
            vdc_override=vdc_override,
            mapping=mapping,
            auto_extract=False,
        )
        return self.run_extraction(array_mode=array_mode)

    def extract_all(
        self,
        paths: list[str | Path],
        *,
        test_mode: str | None = None,
        phase: str | None = None,
        bridge: str | None = None,
        vdc_override: float | None = None,
        array_mode: str = "summary",
        continue_on_error: bool = True,
    ) -> dict[str, Any]:
        """批量无头提取，逐文件返回结果或错误，不因单点失败中断整批。

        **必须显式指定 test_mode**：短路与双脉冲是两套不同的计算方法，
        产出语义不同的结果对象，不能在同一批次中混合。调用方应按测试类型
        分组、分多次调用（如 SMC 组传 dpt、DL 组传 short_circuit）。
        """
        if test_mode is None:
            raise ApiError(
                "missing_test_mode",
                "批量接口必须显式指定 test_mode（dpt / short_circuit / offset_measurement）。"
                "短路与双脉冲是两套不同的计算方法，不支持在同一批次中混合。",
            )
        with self._lock:
            started = self._begin("extract_all")
            items: list[dict[str, Any]] = []
            ok = 0
            failed = 0
            try:
                for raw in paths:
                    try:
                        payload = self.extract_file(
                            raw,
                            phase=phase,
                            bridge=bridge,
                            test_mode=test_mode,
                            vdc_override=vdc_override,
                            array_mode=array_mode,
                        )
                        items.append({"path": str(raw), "ok": True, "result": payload})
                        ok += 1
                    except ApiError as exc:
                        failed += 1
                        items.append(
                            {"path": str(raw), "ok": False, "error": exc.to_dict()}
                        )
                        if not continue_on_error:
                            raise
                self._end(started)
                return {"count": len(items), "ok": ok, "failed": failed, "items": items}
            except ApiError as exc:
                self._fail(started, exc.message)
                raise
            except Exception as exc:
                self._fail(started, str(exc))
                raise ApiError(
                    "extract_all_failed", str(exc), detail=traceback.format_exc()
                ) from exc

    def _result_payload(
        self, result: ExtractResult, *, array_mode: str = "summary"
    ) -> dict[str, Any]:
        payload = result_to_dict(result, array_mode=array_mode)
        payload["segments_detail"] = self._segments_payload(result)
        return payload

    def _segments_payload(self, result: ExtractResult) -> dict[str, Any] | None:
        segments = result.segments
        if segments is None or self._bundle is None:
            return None
        t = self._bundle.t

        def window(pair: tuple[int, int]) -> dict[str, float]:
            i0, i1 = int(pair[0]), int(pair[1])
            i0 = max(0, min(i0, len(t) - 1))
            i1 = max(i0, min(i1, len(t) - 1))
            return {"i0": i0, "i1": i1, "t0_us": _as_us(t[i0]), "t1_us": _as_us(t[i1])}

        return {
            "turn_off": window(segments.turn_off),
            "turn_on": window(segments.turn_on),
            "reverse_recovery": window(segments.reverse_recovery),
            "pulse1_on": int(segments.pulse1_on),
            "pulse1_off": int(segments.pulse1_off),
            "pulse2_on": int(segments.pulse2_on),
            "pulse2_off": int(segments.pulse2_off),
            "next_pulse_on": segments.next_pulse_on,
        }

    def get_result(self, *, array_mode: str = "summary") -> dict[str, Any]:
        """读取最近一次提取结果；未提取过则自动执行一次。"""
        with self._lock:
            if self._result is None:
                return self.run_extraction(array_mode=array_mode)
            return self._result_payload(self._result, array_mode=array_mode)

    def set_pulse_selection(self, *, off_pulse: int | None = None, on_pulse: int | None = None) -> dict[str, Any]:
        """设置关断/开通各取第几个门极脉冲，并立即重算。"""
        with self._lock:
            if off_pulse is not None:
                self._cfg.pulse_selection.off_pulse = int(off_pulse)
            if on_pulse is not None:
                self._cfg.pulse_selection.on_pulse = int(on_pulse)
            return {
                "off_pulse": int(self._cfg.pulse_selection.off_pulse),
                "on_pulse": int(self._cfg.pulse_selection.on_pulse),
                "result": self.run_extraction() if self._bundle is not None else None,
            }

    # ------------------------------------------------------- 光标与上下文

    def list_contexts(self) -> dict[str, Any]:
        """列出当前结果里所有可读取的测量上下文键。"""
        with self._lock:
            if self._result is None:
                raise ApiError("no_result", "尚未提取，无法列出测量上下文")
            out: dict[str, list[str]] = {}
            for field_name in _CONTEXT_FIELD_BY_SECTION:
                contexts = getattr(self._result, field_name, None) or {}
                out[field_name] = sorted("/".join(str(x) for x in key) for key in contexts)
            return out

    def get_context(self, section: str, name: str) -> dict[str, Any]:
        """读取单个参数的权威测量上下文（含 A/B 光标与端点电平）。

        优先返回手动设置的光标；否则返回提取阶段算好、并与 GUI 完全一致的
        默认上下文。
        """
        with self._lock:
            if self._result is None:
                raise ApiError("no_result", "尚未提取，无法读取测量上下文")
            manual = self._manual_cursors.get((section, name))
            stored = self._lookup_context(section, name)
            payload: dict[str, Any] = {
                "section": section,
                "name": name,
                "manual": manual is not None,
            }
            if stored is not None:
                payload["context"] = to_jsonable(stored)
            if manual is not None:
                payload["cursor"] = {"t_a_us": manual[0], "t_b_us": manual[1]}
            elif stored is not None:
                payload["cursor"] = self._cursor_from_context(stored)
            if not payload.get("context") and manual is None:
                raise ApiError(
                    "context_not_found",
                    f"{section}-{name} 没有可用的测量上下文",
                )
            return payload

    def _lookup_context(self, section: str, name: str) -> Any:
        assert self._result is not None
        for field_name in _CONTEXT_FIELD_BY_SECTION:
            contexts = getattr(self._result, field_name, None) or {}
            value = contexts.get((section, name))
            if value is not None:
                return value
        return None

    @staticmethod
    def _cursor_from_context(context: Any) -> dict[str, float] | None:
        crossing = getattr(context, "crossing", None)
        if crossing is None:
            return None
        t_a = getattr(crossing, "t_pct_a_s", None)
        t_b = getattr(crossing, "t_pct_b_s", None)
        if t_a is None or t_b is None:
            return None
        return {"t_a_us": _as_us(t_a), "t_b_us": _as_us(t_b)}

    def set_manual_cursor(
        self,
        section: str,
        name: str,
        *,
        t_a_us: float,
        t_b_us: float,
    ) -> dict[str, Any]:
        """按实时波形用手动 A/B 位置重算单个斜率参数。

        语义与 GUI 手动拖动 A/B 一致：两个时刻由用户直接拥有，数值按对应逻辑
        通道在这两点之间的幅值变化 / 时间变化计算。不触碰其他参数。
        """
        with self._lock:
            if self._bundle is None or self._result is None:
                raise ApiError("no_result", "尚未加载并提取，无法重算光标")
            if (section, name) not in _SLOPE_CHANNEL_ROLE:
                raise ApiError(
                    "unsupported_manual_cursor",
                    f"{section}-{name} 暂不支持手动光标重算（仅支持 dv/dt、di/dt 斜率行）",
                )
            if abs(float(t_b_us) - float(t_a_us)) < 1e-9:
                raise ApiError("invalid_cursor", "A/B 光标时间不能相同")

            role = _SLOPE_CHANNEL_ROLE[(section, name)]
            channel_ref = getattr(self._profile, role, "")
            if not channel_ref:
                raise ApiError(
                    "channel_unavailable",
                    f"当前 profile 未映射 {role} 通道，无法重算 {name}",
                )
            series = self._bundle.maybe_get(channel_ref)
            if series is None:
                raise ApiError(
                    "channel_missing",
                    f"波形中不存在通道 {channel_ref}",
                )

            t = self._bundle.t
            lo_us, hi_us = sorted((float(t_a_us), float(t_b_us)))
            i_a = int(np.searchsorted(t, lo_us * 1e-6, side="left"))
            i_b = int(np.searchsorted(t, hi_us * 1e-6, side="left"))
            i_a = max(0, min(i_a, len(t) - 1))
            i_b = max(i_a, min(i_b, len(t) - 1))

            values = series
            if (section, name) in _ABSOLUTE_VALUE_METRICS:
                values = np.abs(series)
            y_a = float(values[i_a])
            y_b = float(values[i_b])
            dt = hi_us - lo_us
            delta = abs(y_b - y_a)
            value = delta / (dt * 1e-6) / 1e9 if dt > 0 else 0.0

            self._manual_cursors[(section, name)] = (lo_us, hi_us)
            return {
                "section": section,
                "name": name,
                "cursor": {"t_a_us": lo_us, "t_b_us": hi_us},
                "channel": channel_ref,
                "level_a": y_a,
                "level_b": y_b,
                "value": value,
            }

    def clear_manual_cursor(self, section: str | None = None, name: str | None = None) -> dict[str, Any]:
        """清除手动光标；不带参数时清除全部。"""
        with self._lock:
            if section is None and name is None:
                self._manual_cursors.clear()
            else:
                self._manual_cursors.pop((section, name), None)
            return {"manual_cursors": sorted(
                f"{s}/{n}" for (s, n) in self._manual_cursors
            )}

    # ------------------------------------------------------------------ 导出

    def export_xlsx(self, path: str | Path | None = None) -> dict[str, Any]:
        """导出 xlsx 报告到指定路径。"""
        with self._lock:
            started = self._begin("export_xlsx")
            try:
                if self._result is None:
                    raise ApiError("no_result", "无提取结果可导出")
                target = (
                    Path(path).expanduser()
                    if path is not None
                    else default_export_path(self._result)
                )
                if target.suffix.lower() != ".xlsx":
                    target = target.with_suffix(".xlsx")
                target.parent.mkdir(parents=True, exist_ok=True)
                export_to_excel(self._result, target)
                self._end(started)
                return {
                    "path": str(target),
                    "exists": target.is_file(),
                    "size_bytes": target.stat().st_size if target.is_file() else 0,
                }
            except ApiError as exc:
                self._fail(started, exc.message)
                raise
            except Exception as exc:
                self._fail(started, str(exc))
                raise ApiError("export_failed", str(exc), detail=traceback.format_exc()) from exc

    def export_all(
        self,
        paths: list[str | Path],
        output_dir: str | Path,
        *,
        test_mode: str | None = None,
        phase: str | None = None,
        bridge: str | None = None,
        vdc_override: float | None = None,
    ) -> dict[str, Any]:
        """批量提取并导出 xlsx，输出到指定目录。

        **必须显式指定 test_mode**，理由同 extract_all：短路与双脉冲是两套
        不同的计算方法，不能在同一批次中混合。
        """
        if test_mode is None:
            raise ApiError(
                "missing_test_mode",
                "批量接口必须显式指定 test_mode（dpt / short_circuit / offset_measurement）。"
                "短路与双脉冲是两套不同的计算方法，不支持在同一批次中混合。",
            )
        with self._lock:
            started = self._begin("export_all")
            out_dir = Path(output_dir).expanduser()
            out_dir.mkdir(parents=True, exist_ok=True)
            items: list[dict[str, Any]] = []
            ok = 0
            failed = 0
            try:
                for raw in paths:
                    source = Path(raw)
                    try:
                        self.extract_file(
                            source,
                            phase=phase,
                            bridge=bridge,
                            test_mode=test_mode,
                            vdc_override=vdc_override,
                        )
                        exported = self.export_xlsx(out_dir / f"{source.stem}.xlsx")
                        items.append({"source": str(source), "ok": True, **exported})
                        ok += 1
                    except ApiError as exc:
                        failed += 1
                        items.append(
                            {"source": str(source), "ok": False, "error": exc.to_dict()}
                        )
                self._end(started)
                return {"count": len(items), "ok": ok, "failed": failed, "items": items}
            except Exception as exc:
                self._fail(started, str(exc))
                raise ApiError(
                    "export_all_failed", str(exc), detail=traceback.format_exc()
                ) from exc

    # ------------------------------------------------------------------ GUI 自动化控制桥接

    def _require_gui_bridge(self) -> Any:
        from dpt_extractor.api import gui_host

        bridge = gui_host.get_gui_bridge()
        if bridge is None:
            raise ApiError(
                "gui_bridge_unavailable",
                "当前未挂载 GUI 主窗口控制桥（请确认已通过 GUI 启动并开启内嵌 API）",
            )
        return bridge

    def gui_set_template(self, path: str | None) -> dict[str, Any]:
        """设置 GUI 当前报告模板路径。"""
        if not path:
            raise ApiError("missing_param", "缺少必填参数 path")
        started = self._begin("gui_set_template")
        try:
            bridge = self._require_gui_bridge()
            res = bridge.invoke("set_template", {"path": str(path)}, timeout=15.0)
            self._end(started)
            return res
        except ApiError:
            raise
        except Exception as exc:
            self._fail(started, str(exc))
            raise ApiError("gui_set_template_failed", str(exc), detail=traceback.format_exc()) from exc

    def gui_set_output(self, path: str | None) -> dict[str, Any]:
        """设置 GUI 当前报告输出路径。"""
        if not path:
            raise ApiError("missing_param", "缺少必填参数 path")
        started = self._begin("gui_set_output")
        try:
            bridge = self._require_gui_bridge()
            res = bridge.invoke("set_output", {"path": str(path)}, timeout=15.0)
            self._end(started)
            return res
        except ApiError:
            raise
        except Exception as exc:
            self._fail(started, str(exc))
            raise ApiError("gui_set_output_failed", str(exc), detail=traceback.format_exc()) from exc

    def gui_load_file(
        self,
        path: str | None,
        *,
        phase: str | None = None,
        bridge: str | None = None,
        test_mode: str | None = None,
    ) -> dict[str, Any]:
        """在 GUI 主窗口加载单个波形并等待提取/渲染完成。"""
        if not path:
            raise ApiError("missing_param", "缺少必填参数 path")
        params = {
            "path": str(path),
            "phase": phase,
            "bridge": bridge,
            "test_mode": test_mode,
        }
        started = self._begin("gui_load_file")
        try:
            gui_bridge = self._require_gui_bridge()
            res = gui_bridge.invoke("load_file", params, timeout=60.0)
            self._end(started)
            return res
        except ApiError:
            raise
        except Exception as exc:
            self._fail(started, str(exc))
            raise ApiError("gui_load_file_failed", str(exc), detail=traceback.format_exc()) from exc

    def gui_write_report(self, *, timeout: float = 60.0) -> dict[str, Any]:
        """触发 GUI 主窗口“写入报告”（含真实图表截图与双脉冲/单脉冲/短路多sheet写入）并等待完成。"""
        started = self._begin("gui_write_report")
        try:
            gui_bridge = self._require_gui_bridge()
            res = gui_bridge.invoke("write_report", {"timeout": timeout}, timeout=max(10.0, float(timeout) + 5.0))
            self._end(started)
            return res
        except ApiError:
            raise
        except Exception as exc:
            self._fail(started, str(exc))
            raise ApiError("gui_write_report_failed", str(exc), detail=traceback.format_exc()) from exc

    def gui_set_temperature(
        self, code: str | None, value: float | None = None
    ) -> dict[str, Any]:
        """设置 GUI 的温度工况与温度值。

        语义等价于「用户在温度下拉选 ``code``，再在 ℃ 输入框填 ``value``」：
        省略 ``value`` 只切工况，该 code 保持既有温度值。合法域在协议层先校验
        一次，因为本机 HTTP 直连可以绕过界面控件，不能只靠 GUI 兜底。
        """
        if not code:
            raise ApiError("missing_param", "缺少必填参数 code")
        normalized = str(code).strip().upper()
        if normalized not in _GUI_TEMPERATURE_CODES:
            raise ApiError(
                "invalid_temperature_code",
                "温度工况码必须是 "
                f"{'/'.join(_GUI_TEMPERATURE_CODES)} 之一，收到 {code!r}",
            )
        params: dict[str, Any] = {"code": normalized}
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ApiError(
                    "invalid_temperature_value", f"温度值必须是数字，收到 {value!r}"
                )
            number = float(value)
            if not math.isfinite(number) or not (
                _GUI_TEMPERATURE_MIN_C <= number <= _GUI_TEMPERATURE_MAX_C
            ):
                raise ApiError(
                    "invalid_temperature_value",
                    "温度值必须是 "
                    f"{_GUI_TEMPERATURE_MIN_C:g}~{_GUI_TEMPERATURE_MAX_C:g} ℃ "
                    f"之间的有限数，收到 {value!r}",
                )
            params["value"] = number
        started = self._begin("gui_set_temperature")
        try:
            bridge = self._require_gui_bridge()
            res = bridge.invoke("set_temperature", params, timeout=15.0)
            self._end(started)
            return res
        except ApiError as exc:
            self._fail(started, exc.message)
            raise
        except Exception as exc:
            self._fail(started, str(exc))
            raise ApiError(
                "gui_set_temperature_failed", str(exc), detail=traceback.format_exc()
            ) from exc

    def gui_set_report_conditions(
        self, conditions: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """设置 GUI 的报告工况字段（部分更新，``null`` 清空该字段）。

        字段集随当前测试模式变化，而模式只存在于 GUI 进程里，因此先做一次
        只读的 ``get_report_context`` 拿口径，再按该模式的字段表校验：把短路
        字段写进双脉冲报告（或反之）在界面上是看不见的，只能在这里挡掉。
        """
        if not isinstance(conditions, dict) or not conditions:
            raise ApiError(
                "missing_param", "缺少必填参数：至少给出一个报告工况字段"
            )
        started = self._begin("gui_set_report_conditions")
        try:
            bridge = self._require_gui_bridge()
            context = bridge.invoke("get_report_context", {}, timeout=15.0)
            mode_key = _gui_report_mode_key(
                context.get("test_mode") if isinstance(context, dict) else None
            )
            allowed = (
                _GUI_SHORT_REPORT_CONDITION_FIELDS
                if mode_key == "short"
                else _GUI_DPT_REPORT_CONDITION_FIELDS
            )
            unknown = sorted(set(conditions) - set(allowed))
            if unknown:
                raise ApiError(
                    "mode_mismatch",
                    f"当前测试模式为 {mode_key}，可用工况字段："
                    f"{', '.join(allowed)}；本次传入的 {', '.join(unknown)} "
                    "不属于该模式",
                )
            payload = {
                field: _gui_condition_value(field, raw)
                for field, raw in conditions.items()
            }
            res = bridge.invoke("set_report_conditions", payload, timeout=15.0)
            self._end(started)
            return res
        except ApiError as exc:
            self._fail(started, exc.message)
            raise
        except Exception as exc:
            self._fail(started, str(exc))
            raise ApiError(
                "gui_set_report_conditions_failed",
                str(exc),
                detail=traceback.format_exc(),
            ) from exc

    def gui_get_report_context(self) -> dict[str, Any]:
        """查询当前 GUI 会写进报告的温度与工况口径。

        取值由 GUI 走页面状态（控件与内存态），不回读 QSettings：设置只是
        控件状态的镜像，页面保存时还会反过来覆盖它。
        """
        started = self._begin("gui_get_report_context")
        try:
            bridge = self._require_gui_bridge()
            res = bridge.invoke("get_report_context", {}, timeout=15.0)
            self._end(started)
            return res
        except ApiError as exc:
            self._fail(started, exc.message)
            raise
        except Exception as exc:
            self._fail(started, str(exc))
            raise ApiError(
                "gui_get_report_context_failed",
                str(exc),
                detail=traceback.format_exc(),
            ) from exc

    # ------------------------------------------------------------------ 分发

    def dispatch(self, command: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """把（命令名, 参数字典）路由到对应方法，供 HTTP/CLI 层复用。"""
        params = dict(params or {})
        handlers = {
            "health": lambda: self.health(),
            "status": lambda: self.status(),
            "list_samples": lambda: self.list_samples(params.get("root")),
            "get_profile": lambda: self.get_profile(),
            "set_profile": lambda: self.set_profile(
                phase=params.get("phase"),
                bridge=params.get("bridge"),
                mapping=params.get("mapping"),
                persist=bool(params.get("persist", False)),
            ),
            "get_slope_ranges": lambda: self.get_slope_ranges(),
            "set_slope_range": lambda: self.set_slope_range(
                params["section"],
                params["name"],
                start_pct=params.get("start_pct"),
                end_pct=params.get("end_pct"),
                ic_reference=params.get("ic_reference"),
                ic_direction=params.get("ic_direction"),
                auto_max=bool(params.get("auto_max", False)),
                recalculate=bool(params.get("recalculate", True)),
            ),
            "load_session": lambda: self.load_session(
                params["path"],
                phase=params.get("phase"),
                bridge=params.get("bridge"),
                test_mode=params.get("test_mode"),
                vdc_override=params.get("vdc_override"),
                mapping=params.get("mapping"),
                auto_extract=bool(params.get("auto_extract", True)),
            ),
            "close_session": lambda: self.close_session(),
            "run_extraction": lambda: self.run_extraction(
                array_mode=str(params.get("array_mode", "summary"))
            ),
            "extract_file": lambda: self.extract_file(
                params["path"],
                phase=params.get("phase"),
                bridge=params.get("bridge"),
                test_mode=params.get("test_mode"),
                vdc_override=params.get("vdc_override"),
                mapping=params.get("mapping"),
                array_mode=str(params.get("array_mode", "summary")),
            ),
            "extract_all": lambda: self.extract_all(
                list(params.get("paths") or []),
                phase=params.get("phase"),
                bridge=params.get("bridge"),
                test_mode=params.get("test_mode"),
                vdc_override=params.get("vdc_override"),
                array_mode=str(params.get("array_mode", "summary")),
                continue_on_error=bool(params.get("continue_on_error", True)),
            ),
            "get_result": lambda: self.get_result(
                array_mode=str(params.get("array_mode", "summary"))
            ),
            "set_pulse_selection": lambda: self.set_pulse_selection(
                off_pulse=params.get("off_pulse"),
                on_pulse=params.get("on_pulse"),
            ),
            "list_contexts": lambda: self.list_contexts(),
            "get_context": lambda: self.get_context(params["section"], params["name"]),
            "set_manual_cursor": lambda: self.set_manual_cursor(
                params["section"],
                params["name"],
                t_a_us=float(params["t_a_us"]),
                t_b_us=float(params["t_b_us"]),
            ),
            "clear_manual_cursor": lambda: self.clear_manual_cursor(
                params.get("section"), params.get("name")
            ),
            "export_xlsx": lambda: self.export_xlsx(params.get("path")),
            "export_all": lambda: self.export_all(
                list(params.get("paths") or []),
                params["output_dir"],
                phase=params.get("phase"),
                bridge=params.get("bridge"),
                test_mode=params.get("test_mode"),
                vdc_override=params.get("vdc_override"),
            ),
            "gui_set_template": lambda: self.gui_set_template(params.get("path")),
            "gui_set_output": lambda: self.gui_set_output(params.get("path")),
            "gui_load_file": lambda: self.gui_load_file(
                params.get("path"),
                phase=params.get("phase"),
                bridge=params.get("bridge"),
                test_mode=params.get("test_mode"),
            ),
            "gui_write_report": lambda: self.gui_write_report(
                timeout=float(params.get("timeout", 60.0))
            ),
            "gui_set_temperature": lambda: self.gui_set_temperature(
                params.get("code"), params.get("value")
            ),
            # 工况命令的 params 本身就是「字段: 值」字典，没有外层包装键。
            "gui_set_report_conditions": lambda: self.gui_set_report_conditions(
                params
            ),
            "gui_get_report_context": lambda: self.gui_get_report_context(),
        }
        handler = handlers.get(command)
        if handler is None:
            raise ApiError("unknown_command", f"未知命令：{command}")
        return handler()