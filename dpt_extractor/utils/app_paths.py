"""应用路径：开发目录 vs PyInstaller 打包后的资源/用户配置目录。"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from dpt_extractor import __version__

DEFAULT_REPORT_TEMPLATE_NAME = "默认报告模板.xlsx"
COMMERCIAL_NOTICE_POSTER_NAME = "noncommercial_authorization_poster.png"
_NUMBA_CACHE_VERSION_FILE = ".dpt_numba_cache_version"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False)) and hasattr(sys, "_MEIPASS")


def bundle_root() -> Path:
    """只读资源根（打包后为 _MEIPASS，开发时为项目根目录）。"""
    if is_frozen():
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[2]


def package_config_dir() -> Path:
    if is_frozen():
        return bundle_root() / "dpt_extractor" / "config"
    return Path(__file__).resolve().parents[1] / "config"


def default_config_path() -> Path:
    return package_config_dir() / "default.yaml"


def package_templates_dir() -> Path:
    if is_frozen():
        return bundle_root() / "dpt_extractor" / "templates"
    return bundle_root()


def default_report_template_path() -> Path:
    return package_templates_dir() / DEFAULT_REPORT_TEMPLATE_NAME


def package_assets_dir() -> Path:
    if is_frozen():
        return bundle_root() / "dpt_extractor" / "assets"
    return bundle_root() / "assets"


def commercial_notice_poster_path() -> Path:
    return package_assets_dir() / COMMERCIAL_NOTICE_POSTER_NAME


def copy_default_report_template(path: str | Path) -> Path:
    return copy_report_template(default_report_template_path(), path)


def copy_report_template(template_path: str | Path, path: str | Path) -> Path:
    dst = Path(path)
    if dst.suffix.lower() != ".xlsx":
        dst = dst.with_suffix(".xlsx")
    src = Path(template_path)
    if not src.is_file():
        raise FileNotFoundError(f"报告模板不存在: {src}")
    if src.resolve() == dst.resolve():
        raise ValueError("不能直接覆盖报告模板源文件，请另存为报告文件")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def user_data_dir() -> Path:
    """可写用户数据目录（通道映射等）。"""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or Path.home())
        root = base / "DPT"
    else:
        root = Path.home() / ".dpt"
    root.mkdir(parents=True, exist_ok=True)
    return root


def configure_numba_cache_dir() -> Path | None:
    """
    Pin Numba's cache to an application-controlled writable directory.

    Tektronix ``tm_data_types`` imports Numba during WFM parsing. On some Windows
    setups Numba's default cache probe can stall on temp/cache directories, so we
    set the location before that dependency is imported.
    """
    if os.environ.get("NUMBA_CACHE_DIR"):
        return Path(os.environ["NUMBA_CACHE_DIR"])

    candidates: list[Path] = []
    try:
        candidates.append(user_data_dir() / "numba_cache")
    except OSError:
        pass
    if not is_frozen():
        candidates.append(bundle_root() / ".numba_cache")

    for cache_dir in candidates:
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        _refresh_numba_cache_for_version(cache_dir)
        os.environ["NUMBA_CACHE_DIR"] = str(cache_dir)
        return cache_dir
    return None


def _refresh_numba_cache_for_version(cache_dir: Path) -> None:
    marker = cache_dir / _NUMBA_CACHE_VERSION_FILE
    try:
        cached_version = marker.read_text(encoding="utf-8").strip()
    except OSError:
        cached_version = ""
    if cached_version == __version__:
        return

    try:
        children = list(cache_dir.iterdir())
    except OSError:
        children = []

    for child in children:
        if child == marker:
            continue
        try:
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        except OSError:
            continue

    try:
        marker.write_text(__version__, encoding="utf-8")
    except OSError:
        pass


def user_channel_maps_path() -> Path:
    return user_data_dir() / "channel_maps_user.yaml"


def seed_user_channel_maps_if_missing() -> None:
    """首次运行：将内置默认通道映射模板复制到用户目录。"""
    dst = user_channel_maps_path()
    try:
        if dst.exists():
            return
    except OSError:
        return
    src = package_config_dir() / "channel_maps_user.yaml"
    if src.is_file():
        try:
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        except OSError:
            return
