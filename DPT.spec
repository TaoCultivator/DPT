# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 规格：Windows 单文件 GUI 可执行程序。"""
import re
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH)
os.environ.setdefault("NUMBA_CACHE_DIR", str(ROOT / ".numba_cache"))
VERSION_FILE = ROOT / "dpt_extractor" / "__init__.py"
VERSION_MATCH = re.search(
    r'__version__\s*=\s*["\']([^"\']+)["\']',
    VERSION_FILE.read_text(encoding="utf-8"),
)
VERSION = VERSION_MATCH.group(1) if VERSION_MATCH else "0.0.0"

datas = [
    (str(ROOT / "dpt_extractor" / "config" / "default.yaml"), "dpt_extractor/config"),
    (
        str(ROOT / "dpt_extractor" / "io" / "tek_scope_bridge.ps1"),
        "dpt_extractor/io",
    ),
    (str(ROOT / "默认报告模板.xlsx"), "dpt_extractor/templates"),
    (
        str(ROOT / "assets" / "noncommercial_authorization_poster.png"),
        "dpt_extractor/assets",
    ),
]
user_map = ROOT / "dpt_extractor" / "config" / "channel_maps_user.yaml"
if user_map.is_file():
    datas.append((str(user_map), "dpt_extractor/config"))

hiddenimports = collect_submodules("tm_data_types") + collect_submodules("PIL") + [
    "dpt_extractor",
    "dpt_extractor.gui",
    "dpt_extractor.gui.main_window",
    "dpt_extractor.gui.channel_settings_panel",
    "dpt_extractor.gui.waveform_plot",
    "dpt_extractor.pipeline.extract",
    "dpt_extractor.export.mcu2506_layout",
    "dpt_extractor.export.report_template",
    "dpt_extractor.export.short_circuit_layout",
    "scipy.ndimage",
    "scipy.ndimage._nd_image",
]

binaries = []
python_library_bin = Path(sys.base_prefix) / "Library" / "bin"
if python_library_bin.is_dir():
    os.environ["PATH"] = str(python_library_bin) + os.pathsep + os.environ.get("PATH", "")
    for dll in python_library_bin.glob("tbb*.dll"):
        binaries.append((str(dll), "."))

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pytest", "IPython"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=f"DPT_双脉冲参数提取工具_v{VERSION}",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
