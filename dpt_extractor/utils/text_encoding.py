from __future__ import annotations

import os
import sys
from typing import TextIO


def _reconfigure_stream(stream: TextIO | None) -> None:
    if stream is None:
        return
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (TypeError, ValueError, OSError):
            pass


def configure_utf8_text_io() -> None:
    """Keep Chinese text stable in Windows console and bundled runs."""
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    _reconfigure_stream(sys.stdout)
    _reconfigure_stream(sys.stderr)
