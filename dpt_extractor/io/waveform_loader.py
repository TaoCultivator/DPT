from __future__ import annotations

from pathlib import Path

from dpt_extractor.io.tek_parser import TekParser
from dpt_extractor.io.tss_parser import TssParser
from dpt_extractor.models.waveform import WaveformBundle


def load_waveform(path: str | Path) -> WaveformBundle:
    """Load Tekscope CSV or Tektronix TSS session into a WaveformBundle."""
    suffix = Path(path).suffix.lower()
    if suffix == ".csv":
        return TekParser().parse(path)
    if suffix == ".tss":
        return TssParser().parse(path)
    raise ValueError(f"不支持的波形文件格式: {suffix or '(无扩展名)'}")
