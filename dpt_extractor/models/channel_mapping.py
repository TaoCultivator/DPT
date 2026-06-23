from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable

import yaml

from dpt_extractor.models.bridge_profile import BridgeProfile, make_profile
from dpt_extractor.models.waveform import (
    WaveformBundle,
    channel_reference_base_name,
    normalize_channel_reference,
)


def sort_channel_names(names: Iterable[str]) -> list[str]:
    """CH1..CH8 then MATH1..MATHn, matching Tekscope column order."""

    def sort_key(name: str) -> tuple[int, int, int, str]:
        normalized = normalize_channel_reference(name)
        signed = 1 if normalized.startswith("-") else 0
        base = channel_reference_base_name(normalized)
        m = re.fullmatch(r"(CH|MATH)(\d+)", base)
        if not m:
            return (2, 0, signed, normalized)
        return (0 if m.group(1) == "CH" else 1, int(m.group(2)), signed, normalized)

    return sorted(names, key=sort_key)


def infer_mapping_from_bundle(
    bundle: WaveformBundle | None,
    bridge: str,
) -> ChannelMapping | None:
    """Infer mapping from waveform channel labels; returns None if labels are missing."""
    if bundle is None or not bundle.meta.channel_labels:
        return None
    from dpt_extractor.io.label_mapping import infer_channel_mapping

    return infer_channel_mapping(
        bundle.meta.channel_labels,
        bridge,
        set(bundle.channels.keys()),
    )


def infer_mapping_from_waveform_trends(
    bundle: WaveformBundle | None,
    bridge: str,
) -> ChannelMapping | None:
    """Infer DPT mapping from waveform shape trends without trusting labels."""
    if bundle is None:
        return None
    from dpt_extractor.io.waveform_mapping import (
        infer_channel_mapping_from_waveform_trends,
    )

    return infer_channel_mapping_from_waveform_trends(bundle, bridge)


def infer_best_mapping_from_bundle(
    bundle: WaveformBundle | None,
    bridge: str,
) -> tuple[ChannelMapping | None, str]:
    """Try waveform trends first, then TSS labels as a fallback."""
    inferred = infer_mapping_from_waveform_trends(bundle, bridge)
    if inferred is not None:
        return inferred, "trend"
    inferred = infer_mapping_from_bundle(bundle, bridge)
    if inferred is not None:
        return inferred, "label"
    return None, ""


def infer_short_circuit_mapping_from_bundle(
    bundle: WaveformBundle | None,
    bridge: str,
) -> ChannelMapping | None:
    """Infer short-circuit mapping from waveform channel labels."""
    if bundle is None or not bundle.meta.channel_labels:
        return None
    from dpt_extractor.io.label_mapping import infer_short_circuit_mapping

    return infer_short_circuit_mapping(
        bundle.meta.channel_labels,
        bridge,
        set(bundle.channels.keys()),
    )


def channels_for_mapping(
    bundle: WaveformBundle | None,
    *,
    include_inverted: bool = False,
) -> list[str]:
    """Channel names available in the mapping UI from the loaded TSS."""
    if bundle is None:
        return []
    names = sort_channel_names(bundle.channels.keys())
    if include_inverted:
        names = sort_channel_names([*names, *(f"-{name}" for name in names)])
    return names

# logical_key -> (中文名, 简要说明)
LOGICAL_SIGNALS: tuple[tuple[str, str, str], ...] = (
    ("vge", "Vge", "被测管门极电压"),
    ("vce", "Vce", "被测管集射/漏源电压"),
    (
        "ic",
        "Ic",
        "被测管总电流；上桥多为下桥电流+IL 相加，下桥为实测总电流列",
    ),
    ("il", "IL", "电感电流探头"),
    (
        "irr",
        "下桥支路电流",
        "上桥：接下桥回路，关断下桥时即反向恢复分量，与 IL 相加得 Ic；下桥：由 Ic−IL 计算",
    ),
    ("v_diode", "V_二极管", "换流/对管二极管电压"),
    ("vge_other", "Vge_对管", "对管门极（串扰）"),
    ("vdesat", "Vdesat", "驱动器 DESAT 判定电压（短路可选）"),
)

LOGICAL_SIGNAL_KEYS: tuple[str, ...] = tuple(k for k, _, _ in LOGICAL_SIGNALS)
OPTIONAL_SIGNAL_KEYS = frozenset({"il", "irr", "v_diode", "vge_other", "vdesat"})
ALLOW_SHARED_SOURCE_KEYS = frozenset({"ic", "irr"})


