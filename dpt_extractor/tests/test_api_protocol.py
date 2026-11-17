"""End-to-end tests for the headless DPT API protocol.

覆盖：服务层（load / extract / context / manual cursor / export）与 HTTP 壳
（/health、/rpc 成败分支、token 鉴权）。全部使用真实 .tss 样例，确保协议层
与 GUI 共用同一条提取路径，数值不会分叉。
"""

from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request
import warnings
from pathlib import Path
from unittest.mock import patch

from dpt_extractor.api import gui_host
from dpt_extractor.api.serialization import result_to_dict
from dpt_extractor.api.server import create_server, start_in_thread
from dpt_extractor.api.service import ApiError, ApiService
from dpt_extractor.io.waveform_loader import load_waveform
from dpt_extractor.models.wiring import (
    TOPOLOGY_DIRECT_IC,
    TOPOLOGY_DPT_LOWER_SUB,
    TOPOLOGY_DPT_UPPER_SUM,
    detect_wiring,
)
from dpt_extractor.utils.sample_corpus import discover_sample_waveforms

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SAMPLE_ROOT = _PROJECT_ROOT / "示例文件"


def _pick_sample(*hints: str) -> Path:
    """Pick the first real .tss sample whose path contains every hint."""
    candidates = discover_sample_waveforms(_SAMPLE_ROOT)
    lowered = [(p, str(p).lower()) for p in candidates]

    if not hints:
        normal = [(p, text) for p, text in lowered if "short" not in text]
        if normal:
            lowered = normal

    for hint in hints:
        needle = hint.lower()
        matched = [p for p, text in lowered if needle in text]
        if matched:
            lowered = [(p, text) for p, text in lowered if p in matched]
    if not lowered:
        raise unittest.SkipTest(f"未找到包含 {hints} 的 .tss 样例")
    return lowered[0][0]


def _pick_by_wiring(topology: str) -> Path:
    """按接线拓扑选样，要求样本与被测判据同源。

    ``_pick_sample`` 用全路径子串匹配，``"dl"``/``"lt"`` 这种短 hint 会命中
    无关测试集（如 ``KSU2506/DCU/DL/LT``），且选出的样本可能没有 MATH 列，
    导致 ``detect_wiring`` 判为 unknown——测试能过，但接线校验一分没测到。

    这里改为：限定在 MCU24N9 目录内（按路径分段精确比对，不用子串，避免
    ``NDE36_MCU24A1`` 这类近似目录名误伤），再按拓扑筛选。找不到则跳过。
    """
    for path in discover_sample_waveforms(_SAMPLE_ROOT):
        if not any(part.upper() == "MCU24N9" for part in path.parts):
            continue
        try:
            if detect_wiring(load_waveform(path)).topology == topology:
                return path
        except Exception:  # noqa: BLE001 - 单个样本损坏不应中断选样
            continue
    raise unittest.SkipTest(f"MCU24N9 下未找到接线拓扑为 {topology} 的 .tss 样例")


class _ServiceBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sample = _pick_sample()

    def setUp(self) -> None:
        self.service = ApiService()


class TestServiceHealth(_ServiceBase):
    def test_health_reports_identity_and_clean_state(self) -> None:
        health = self.service.health()
        self.assertTrue(health["ok"])
        self.assertEqual(health["service"], "dpt-extractor-api")
        self.assertFalse(health["loaded"])
        self.assertFalse(health["has_result"])

    def test_status_before_load_has_no_waveform_fields(self) -> None:
        status = self.service.status()
        self.assertNotIn("sample_count", status)
        self.assertEqual(status["state"], "idle")

    def test_unknown_command_raises_api_error(self) -> None:
        with self.assertRaises(ApiError) as ctx:
            self.service.dispatch("no_such_command", {})
        self.assertEqual(ctx.exception.code, "unknown_command")


