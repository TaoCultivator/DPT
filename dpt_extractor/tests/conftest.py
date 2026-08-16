from __future__ import annotations

import pytest


@pytest.fixture(scope="session", autouse=True)
def isolate_qsettings_root(tmp_path_factory):
    """Redirect organization-based QSettings to one temporary test root."""
    from PyQt6.QtCore import QSettings

    settings_root = tmp_path_factory.mktemp("qsettings")
    yield settings_root / "DPTExtractor.ini"


@pytest.fixture(autouse=True)
def reset_production_qsettings(isolate_qsettings_root, monkeypatch):
    """Give each test a clean app store without touching real user settings."""
    from PyQt6.QtCore import QSettings
    from dpt_extractor.gui import main_window

    def settings_factory(*_args, **_kwargs):
        return QSettings(
            str(isolate_qsettings_root),
            QSettings.Format.IniFormat,
        )

    monkeypatch.setattr(main_window, "QSettings", settings_factory)

    settings = settings_factory()
    settings.clear()
    settings.setValue("license/noncommercial_notice_shown", True)
    settings.sync()
    yield
    settings.clear()
    settings.sync()
