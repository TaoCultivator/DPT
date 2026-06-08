from __future__ import annotations

import re
from pathlib import Path


def parse_setpoints_from_filename(path: str) -> tuple[float | None, float | None]:
    """
    Parse setpoints from filename like:
    WH_480V_800A_000.tss -> (480.0, 800.0)
    """
    stem = Path(path).stem.upper()
    m = re.search(r"(\d+(?:\.\d+)?)V[_-](\d+(?:\.\d+)?)A", stem)
    if not m:
        return None, None
    return float(m.group(1)), float(m.group(2))

