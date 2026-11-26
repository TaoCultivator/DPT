"""启动前置检查（Qt 加载失败诊断）的纯逻辑校验。

不弹窗、不依赖 Qt、不依赖真实语料：只验证现场收集、DLL 探测、日志写入与
提示文案四条路径，以及 ``main.py`` 确实接上了这道守卫。
"""
from __future__ import annotations

from pathlib import Path

from dpt_extractor import __version__
from dpt_extractor.utils import qt_bootstrap


def test_probe_required_dlls_reports_missing_and_found(tmp_path: Path):
    (tmp_path / "Qt6Core.dll").write_bytes(b"stub")
    lines = qt_bootstrap.probe_required_dlls([tmp_path])
    found = [line for line in lines if "Qt6Core.dll" in line]
    missing = [line for line in lines if "Qt6Widgets.dll" in line]
    assert found and found[0].strip().startswith("找到")
    assert missing and missing[0].strip().startswith("缺失")
    assert len(lines) == len(qt_bootstrap._REQUIRED_DLLS)


def test_collect_diagnostics_contains_version_form_and_dll_section(tmp_path: Path):
    text = qt_bootstrap.collect_diagnostics(search_dirs=[tmp_path])
    assert f"DPT {__version__}" in text
    assert "运行形态" in text
    assert "关键文件检查" in text
    assert str(tmp_path) in text
    assert "异常：" not in text


def test_collect_diagnostics_includes_exception_traceback(tmp_path: Path):
    try:
        raise ImportError("DLL load failed while importing QtWidgets")
    except ImportError as exc:
        text = qt_bootstrap.collect_diagnostics(exc, search_dirs=[tmp_path])
    assert "异常：" in text
    assert "DLL load failed while importing QtWidgets" in text
    assert "Traceback" in text


def test_write_failure_log_uses_given_directory(tmp_path: Path):
    target = qt_bootstrap.write_failure_log("现场", log_dir=tmp_path)
    assert target == tmp_path / qt_bootstrap.LOG_FILE_NAME
    assert target is not None and target.read_text(encoding="utf-8") == "现场"


def test_format_failure_message_points_at_log_and_exception(tmp_path: Path):
    log_path = tmp_path / qt_bootstrap.LOG_FILE_NAME
    message = qt_bootstrap.format_failure_message(log_path, ImportError("缺少模块"))
    assert log_path.name in message
    assert "ImportError: 缺少模块" in message
    assert "Qt" in message


def test_format_failure_message_handles_unwritable_log_and_long_text():
    message = qt_bootstrap.format_failure_message(None, RuntimeError("x" * 500))
    assert "无法写入磁盘" in message
    assert "…" in message


def test_report_startup_failure_writes_log_without_dialog(tmp_path: Path):
    code = qt_bootstrap.report_startup_failure(
        ImportError("DLL load failed while importing QtWidgets"),
        show_dialog=False,
        log_dir=tmp_path,
        search_dirs=[tmp_path],
    )
    assert code == 1
    written = (tmp_path / qt_bootstrap.LOG_FILE_NAME).read_text(encoding="utf-8")
    assert "DLL load failed while importing QtWidgets" in written


def test_main_entry_is_wired_to_startup_guard():
    main_source = (Path(__file__).resolve().parents[2] / "main.py").read_text(encoding="utf-8")
    assert "report_startup_failure" in main_source
    assert "except Exception as _gui_import_error" in main_source