class TestServiceExtraction(_ServiceBase):
    def test_load_and_extract_returns_full_result(self) -> None:
        payload = self.service.load_session(self.sample)
        self.assertEqual(payload["source_path"], str(self.sample))
        self.assertGreater(payload["sample_count"], 0)
        result = payload["result"]
        self.assertIn("turn_off", result)
        self.assertIn("turn_on", result)
        self.assertIn("reverse_recovery", result)
        self.assertIn("segments_detail", result)
        # 数值必须来自真实提取，而不是空的默认 dataclass。
        self.assertNotEqual(result["vdc"], 0.0)

    def test_load_session_missing_file_raises(self) -> None:
        with self.assertRaises(ApiError) as ctx:
            self.service.load_session(_PROJECT_ROOT / "no_such_file.tss")
        self.assertEqual(ctx.exception.code, "file_not_found")

    def test_extract_without_waveform_raises(self) -> None:
        with self.assertRaises(ApiError) as ctx:
            self.service.run_extraction()
        self.assertEqual(ctx.exception.code, "no_waveform")

    def test_numpy_and_set_are_json_safe(self) -> None:
        payload = self.service.load_session(self.sample)["result"]
        # 不允许出现 NaN/Infinity 或无法序列化的对象。
        json.dumps(payload, allow_nan=False)
        self.assertIsInstance(payload["unavailable_metrics"], list)


class TestServiceContexts(_ServiceBase):
    def test_list_contexts_after_extraction(self) -> None:
        self.service.load_session(self.sample)
        contexts = self.service.list_contexts()
        self.assertIn("didt_contexts", contexts)
        self.assertTrue(contexts["didt_contexts"], "至少应有一个 di/dt 上下文")

    def test_get_context_returns_cursor(self) -> None:
        self.service.load_session(self.sample)
        contexts = self.service.list_contexts()
        section, name = contexts["dvdt_contexts"][0].split("/", 1)
        payload = self.service.get_context(section, name)
        self.assertEqual(payload["section"], section)
        self.assertEqual(payload["name"], name)
        self.assertIn("context", payload)

    def test_manual_cursor_recomputes_slope(self) -> None:
        self.service.load_session(self.sample)
        seg = self.service.get_result()["segments_detail"]["turn_on"]
        mid = (seg["t0_us"] + seg["t1_us"]) / 2.0
        updated = self.service.set_manual_cursor(
            "开通", "dv/dt", t_a_us=seg["t0_us"], t_b_us=mid
        )
        self.assertEqual(updated["section"], "开通")
        self.assertGreaterEqual(updated["value"], 0.0)
        self.assertEqual(updated["cursor"]["t_a_us"], seg["t0_us"])

    def test_manual_cursor_rejects_unsupported_metric(self) -> None:
        self.service.load_session(self.sample)
        with self.assertRaises(ApiError) as ctx:
            self.service.set_manual_cursor("开通", "Ton", t_a_us=1.0, t_b_us=2.0)
        self.assertEqual(ctx.exception.code, "unsupported_manual_cursor")

    def test_manual_cursor_rejects_degenerate_span(self) -> None:
        self.service.load_session(self.sample)
        with self.assertRaises(ApiError) as ctx:
            self.service.set_manual_cursor("开通", "dv/dt", t_a_us=5.0, t_b_us=5.0)
        self.assertEqual(ctx.exception.code, "invalid_cursor")

    def test_clear_manual_cursor(self) -> None:
        self.service.load_session(self.sample)
        seg = self.service.get_result()["segments_detail"]["turn_on"]
        self.service.set_manual_cursor(
            "开通", "dv/dt", t_a_us=seg["t0_us"], t_b_us=seg["t1_us"]
        )
        cleared = self.service.clear_manual_cursor("开通", "dv/dt")
        self.assertEqual(cleared["manual_cursors"], [])


class TestServiceSlopeRange(_ServiceBase):
    def test_set_slope_range_triggers_recalculation(self) -> None:
        self.service.load_session(self.sample)
        payload = self.service.set_slope_range(
            "关断过程", "dv/dt", start_pct=20.0, end_pct=80.0
        )
        self.assertEqual(payload["row_key"], "off_dvdt")
        self.assertEqual(payload["slope_ranges"]["off_dvdt"]["start_pct"], 20.0)
        self.assertIn("result", payload)

    def test_set_slope_range_rejects_non_slope_metric(self) -> None:
        with self.assertRaises(ApiError) as ctx:
            self.service.set_slope_range("开通", "Ton", start_pct=1.0, end_pct=2.0)
        self.assertEqual(ctx.exception.code, "unknown_slope_metric")

    def test_auto_max_mode(self) -> None:
        payload = self.service.set_slope_range(
            "开通", "di/dt", auto_max=True, recalculate=False
        )
        self.assertEqual(
            payload["slope_ranges"]["on_didt"]["selection_mode"], "auto_max"
        )


