from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from dpt_extractor.models.waveform import WaveformBundle


def load_waveform(
    path: str | Path,
    *,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> WaveformBundle:
    """Load a Tektronix TSS session into a WaveformBundle."""
    suffix = Path(path).suffix.lower()
    if suffix == ".tss":
        from dpt_extractor.io.tss_parser import TssParser

        return TssParser().parse(path, progress_callback=progress_callback)
    raise ValueError(f"仅支持 Tektronix TSS 会话文件 (.tss)，当前格式: {suffix or '(无扩展名)'}")
