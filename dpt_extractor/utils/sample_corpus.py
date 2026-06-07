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


def _is_tekscope_csv(path: Path) -> bool:
    """Cheap CSV sniff: Tekscope data header contains a leading TIME column."""
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i > 300:
                    break
                first = line.split(",", 1)[0].strip()
                if first == "TIME":
                    return True
    except OSError:
        return False
    return False


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
    Discover Tekscope sample waveforms for compatibility regression/training.
    Priority:
    1) root-level waveform samples (legacy behavior)
    2) project sample folders (e.g. 示例文件/samples/examples/...)
    """
    base = Path(root).resolve()
    seen: set[Path] = set()
    picked: list[Path] = []
    for candidate in _candidate_roots(base):
        for path in candidate.rglob("*"):
            if not path.is_file():
                continue
            ext = path.suffix.lower()
            if ext not in (".csv", ".tss"):
                continue
            if any(part in _SKIP_DIRS for part in path.parts):
                continue
            full = path.resolve()
            if full in seen:
                continue
            if ext == ".csv":
                ok = _is_tekscope_csv(full)
            else:
                ok = _is_tss_session(full)
            if not ok:
                continue
            seen.add(full)
            picked.append(full)
    # Train with TSS first to preserve scope display scale consistency.
    picked.sort(key=lambda p: (0 if p.suffix.lower() == ".tss" else 1, str(p.parent), p.name))
    return picked


def discover_sample_csvs(root: str | Path) -> list[Path]:
    """Backward-compatible CSV-only alias used by older call sites."""
    return [p for p in discover_sample_waveforms(root) if p.suffix.lower() == ".csv"]