class TestServiceExport(_ServiceBase):
    def test_export_xlsx_writes_real_file(self) -> None:
        import tempfile

        self.service.load_session(self.sample)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "report.xlsx"
            payload = self.service.export_xlsx(target)
            self.assertTrue(payload["exists"])
            self.assertGreater(payload["size_bytes"], 0)

    def test_export_without_result_raises(self) -> None:
        with self.assertRaises(ApiError) as ctx:
            self.service.export_xlsx("whatever.xlsx")
        self.assertEqual(ctx.exception.code, "no_result")


class TestListSamples(_ServiceBase):
    def test_discovers_real_samples(self) -> None:
        payload = self.service.list_samples()
        self.assertGreater(payload["count"], 0)
        self.assertTrue(all(path.endswith(".tss") for path in payload["samples"]))


class TestHttpShell(_ServiceBase):
    def setUp(self) -> None:
        super().setUp()
        self.handle = start_in_thread(port=0, service=self.service)
        self.addCleanup(self.handle.stop)

    def _url(self, path: str) -> str:
        return f"{self.handle.base_url}{path}"

    def _post(self, command: str, params: dict | None = None) -> dict:
        body = json.dumps({"command": command, "params": params or {}}).encode()
        request = urllib.request.Request(
            self._url("/rpc"),
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_health_endpoint(self) -> None:
        with urllib.request.urlopen(self._url("/health"), timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["service"], "dpt-extractor-api")

    def test_rpc_load_and_extract(self) -> None:
        payload = self._post("load_session", {"path": str(self.sample)})
        self.assertTrue(payload["ok"])
        self.assertGreater(payload["data"]["sample_count"], 0)
        self.assertIn("turn_off", payload["data"]["result"])

    def test_rpc_business_error_is_200_with_ok_false(self) -> None:
        payload = self._post("run_extraction")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "no_waveform")

    def test_rpc_unknown_command(self) -> None:
        payload = self._post("does_not_exist")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "unknown_command")

    def test_rpc_missing_required_param(self) -> None:
        payload = self._post("get_context", {"section": "开通"})
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "missing_param")


