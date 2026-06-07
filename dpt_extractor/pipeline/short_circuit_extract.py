"""短路测试参数提取（占位模块，与双脉冲 ``extract_all`` 隔离）。"""

from __future__ import annotations

from dpt_extractor.config.loader import AppConfig
from dpt_extractor.models.bridge_profile import BridgeProfile
from dpt_extractor.models.results import ExtractResult
from dpt_extractor.models.waveform import WaveformBundle


class ShortCircuitExtractNotReady(RuntimeError):
    """短路提取尚未实现时由 pipeline 抛出。"""


def extract_short_circuit(
    bundle: WaveformBundle,
    profile: BridgeProfile,
    cfg: AppConfig,
) -> ExtractResult:
    """短路测试参数提取入口（待实现）。"""
    _ = bundle, profile, cfg
    raise ShortCircuitExtractNotReady(
        "短路测试参数提取功能开发中，当前仅可浏览波形。"
    )
