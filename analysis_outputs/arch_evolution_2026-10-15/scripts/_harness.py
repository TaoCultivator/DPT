"""共享工具：语料发现、样例分类、计时辅助。

本目录是架构演进议题（k-mv89ep9q-2）的测量脚手架。
不修改 ``dpt_extractor`` 下任何文件，只做只读调用。
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------- 路径解析

#: 本工作树根目录（脚本均从仓库根运行）
REPO_ROOT = Path(__file__).resolve().parents[3]

#: 语料目录：默认取同盘的 ``DPT/示例文件``（主工作树，git 忽略，不随分支走）
DEFAULT_CORPUS = Path(os.environ.get("DPT_CORPUS", r"E:\Works\DPT\示例文件"))

#: 原始数据输出目录
RAW_DIR = Path(__file__).resolve().parents[1] / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)


def ensure_repo_on_path() -> None:
    """确保导入的是本工作树里的 ``dpt_extractor``，而不是主工作树。"""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------- 样例分类

_SHORT_CIRCUIT_DIR_TOKENS = {"DL", "DDD", "SHORT"}
_SHORT_CIRCUIT_FILENAME_RE = re.compile(
    r"(?:^|[_-])short(?:[_-]|$)|^[UVW][HL][_-]\d+(?:\.\d+)?V[_-]0{3}$",
    re.IGNORECASE,
)


def is_short_circuit_sample(path: Path) -> bool:
    """与 ``scripts/validate_tss_samples.py::_is_short_circuit_sample`` 同口径。"""
    parts = {part.upper() for part in path.parts}
    if parts & _SHORT_CIRCUIT_DIR_TOKENS:
        return True
    return bool(_SHORT_CIRCUIT_FILENAME_RE.search(path.stem))


def corpus_files(corpus: Path = DEFAULT_CORPUS) -> list[Path]:
    ensure_repo_on_path()
    from dpt_extractor.utils.sample_corpus import discover_sample_waveforms

    return discover_sample_waveforms(corpus)


# ---------------------------------------------------------------- 计时辅助


@dataclass
class StageTimer:
    """按阶段累计耗时，可重复使用。"""

    totals: dict[str, float] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)

    def add(self, stage: str, seconds: float) -> None:
        self.totals[stage] = self.totals.get(stage, 0.0) + seconds
        self.counts[stage] = self.counts.get(stage, 0) + 1

    def phase(self, stage: str) -> "_Phase":
        return _Phase(self, stage)


class _Phase:
    def __init__(self, timer: StageTimer, stage: str) -> None:
        self._timer = timer
        self._stage = stage
        self._t0 = 0.0

    def __enter__(self) -> "_Phase":
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *exc) -> bool:
        self._timer.add(self._stage, time.perf_counter() - self._t0)
        return False


def write_json(name: str, payload) -> Path:
    path = RAW_DIR / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def human_mb(num_bytes: float) -> float:
    return round(num_bytes / 1024 / 1024, 3)