class TestHttpAuth(_ServiceBase):
    def test_token_required_when_configured(self) -> None:
        handle = start_in_thread(port=0, service=ApiService(), token="s3cret")
        self.addCleanup(handle.stop)
        body = json.dumps({"command": "health"}).encode()
        request = urllib.request.Request(
            f"{handle.base_url}/rpc",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "unauthorized")

        request = urllib.request.Request(
            f"{handle.base_url}/rpc",
            data=body,
            headers={"Content-Type": "application/json", "X-DPT-Token": "s3cret"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertTrue(payload["ok"])


class TestTestModeIsolation(_ServiceBase):
    """回归：test_mode 不得跨请求粘滞。

    历史缺陷：load_session 里 cfg = self._cfg 是别名，
    cfg.test_mode.mode = ... 会直接改写共享配置，
    导致不传 test_mode 的下一次请求沿用上一次的模式。
    """

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        # 按接线拓扑选样，保证样本的物理接线与所用 profile 自洽。
        # 用 _pick_sample("dl","lt") 这类路径子串会命中无关测试集
        # （如 KSU2506/DCU/DL/LT），且可能选出无 MATH 列、拓扑 unknown 的样本，
        # 使测试「能过但接线校验一分没测到」。
        cls.short_circuit_sample = _pick_by_wiring(TOPOLOGY_DIRECT_IC)
        cls.dpt_sample = _pick_by_wiring(TOPOLOGY_DPT_UPPER_SUM)

    def test_mode_does_not_leak_across_requests(self) -> None:
        service = ApiService()
        service.load_session(
            self.short_circuit_sample,
            test_mode="short_circuit",
            auto_extract=False,
        )
        self.assertEqual(service.status()["test_mode"], "short_circuit")

        service.load_session(
            self.dpt_sample,
            auto_extract=False,
        )
        self.assertEqual(
            service.status()["test_mode"],
            "dpt",
            "不传 test_mode 时应回到基础配置，不能沿用上一次的 short_circuit",
        )

    def test_explicit_mode_overrides_residual_state(self) -> None:
        service = ApiService()
        service.load_session(
            self.short_circuit_sample,
            test_mode="short_circuit",
            auto_extract=False,
        )
        service.load_session(
            self.dpt_sample,
            test_mode="dpt",
            auto_extract=False,
        )
        self.assertEqual(service.status()["test_mode"], "dpt")

    def test_base_config_is_never_mutated(self) -> None:
        service = ApiService()
        baseline_mode = service._cfg.test_mode.mode
        baseline_vdc = service._cfg.vdc_override
        baseline_test_mode_obj = service._cfg.test_mode

        service.load_session(
            self.short_circuit_sample,
            test_mode="short_circuit",
            vdc_override=123.0,
            auto_extract=False,
        )

        self.assertEqual(
            service._cfg.test_mode.mode,
            baseline_mode,
            "共享的 _cfg.test_mode.mode 不得被单次请求改写",
        )
        self.assertEqual(
            service._cfg.vdc_override,
            baseline_vdc,
            "共享的 _cfg.vdc_override 不得被单次请求改写",
        )
        self.assertIs(
            service._cfg.test_mode,
            baseline_test_mode_obj,
            "嵌套的 _cfg.test_mode 必须保持同一对象，不能被替换",
        )

        # 会话级覆盖确实生效
        self.assertEqual(service._active_cfg().test_mode.mode, "short_circuit")
        self.assertEqual(service._active_cfg().vdc_override, 123.0)
        # 嵌套对象必须与基础配置分离，防止退化回浅赋值
        self.assertIsNot(
            service._active_cfg().test_mode,
            service._cfg.test_mode,
            "覆盖后的 test_mode 必须是新对象，否则基础配置会被原地修改",
        )

        service.close_session()
        self.assertEqual(service.status()["test_mode"], baseline_mode)

    def test_active_cfg_identity_follows_override_presence(self) -> None:
        """无覆盖时走快路径返回同一对象；有覆盖时返回新对象。"""
        service = ApiService()
        self.assertIs(
            service._active_cfg(),
            service._cfg,
            "无覆盖时应直接返回 _cfg（零开销快路径）",
        )

        service.load_session(
            self.short_circuit_sample,
            test_mode="short_circuit",
            auto_extract=False,
        )
        self.assertIsNot(
            service._active_cfg(),
            service._cfg,
            "有覆盖时应返回叠加后的新对象",
        )
        self.assertEqual(service._active_cfg().test_mode.mode, "short_circuit")

    def test_close_session_clears_overrides(self) -> None:
        """close_session 必须清空会话覆盖，让 _active_cfg 回落到基础配置。"""
        service = ApiService()
        service.load_session(
            self.short_circuit_sample,
            test_mode="short_circuit",
            auto_extract=False,
        )
        self.assertTrue(service._session_overrides, "加载后应存在会话覆盖")

        service.close_session()

        self.assertEqual(service._session_overrides, {})
        self.assertIs(
            service._active_cfg(),
            service._cfg,
            "close_session 后应回落为同一对象",
        )


class TestBatchRequiresExplicitMode(_ServiceBase):
    """回归：批量接口必须显式指定 test_mode。

    短路与双脉冲是两套不同的计算方法，产出语义不同的结果对象，
    不能在同一批次中混合（SMC_UH + short_circuit 会把 Irr 当 Ic 直读，
    能跑通但数值全错）。自动推断已撤销。
    """

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.dpt_sample = _pick_by_wiring(TOPOLOGY_DPT_UPPER_SUM)
        cls.short_circuit_sample = _pick_by_wiring(TOPOLOGY_DIRECT_IC)

    def test_extract_all_rejects_missing_mode(self) -> None:
        with self.assertRaises(ApiError) as ctx:
            ApiService().extract_all([self.dpt_sample])
        self.assertEqual(ctx.exception.code, "missing_test_mode")

    def test_export_all_rejects_missing_mode(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ApiError) as ctx:
                ApiService().export_all([self.dpt_sample], tmp)
        self.assertEqual(ctx.exception.code, "missing_test_mode")

    def test_extract_all_accepts_explicit_dpt(self) -> None:
        payload = ApiService().extract_all([self.dpt_sample], test_mode="dpt")
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["ok"], 1)

    def test_extract_all_accepts_explicit_short_circuit(self) -> None:
        payload = ApiService().extract_all(
            [self.short_circuit_sample], test_mode="short_circuit"
        )
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["ok"], 1)
        # 只断言 ok==1 不够：模式选错时也可能跑通但数值全错。
        # 这里钉住结果对象确实是短路语义，而不是 dpt 结果被错标。
        result = payload["items"][0]["result"]
        self.assertTrue(
            result["short_circuit_mode"],
            "短路批次产出的结果必须标记 short_circuit_mode=True",
        )

        # ExtractResult 是统一 dataclass：短路模式下双脉冲字段填 0 占位，
        # 不是从结构里删除。所以判据不能写「字段不存在」，要写「双向」：
        #   短路字段必须有真值  +  双脉冲字段必须是空壳
        # 反过来若模式串味（短路样本被当 dpt 跑），short_circuit.ic_max 会归零
        # 而 turn_off 出现非零值。只断言 ok==1 抓不到这种错。
        short = result["short_circuit"]
        self.assertGreater(
            short["ic_max"],
            0.0,
            "短路结果必须带真实的 ic_max",
        )
        self.assertGreater(
            short["tsc"],
            0.0,
            "短路结果必须带真实的 tsc",
        )
        self.assertEqual(
            result["turn_off"]["ic_off_max"],
            0.0,
            "短路模式下双脉冲的 turn_off 应为空壳（全部 0），"
            "若出现非零值说明模式串味",
        )
        self.assertEqual(
            result["turn_on"]["ic_on_max"],
            0.0,
            "短路模式下双脉冲的 turn_on 应为空壳（全部 0）",
        )