@dataclass
class ChannelMapping:
    """Maps logical DPT signals to waveform channel names."""

    vge: str = "CH1"
    vce: str = "CH2"
    ic: str = "MATH1"
    il: str = "CH4"
    irr: str = "CH3"
    v_diode: str = "CH5"
    vge_other: str = "CH6"
    vdesat: str = ""
    #: True：总电流 = Irr 列 + IL 列逐点相加，忽略 ic 列映射
    ic_from_sum_irr_il: bool = False
    #: True：反向恢复 = Ic 列 − IL 列，忽略 irr 列映射
    irr_from_ic_minus_il: bool = False

    def to_dict(self) -> dict[str, str | bool]:
        d: dict[str, str | bool] = {k: getattr(self, k) for k in LOGICAL_SIGNAL_KEYS}
        d["ic_from_sum_irr_il"] = self.ic_from_sum_irr_il
        d["irr_from_ic_minus_il"] = self.irr_from_ic_minus_il
        return d

    @classmethod
    def from_profile(cls, profile: BridgeProfile) -> ChannelMapping:
        return cls(
            **{k: getattr(profile, k) for k in LOGICAL_SIGNAL_KEYS},
            ic_from_sum_irr_il=profile.ic_from_sum_irr_il,
            irr_from_ic_minus_il=profile.irr_from_ic_minus_il,
        )

    @classmethod
    def from_dict(cls, data: dict) -> ChannelMapping:
        base = cls()
        kwargs: dict[str, str | bool] = {}
        for k in LOGICAL_SIGNAL_KEYS:
            v = data.get(k)
            if v is None:
                kwargs[k] = getattr(base, k)
            else:
                kwargs[k] = normalize_channel_reference(str(v))
        kwargs["ic_from_sum_irr_il"] = bool(
            data.get("ic_from_sum_irr_il", getattr(base, "ic_from_sum_irr_il"))
        )
        kwargs["irr_from_ic_minus_il"] = bool(
            data.get("irr_from_ic_minus_il", getattr(base, "irr_from_ic_minus_il"))
        )
        return cls(**kwargs)


def apply_mapping(profile: BridgeProfile, mapping: ChannelMapping) -> BridgeProfile:
    d = mapping.to_dict()
    return replace(profile, **d)


def default_mapping_for(phase: str, bridge: str) -> ChannelMapping:
    return ChannelMapping.from_profile(make_profile(phase, bridge))


def validate_mapping(
    mapping: ChannelMapping,
    bundle: WaveformBundle | None,
    *,
    require_existing: bool = True,
) -> list[str]:
    errors: list[str] = []
    seen: dict[str, str] = {}

    def require_col(key: str, label: str) -> bool:
        col = str(getattr(mapping, key) or "")
        if col:
            return True
        errors.append(f"{label}: 须指定通道")
        return False

    def check_col(key: str, col: str) -> None:
        if not col:
            return
        col_ref = normalize_channel_reference(col)
        if (
            require_existing
            and bundle is not None
            and not bundle.has_channel_reference(col_ref)
        ):
            errors.append(f"{col} 在当前 TSS 中不存在")
        if (
            col_ref in seen
            and seen[col_ref] != key
            and {seen[col_ref], key} - ALLOW_SHARED_SOURCE_KEYS
        ):
            errors.append(f"{col_ref} 被重复分配给 {seen[col_ref]} 与 {key}")
        seen[col_ref] = key

    require_col("vge", "Vge")
    require_col("vce", "Vce")

    direct_ic = bool(mapping.ic)
    direct_irr = bool(mapping.irr)
    need_ic_formula = bool(mapping.ic_from_sum_irr_il and not direct_ic)
    need_irr_formula = bool(mapping.irr_from_ic_minus_il and not direct_irr)

    if need_ic_formula and need_irr_formula:
        errors.append("总电流 Irr+IL 与反向恢复 Ic−IL 不能同时作为兜底公式启用")

    if not direct_ic and not mapping.ic_from_sum_irr_il:
        errors.append("Ic: 须指定通道")

    if need_ic_formula:
        require_col("irr", "Irr")
        require_col("il", "IL")
        if (
            mapping.irr
            and mapping.il
            and channel_reference_base_name(mapping.irr)
            == channel_reference_base_name(mapping.il)
        ):
            errors.append("总电流为 Irr+IL 相加时，Irr 与 IL 不能选择同一列")

    if need_irr_formula:
        require_col("ic", "Ic")
        require_col("il", "IL")
        if (
            mapping.ic
            and mapping.il
            and channel_reference_base_name(mapping.ic)
            == channel_reference_base_name(mapping.il)
        ):
            errors.append("反向恢复为 Ic−IL 时，Ic 与 IL 不能选择同一列")

    for key in LOGICAL_SIGNAL_KEYS:
        col = getattr(mapping, key)
        if not col and key not in OPTIONAL_SIGNAL_KEYS:
            continue
        check_col(key, col)

    return errors


