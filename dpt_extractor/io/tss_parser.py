from __future__ import annotations

import re
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

import numpy as np
from tm_data_types import read_file
from tm_data_types.datum.waveforms.analog_waveform import AnalogWaveform

from dpt_extractor.io.wfm_scope_display import read_wfm_vertical_scale_per_div
from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

_CHANNEL_RE = re.compile(r"^(CH[1-6]|MATH\d+)$", re.I)
_WFM_NAME_RE = re.compile(r"(CH[1-6]|MATH\d+)", re.I)


def _normalize_channel(name: str) -> str:
    upper = name.upper()
    if upper.startswith("MATH"):
        suffix = upper[4:]
        return f"MATH{suffix}" if suffix else upper
    return upper


def _channel_from_member(member: str) -> str | None:
    stem = PurePosixPath(member).stem
    match = _WFM_NAME_RE.fullmatch(stem) or _WFM_NAME_RE.search(stem)
    if not match:
        return None
    return _normalize_channel(match.group(1))


def _channel_from_waveform(wfm: AnalogWaveform) -> str | None:
    if wfm.source_name:
        token = wfm.source_name.split(",", 1)[0].strip()
        if _CHANNEL_RE.match(token):
            return _normalize_channel(token)
    return None


def _waveform_arrays(wfm: AnalogWaveform) -> tuple[np.ndarray, np.ndarray]:
    y = np.asarray(wfm.normalized_vertical_values, dtype=np.float64)
    if wfm.x_axis_values is not None:
        t = np.asarray(wfm.x_axis_values, dtype=np.float64)
    else:
        t = np.asarray(wfm.normalized_horizontal_values, dtype=np.float64)
    if len(t) != len(y):
        spacing = float(wfm.x_axis_spacing or 0.0)
        trigger = float(wfm.trigger_index or 0.0)
        idx = np.arange(len(y), dtype=np.float64)
        t = (idx - trigger) * spacing
    return t, y


class TssParser:
    """Parse Tektronix session (.tss) files — ZIP archives of .wfm waveforms."""

    def parse(self, path: str | Path) -> WaveformBundle:
        path = Path(path)
        if not zipfile.is_zipfile(path):
            raise ValueError("TSS 会话: 文件不是有效的 ZIP/TSS 格式")

        channels: dict[str, np.ndarray] = {}
        labels: dict[str, str] = {}
        vdiv: dict[str, float] = {}
        y_position: dict[str, float] = {}
        meta = TekMetadata()
        t_ref: np.ndarray | None = None

        with zipfile.ZipFile(path, "r") as zf:
            wfm_members = sorted(
                name
                for name in zf.namelist()
                if name.lower().endswith(".wfm")
                and not name.startswith("__MACOSX/")
                and not PurePosixPath(name).name.startswith(".")
            )
            if not wfm_members:
                raise ValueError("TSS 会话: 未找到 .wfm 波形文件")

            with tempfile.TemporaryDirectory(prefix="dpt_tss_") as tmp:
                tmp_path = Path(tmp)
                for member in wfm_members:
                    channel = _channel_from_member(member)
                    local = tmp_path / PurePosixPath(member).name
                    with zf.open(member) as src, open(local, "wb") as dst:
                        dst.write(src.read())

                    wfm = read_file(str(local))
                    if not isinstance(wfm, AnalogWaveform):
                        continue

                    channel = channel or _channel_from_waveform(wfm)
                    if not channel or channel in channels:
                        continue

                    t, y = _waveform_arrays(wfm)
                    if y.size == 0:
                        continue

                    channels[channel] = y
                    if t_ref is None:
                        t_ref = t
                        meta.sample_interval = float(wfm.x_axis_spacing or meta.sample_interval)
                        meta.zero_index = float(wfm.trigger_index or 0.0)
                        meta.record_length = int(y.size)
                        if wfm.meta_info is not None:
                            equipment = getattr(wfm.meta_info, "test_equipment", None)
                            if equipment:
                                meta.model = str(equipment)

                    label = ""
                    if wfm.meta_info and wfm.meta_info.waveform_label:
                        label = wfm.meta_info.waveform_label.strip()
                    if label:
                        labels[channel] = label

                    scale = read_wfm_vertical_scale_per_div(local)
                    if scale is not None:
                        vdiv[channel] = scale
                    if wfm.meta_info is not None and wfm.meta_info.y_position is not None:
                        y_position[channel] = float(wfm.meta_info.y_position)

        if not channels or t_ref is None:
            raise ValueError("TSS 会话: 未能解析有效波形通道")

        n = len(t_ref)
        for ch, y in list(channels.items()):
            if len(y) != n:
                channels[ch] = y[:n] if len(y) > n else np.pad(y, (0, n - len(y)))

        meta.source_path = str(path.resolve())
        meta.channel_labels = labels
        meta.channel_vdiv = vdiv
        meta.channel_y_position = y_position
        meta.record_length = n
        return WaveformBundle(t=t_ref, channels=channels, meta=meta)