class TestSessionCfgGlobalFieldsSync(_ServiceBase):
    """回归：会话覆盖存在时，全局运行时设置仍须实时生效。

    历史缺陷：``_session_cfg`` 是 load 时刻的整份快照，而 ``set_slope_range``
    里是 ``self._cfg.slope_ranges = current``（整体重新赋值 dict），浅拷贝的
    会话副本仍指旧 dict，导致 ``run_extraction`` 用旧端点计算，与
    ``get_slope_ranges`` 报告的值不一致。

    现行实现改为增量覆盖（``_session_overrides``），每次从 ``_cfg`` 现派生，
    这两个用例钉住该行为，防止有人改回整份快照或加字段白名单。
    """

    def test_slope_ranges_visible_while_session_override_active(self) -> None:
        sample = _pick_by_wiring(TOPOLOGY_DIRECT_IC)
        service = ApiService()
        service.load_session(
            sample,
            test_mode="short_circuit",
            auto_extract=False,
        )
        self.assertTrue(service._session_overrides, "前置：应存在会话覆盖")

        service.set_slope_range(
            "关断过程",
            "dv/dt",
            start_pct=20.0,
            end_pct=80.0,
            recalculate=False,
        )

        self.assertEqual(
            service._active_cfg().slope_ranges,
            service._cfg.slope_ranges,
            "会话覆盖存在时，_active_cfg 的 slope_ranges 必须与 _cfg 一致；"
            "不一致说明会话副本又持有旧 dict",
        )

    def test_pulse_selection_visible_while_session_override_active(self) -> None:
        sample = _pick_by_wiring(TOPOLOGY_DIRECT_IC)
        service = ApiService()
        service.load_session(
            sample,
            test_mode="short_circuit",
            auto_extract=False,
        )

        service.set_pulse_selection(off_pulse=3, on_pulse=4)

        active = service._active_cfg().pulse_selection
        self.assertEqual(active.off_pulse, 3)
        self.assertEqual(active.on_pulse, 4)


