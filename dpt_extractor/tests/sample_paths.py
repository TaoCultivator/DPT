from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SAMPLE_ROOT = ROOT / "示例文件"


def sample_tss(name: str) -> Path:
    matches = sorted(SAMPLE_ROOT.rglob(name)) if SAMPLE_ROOT.exists() else []
    return matches[0] if matches else SAMPLE_ROOT / name
