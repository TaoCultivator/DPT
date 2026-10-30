#!/usr/bin/env python3
"""DPT parameter extraction tool entry point."""

import sys
from pathlib import Path

# Ensure package root on path when run as script
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _restart_with_local_venv() -> None:
    """Run the app with the project virtual environment when available."""
    if sys.prefix == sys.base_prefix:
        venv_python = _ROOT / ".venv" / "Scripts" / "python.exe"
        if venv_python.exists() and Path(sys.executable).resolve() != venv_python.resolve():
            import os

            os.execv(str(venv_python), [str(venv_python), *sys.argv])


if __name__ == "__main__":
    _restart_with_local_venv()

from dpt_extractor.utils.text_encoding import configure_utf8_text_io
from dpt_extractor.utils.app_paths import configure_numba_cache_dir

configure_utf8_text_io()
configure_numba_cache_dir()

from PyQt6.QtWidgets import QApplication

from dpt_extractor.gui.main_window import MainWindow
from dpt_extractor.io.tek_scope import shutdown_tektronix_backend


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("DPT Extractor")
    app.setStyle("Fusion")
    win = MainWindow()
    win.showMaximized()
    try:
        return app.exec()
    finally:
        # Covers programmatic quit and startup/teardown paths that do not pass
        # through MainWindow.closeEvent().  The function is idempotent.
        win.shutdown_background_work()
        shutdown_tektronix_backend()


if __name__ == "__main__":
    raise SystemExit(main())