class TestWiringConsistencyWarns(_ServiceBase):
    """回归：接线与 profile 不符时必须告警，不能被静默吞掉。

    ``SMC`` 上桥样本的接线是 ``CH3=Irr, CH4=IL, Ic=Irr+IL``。
    若用 ``short_circuit`` profile 去跑，profile 会把 CH3 当总电流直读，
    此时读到的其实是 Irr——能跑通、不报错、数值全错。
    接线校验的价值就在于把这种静默错误变成显式告警。
    """

    def test_short_circuit_profile_on_upper_sum_sample_warns(self) -> None:
        sample = _pick_by_wiring(TOPOLOGY_DPT_UPPER_SUM)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            ApiService().load_session(
                sample,
                test_mode="short_circuit",
                auto_extract=False,
            )

        wiring_warnings = [
            item
            for item in caught
            if "[wiring]" in str(item.message)
        ]
        self.assertTrue(
            wiring_warnings,
            "上桥接线样本配 short_circuit profile 必须触发 [wiring] 告警；"
            f"实际捕获到 {[str(w.message) for w in caught]}",
        )

    def test_matching_profile_does_not_warn(self) -> None:
        """接线与 profile 自洽时不应产生 [wiring] 告警（防误报）。"""
        sample = _pick_by_wiring(TOPOLOGY_DPT_UPPER_SUM)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            ApiService().load_session(
                sample,
                test_mode="dpt",
                auto_extract=False,
            )

        wiring_warnings = [
            item
            for item in caught
            if "[wiring]" in str(item.message)
        ]
        self.assertFalse(
            wiring_warnings,
            "接线与 profile 自洽时不应告警；"
            f"实际捕获到 {[str(w.message) for w in wiring_warnings]}",
        )


class _FakeGuiBridge:
    """记录 ``invoke`` 的假桥，模拟 GUI 线程回执而不碰任何 Qt 控件。

    ``get_report_context`` 返回的 ``test_mode`` 决定协议侧可用的工况字段表，
    因此 ``mode_mismatch`` 是被服务层拒掉的，而不是本假桥自己抛出来的——
    否则这条用例测的就只是「假的会抛异常」。
    """

    def __init__(self, test_mode: str = "dpt") -> None:
        self.test_mode = test_mode
        self.calls: list[tuple[str, dict, float]] = []

    def invoke(
        self,
        action: str,
        params: dict | None = None,
        *,
        timeout: float = 60.0,
    ) -> dict:
        payload = dict(params or {})
        self.calls.append((action, payload, float(timeout)))
        if action == "get_report_context":
            return {
                "test_mode": self.test_mode,
                "phase": "U",
                "bridge": "upper",
                "profile_code": "UH",
                "temperature_code": "HT",
                "temperature_value": 175.0,
                "temperatures": {"RT": 25.0, "HT": 175.0, "LT": -40.0},
                "temperature_labels": {"RT": "25℃", "HT": "175℃", "LT": "-40℃"},
                "conditions": {
                    "voltage_v": 750.0,
                    "current_a": None,
                    "rg_on_ohm": None,
                    "rg_off_ohm": None,
                    "cg_nf": None,
                },
                "template": None,
                "output": None,
                "result_mode_matches": None,
            }
        if action == "set_temperature":
            return {
                "code": payload.get("code"),
                "value": payload.get("value", 25.0),
                "bridge": "upper",
                "temperatures": {"RT": 25.0, "HT": 150.0, "LT": -40.0},
                "result_mode_matches": None,
            }
        if action == "set_report_conditions":
            mode = "short" if self.test_mode == "short_circuit" else "dpt"
            return {
                "mode": mode,
                "bridge": "upper",
                "conditions": payload,
                "result_mode_matches": None,
            }
        raise AssertionError(f"假桥收到未知动作：{action}")

    @property
    def actions(self) -> list[str]:
        return [action for action, _payload, _timeout in self.calls]


