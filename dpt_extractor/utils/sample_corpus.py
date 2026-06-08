from __future__ import annotations

from pathlib import Path
import zipfile

_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "__pycache__",
    ".cursor",
    ".vscode",
    "build",
    "dist",
}

_SAMPLE_DIR_HINTS = (
    "示例",
    "样例",
    "sample",
    "samples",
    "example",
    "examples",
    "dataset",
    "data",
    "project",
)


def _is_tss_session(path: Path) -> bool:
    """Quick TSS sniff: valid zip with at least one .wfm member."""
    if path.suffix.lower() != ".tss":
        return False
    if not zipfile.is_zipfile(path):
        return False
    try:
        with zipfile.ZipFile(path, "r") as zf:
            return any(name.lower().endswith(".wfm") for name in zf.namelist())
    except OSError:
        return False


def _candidate_roots(root: Path) -> list[Path]:
    out = [root]
    try:
        top_dirs = [p for p in root.iterdir() if p.is_dir()]
    except OSError:
        return out
    for d in top_dirs:
        if d.name in _SKIP_DIRS:
            continue
        low = d.name.lower()
        if any(hint in low for hint in _SAMPLE_DIR_HINTS):
            out.append(d)
    return out


def discover_sample_waveforms(root: str | Path) -> list[Path]:
    """
    Discover TSS sample waveforms for compatibility regression/training.
    Priority is root-level waveforms first, then project sample folders
    such as 示例文件/samples/examples.
    """
    base = Path(root).resolve()
    seen: set[Path] = set()
    picked: list[Path] = []
    for candidate in _candidate_roots(base):
        for path in candidate.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() != ".tss":
                continue
            if any(part in _SKIP_DIRS for part in path.parts):
                continue
            full = path.resolve()
            if full in seen:
                continue
            if not _is_tss_session(full):
                continue
            seen.add(full)
            picked.append(full)
    picked.sort(key=lambda p: (str(p.parent), p.name))
    return picked
