"""Read Tektronix .wfm vertical display settings (V/div, A/div, position)."""

from __future__ import annotations

import struct
from pathlib import Path

from dpt_extractor.models.bridge_profile import BridgeProfile
from dpt_extractor.models.waveform import TekMetadata, channel_reference_base_name

# Tek .wfm: scope V/div = explicit_dimensions.scale × this factor.
# explicit_user_view.scale is zoom-adjusted and does not match the V/div readout.
_TEK_WFM_VERT_SCALE_TO_VDIV: float = 6400.0

WFMFile = None
WfmFormat = None
String8 = None
VersionNumber = None


def _wfm_dependencies():
    global WFMFile, WfmFormat, String8, VersionNumber
    if all(obj is not None for obj in (WFMFile, WfmFormat, String8, VersionNumber)):
        return WFMFile, WfmFormat, String8, VersionNumber

    from dpt_extractor.utils.app_paths import configure_numba_cache_dir

    configure_numba_cache_dir()
    from tm_data_types.files_and_formats.wfm.wfm import WFMFile as _WFMFile
    from tm_data_types.files_and_formats.wfm.wfm_format import WfmFormat as _WfmFormat
    from tm_data_types.helpers.byte_data_types import String8 as _String8
    from tm_data_types.helpers.enums import VersionNumber as _VersionNumber

    WFMFile = _WFMFile
    WfmFormat = _WfmFormat
    String8 = _String8
    VersionNumber = _VersionNumber
    return WFMFile, WfmFormat, String8, VersionNumber


def read_wfm_vertical_scale_per_div(path: str | Path) -> float | None:
    """Return scope vertical scale (units per division) from a .wfm file."""
    path = Path(path)
    wfm_file, wfm_format, string8, version_number_type = _wfm_dependencies()
    try:
        with path.open("rb") as fd:
            (byte_order,) = struct.unpack(">2s", fd.read(2))
            if byte_order not in wfm_file._ENDIAN_PREFIX_LOOKUP:
                return None
            endian_prefix = wfm_file._ENDIAN_PREFIX_LOOKUP[byte_order]
            version_value = string8.unpack(endian_prefix.struct, fd)
            version_number = version_number_type(version_value)
            formatted = wfm_format()
            formatted.unpack_wfm_file(endian_prefix, version_number, fd)
    except (OSError, ValueError, struct.error):
        return None

    exp_dim = formatted.explicit_dimensions
    if exp_dim is None or exp_dim.first is None:
        return None
    dim_scale = float(exp_dim.first.scale)
    if dim_scale <= 0 or not (dim_scale < float("inf")):
        return None
    return dim_scale * _TEK_WFM_VERT_SCALE_TO_VDIV


def scope_vdiv_by_logical(meta: TekMetadata, profile: BridgeProfile) -> dict[str, float]:
    """Map CH/MATH vertical scale (units/div) to logical waveform keys."""
    ch_vdiv = meta.channel_vdiv
    if not ch_vdiv:
        return {}
    out: dict[str, float] = {}
    ic_ch = (
        (profile.irr or profile.il)
        if profile.ic_from_sum_irr_il and not profile.ic
        else profile.ic
    )
    for key, ch in (
        ("vge", profile.vge),
        ("vce", profile.vce),
        ("ic", ic_ch),
        ("irr", profile.irr),
        ("v_diode", profile.v_diode),
        ("vge_other", profile.vge_other),
    ):
        base = channel_reference_base_name(ch)
        if base and base in ch_vdiv and key not in out:
            out[key] = ch_vdiv[base]
    return out


def scope_y_position_by_logical(meta: TekMetadata, profile: BridgeProfile) -> dict[str, float]:
    """Map CH/MATH yPosition (divisions) to logical waveform keys."""
    ch_pos = meta.channel_y_position
    if not ch_pos:
        return {}
    out: dict[str, float] = {}
    ic_ch = (
        (profile.irr or profile.il)
        if profile.ic_from_sum_irr_il and not profile.ic
        else profile.ic
    )
    for key, ch in (
        ("vge", profile.vge),
        ("vce", profile.vce),
        ("ic", ic_ch),
        ("irr", profile.irr),
        ("v_diode", profile.v_diode),
        ("vge_other", profile.vge_other),
    ):
        base = channel_reference_base_name(ch)
        if base and base in ch_pos and key not in out:
            out[key] = ch_pos[base]
    return out
