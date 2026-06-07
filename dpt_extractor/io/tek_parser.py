from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from dpt_extractor.io.label_mapping import parse_channel_labels
from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

# Tekscope wide-table data columns (discovered from CSV header, not a fixed list).
_CHANNEL_RE = re.compile(r"^(CH[1-6]|MATH\d+)$")


class TekParser:
    """Parse TekscopeSW exported CSV (wide format with CH + MATH columns)."""

    def parse(self, path: str | Path) -> WaveformBundle:
        path = Path(path)
        header_row = self._find_header_row(path)
        meta = self._read_metadata(path, header_row)
        meta.source_path = str(path.resolve())
        meta.channel_labels = parse_channel_labels(path, header_row)

        df = pd.read_csv(path, skiprows=header_row)
        if "TIME" not in df.columns:
            raise ValueError("Tekscope CSV: 未找到 TIME 列")
        t = df["TIME"].to_numpy(dtype=np.float64)

        channels: dict[str, np.ndarray] = {}
        for col in df.columns:
            name = str(col).strip()
            if _CHANNEL_RE.match(name) and name not in channels:
                channels[name] = df[col].to_numpy(dtype=np.float64)

        if not channels:
            raise ValueError("Tekscope CSV: 未找到 CH/MATH 数据列")

        meta.record_length = len(t)
        return WaveformBundle(t=t, channels=channels, meta=meta)

    @staticmethod
    def _find_header_row(path: Path) -> int:
        """Locate the 0-based line index of the ``TIME,CH1,...`` data header."""
        with open(path, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                first = line.split(",", 1)[0].strip()
                if first == "TIME":
                    return i
        raise ValueError("Tekscope CSV: 未找到 TIME 表头行")

    def _read_metadata(self, path: Path, header_row: int) -> TekMetadata:
        meta = TekMetadata()
        with open(path, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= header_row:
                    break
                if line.startswith("Model,"):
                    meta.model = line.split(",", 1)[1].strip()
                elif "Sample Interval" in line:
                    m = re.search(r"([\d.eE+-]+)", line.split(",")[1])
                    if m:
                        meta.sample_interval = float(m.group(1))
                elif "Record Length" in line:
                    m = re.search(r"(\d+)", line.split(",")[1])
                    if m:
                        meta.record_length = int(m.group(1))
                elif "Zero Index" in line:
                    m = re.search(r"([\d.eE+-]+)", line.split(",")[1])
                    if m:
                        meta.zero_index = float(m.group(1))
        return meta
