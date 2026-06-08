"""应用路径：开发目录 vs PyInstaller 打包后的资源/用户配置目录。"""
from __future__ import annotations

import os
import sys
from pathlib import Path


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
        os.environ["NUMBA_CACHE_DIR"] = str(cache_dir)
        return cache_dir
    return None


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
