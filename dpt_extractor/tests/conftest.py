from __future__ import annotations

import pytest


@pytest.fixture(scope="session", autouse=True)
def isolate_qsettings_root(tmp_path_factory):
    """Redirect organization-based QSettings to one temporary test root."""
    from PyQt6.QtCore import QSettings

    settings_root = tmp_path_factory.mktemp("qsettings")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        str(settings_root),
    )
    yield


@pytest.fixture(autouse=True)
def reset_production_qsettings(isolate_qsettings_root):
    """Give each test a clean app store without touching real user settings."""
    from PyQt6.QtCore import QSettings

    settings = QSettings("DPT", "DPTExtractor")
    settings.clear()
    settings.setValue("license/noncommercial_notice_shown", True)
    settings.sync()
    yield
    settings.clear()
    settings.sync()