def active_mapping_keys(mapping: ChannelMapping) -> tuple[str, ...]:
    """Logical keys that are currently backed by a direct source channel."""
    return LOGICAL_SIGNAL_KEYS


def resolve_mapping_conflicts(
    mapping: ChannelMapping,
    changed_key: str,
    previous_channel: str = "",
) -> ChannelMapping:
    """Let the edited logical channel win, swapping the displaced role when possible."""
    if changed_key not in LOGICAL_SIGNAL_KEYS:
        return mapping
    keys = active_mapping_keys(mapping)
    if changed_key not in keys:
        return mapping
    current = normalize_channel_reference(getattr(mapping, changed_key) or "")
    if not current:
        return mapping

    conflicts = [
        key
        for key in keys
        if key != changed_key
        and normalize_channel_reference(getattr(mapping, key) or "") == current
    ]
    if not conflicts:
        return mapping

    data = mapping.to_dict()
    previous = str(previous_channel or "")
    previous_upper = normalize_channel_reference(previous)
    for conflict_key in conflicts:
        replacement = ""
        if previous and previous_upper != current:
            used_elsewhere = any(
                key not in {changed_key, conflict_key}
                and normalize_channel_reference(getattr(mapping, key) or "")
                == previous_upper
                for key in keys
            )
            if not used_elsewhere:
                replacement = previous
        data[conflict_key] = replacement
    return ChannelMapping.from_dict(data)


class ChannelMappingStore:
    """Persist user overrides per phase+bridge (e.g. U_upper)."""

    def __init__(self, path: str | Path | None = None):
        if path is None:
            from dpt_extractor.utils.app_paths import (
                seed_user_channel_maps_if_missing,
                user_channel_maps_path,
            )

            seed_user_channel_maps_if_missing()
            path = user_channel_maps_path()
        self.path = Path(path)
        self._data: dict[str, dict[str, str | bool]] = {}
        self.load()

    @staticmethod
    def _source_token(source_path: str | Path | None = None) -> str:
        if not source_path:
            return ""
        try:
            text = str(Path(source_path).expanduser().resolve(strict=False))
        except OSError:
            text = str(source_path)
        text = text.replace("\\", "/").lower()
        return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:16]

    def _key(
        self,
        phase: str,
        bridge: str,
        source_path: str | Path | None = None,
    ) -> str:
        base = f"{phase.upper()}_{bridge.lower()}"
        token = self._source_token(source_path)
        return f"{base}::{token}" if token else base

    def load(self) -> None:
        try:
            exists = self.path.exists()
        except OSError:
            self._data = {}
            return
        if not exists:
            self._data = {}
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
        except OSError:
            self._data = {}
            return
        self._data = dict(raw.get("mappings", {}))

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                yaml.safe_dump(
                    {"mappings": self._data},
                    f,
                    allow_unicode=True,
                    sort_keys=False,
                )
        except OSError:
            return

    def get(
        self,
        phase: str,
        bridge: str,
        source_path: str | Path | None = None,
    ) -> ChannelMapping | None:
        key = self._key(phase, bridge, source_path)
        if key not in self._data:
            return None
        mapping = ChannelMapping.from_dict(self._data[key])
        if mapping.to_dict() == default_mapping_for(phase, bridge).to_dict():
            return None
        return mapping

    def set(
        self,
        phase: str,
        bridge: str,
        mapping: ChannelMapping,
        source_path: str | Path | None = None,
    ) -> None:
        self._data[self._key(phase, bridge, source_path)] = mapping.to_dict()
        self.save()

    def clear(
        self,
        phase: str,
        bridge: str,
        source_path: str | Path | None = None,
    ) -> None:
        key = self._key(phase, bridge, source_path)
        if key in self._data:
            del self._data[key]
            self.save()

    def has_custom(
        self,
        phase: str,
        bridge: str,
        source_path: str | Path | None = None,
    ) -> bool:
        return self.get(phase, bridge, source_path) is not None