class TestGuiBridgeCommands(_ServiceBase):
    """温度工况 / 报告工况 / 报告口径三条新命令的服务层契约。

    本组验证「参数原样交给 GUI、非法输入挡在 GUI 之前、错误码稳定」；
    GUI 真机行为（QSettings 落键、控件联动）由 ``test_gui_smoke.py`` 覆盖。
    """

    def _install_bridge(self, bridge: _FakeGuiBridge | None) -> _FakeGuiBridge | None:
        patcher = patch.object(gui_host, "get_gui_bridge", return_value=bridge)
        patcher.start()
        self.addCleanup(patcher.stop)
        return bridge

    # ---------------------------------------------------------- set_temperature

    def test_set_temperature_forwards_code_and_value(self) -> None:
        bridge = self._install_bridge(_FakeGuiBridge())
        payload = self.service.gui_set_temperature(" ht ", 175.0)
        assert bridge is not None
        self.assertEqual(
            bridge.calls,
            [("set_temperature", {"code": "HT", "value": 175.0}, 15.0)],
            "服务层必须把 code 规整成大写并原样转发数值",
        )
        self.assertEqual(payload["code"], "HT")
        self.assertIn("result_mode_matches", payload)
        json.dumps(payload, allow_nan=False)

    def test_set_temperature_without_value_omits_value_key(self) -> None:
        bridge = self._install_bridge(_FakeGuiBridge())
        self.service.gui_set_temperature("LT")
        assert bridge is not None
        self.assertEqual(bridge.calls[0][1], {"code": "LT"})
        self.assertNotIn(
            "value",
            bridge.calls[0][1],
            "省略 value 时不得下发默认值，否则会覆盖该工况的既有温度",
        )

    def test_set_temperature_requires_code(self) -> None:
        bridge = self._install_bridge(_FakeGuiBridge())
        with self.assertRaises(ApiError) as ctx:
            self.service.gui_set_temperature(None)
        self.assertEqual(ctx.exception.code, "missing_param")
        assert bridge is not None
        self.assertEqual(bridge.calls, [], "缺参时不应触达 GUI")

    def test_set_temperature_rejects_invalid_code(self) -> None:
        bridge = self._install_bridge(_FakeGuiBridge())
        with self.assertRaises(ApiError) as ctx:
            self.service.gui_set_temperature("MT")
        self.assertEqual(ctx.exception.code, "invalid_temperature_code")
        assert bridge is not None
        self.assertEqual(bridge.calls, [])

    def test_set_temperature_rejects_out_of_range_and_non_finite(self) -> None:
        bridge = self._install_bridge(_FakeGuiBridge())
        for bad in (250.1, -100.1, float("nan"), float("inf"), "175", True):
            with self.subTest(value=bad):
                with self.assertRaises(ApiError) as ctx:
                    self.service.gui_set_temperature("HT", bad)
                self.assertEqual(ctx.exception.code, "invalid_temperature_value")
        assert bridge is not None
        self.assertEqual(bridge.calls, [], "越界值不应写进 QSettings")

    def test_set_temperature_accepts_range_boundaries(self) -> None:
        bridge = self._install_bridge(_FakeGuiBridge())
        for edge in (-100.0, 250.0):
            with self.subTest(value=edge):
                self.service.gui_set_temperature("HT", edge)
        assert bridge is not None
        self.assertEqual([call[1]["value"] for call in bridge.calls], [-100.0, 250.0])

    # ---------------------------------------------------- set_report_conditions

    def test_set_report_conditions_partial_update(self) -> None:
        bridge = self._install_bridge(_FakeGuiBridge("dpt"))
        payload = self.service.gui_set_report_conditions({"voltage_v": 750.0})
        assert bridge is not None
        self.assertEqual(
            bridge.actions,
            ["get_report_context", "set_report_conditions"],
            "必须先只读查询口径，再按当前模式的字段表校验后下发",
        )
        self.assertEqual(bridge.calls[1][1], {"voltage_v": 750.0})
        self.assertEqual(payload["mode"], "dpt")
        self.assertIn("result_mode_matches", payload)
        json.dumps(payload, allow_nan=False)

    def test_set_report_conditions_null_clears_field(self) -> None:
        bridge = self._install_bridge(_FakeGuiBridge("dpt"))
        self.service.gui_set_report_conditions({"current_a": None})
        assert bridge is not None
        self.assertEqual(bridge.calls[1][1], {"current_a": None})

    def test_set_report_conditions_rejects_cross_mode_field(self) -> None:
        bridge = self._install_bridge(_FakeGuiBridge("short_circuit"))
        with self.assertRaises(ApiError) as ctx:
            self.service.gui_set_report_conditions({"voltage_v": 750.0})
        self.assertEqual(ctx.exception.code, "mode_mismatch")
        message = ctx.exception.message
        self.assertIn("short", message, "错误信息必须写明当前模式")
        self.assertIn("vce_v", message, "错误信息必须列出该模式可用字段")
        assert bridge is not None
        self.assertEqual(
            bridge.actions,
            ["get_report_context"],
            "跨模式字段必须在触达写入口之前就被拒掉",
        )
        self.assertEqual(
            self.service.status()["state"],
            "failed",
            "校验失败也要收尾状态，不能把服务挂在 running",
        )

    def test_set_report_conditions_accepts_short_fields_in_short_mode(self) -> None:
        bridge = self._install_bridge(_FakeGuiBridge("short_circuit"))
        payload = self.service.gui_set_report_conditions({"vce_v": 800.0})
        assert bridge is not None
        self.assertEqual(bridge.calls[1][1], {"vce_v": 800.0})
        self.assertEqual(payload["mode"], "short")

    def test_set_report_conditions_rejects_negative_value(self) -> None:
        bridge = self._install_bridge(_FakeGuiBridge("dpt"))
        for bad in (-1.0, float("nan"), "750", True):
            with self.subTest(value=bad):
                with self.assertRaises(ApiError) as ctx:
                    self.service.gui_set_report_conditions({"voltage_v": bad})
                self.assertEqual(ctx.exception.code, "invalid_condition_value")
        assert bridge is not None
        self.assertNotIn(
            "set_report_conditions",
            bridge.actions,
            "非法数值不得写进 QSettings",
        )

    def test_set_report_conditions_requires_at_least_one_field(self) -> None:
        bridge = self._install_bridge(_FakeGuiBridge("dpt"))
        with self.assertRaises(ApiError) as ctx:
            self.service.dispatch("gui_set_report_conditions", {})
        self.assertEqual(ctx.exception.code, "missing_param")
        assert bridge is not None
        self.assertEqual(bridge.calls, [])

    # ----------------------------------------------------- get_report_context

    def test_get_report_context_is_json_safe_and_readonly(self) -> None:
        bridge = self._install_bridge(_FakeGuiBridge("dpt"))
        payload = self.service.gui_get_report_context()
        assert bridge is not None
        self.assertEqual(bridge.actions, ["get_report_context"])
        json.dumps(payload, allow_nan=False)
        expected_keys = (
            "test_mode",
            "phase",
            "bridge",
            "profile_code",
            "temperature_code",
            "temperature_value",
            "temperatures",
            "temperature_labels",
            "conditions",
            "template",
            "output",
            "result_mode_matches",
        )
        for key in expected_keys:
            self.assertIn(key, payload)
        self.assertIsNone(
            payload["result_mode_matches"],
            "无结果时 result_mode_matches 必须是 None，不能伪造成 True",
        )

    # ------------------------------------------------------------- 通用行为

    def test_gui_commands_without_bridge_report_unavailable(self) -> None:
        self._install_bridge(None)
        for call in (
            lambda: self.service.gui_set_temperature("RT"),
            lambda: self.service.gui_set_report_conditions({"voltage_v": 1.0}),
            lambda: self.service.gui_get_report_context(),
        ):
            with self.subTest(call=call):
                with self.assertRaises(ApiError) as ctx:
                    call()
                self.assertEqual(ctx.exception.code, "gui_bridge_unavailable")

    def test_dispatch_routes_new_gui_commands(self) -> None:
        bridge = self._install_bridge(_FakeGuiBridge("dpt"))
        temperature = self.service.dispatch(
            "gui_set_temperature", {"code": "HT", "value": 175.0}
        )
        self.assertEqual(temperature["code"], "HT")
        conditions = self.service.dispatch(
            "gui_set_report_conditions", {"voltage_v": 750.0}
        )
        self.assertEqual(conditions["mode"], "dpt")
        context = self.service.dispatch("gui_get_report_context")
        self.assertEqual(context["test_mode"], "dpt")
        assert bridge is not None
        self.assertEqual(
            bridge.actions,
            [
                "set_temperature",
                "get_report_context",
                "set_report_conditions",
                "get_report_context",
            ],
        )


class TestSerialization(unittest.TestCase):
    def test_result_to_dict_rejects_non_dataclass(self) -> None:
        with self.assertRaises(TypeError):
            result_to_dict({"not": "a dataclass"})


if __name__ == "__main__":
    unittest.main()