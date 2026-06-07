# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 规格：Windows 单文件 GUI 可执行程序。"""
import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH)
VERSION_FILE = ROOT / "dpt_extractor" / "__init__.py"
VERSION_MATCH = re.search(
    r'__version__\s*=\s*["\']([^"\']+)["\']',
    VERSION_FILE.read_text(encoding="utf-8"),
)
VERSION = VERSION_MATCH.group(1) if VERSION_MATCH else "0.0.0"

datas = [
    (str(ROOT / "dpt_extractor" / "config" / "default.yaml"), "dpt_extractor/config"),
]
user_map = ROOT / "dpt_extractor" / "config" / "channel_maps_user.yaml"
if user_map.is_file():
    datas.append((str(user_map), "dpt_extractor/config"))

hiddenimports = collect_submodules("scipy") + collect_submodules("tm_data_types") + [
    "dpt_extractor",
    "dpt_extractor.gui",
    "dpt_extractor.gui.main_window",
    "dpt_extractor.gui.channel_settings_panel",
    "dpt_extractor.gui.waveform_plot",
    "dpt_extractor.pipeline.extract",
    "dpt_extractor.export.mcu2506_layout",
]

binaries = []
for pkg in ("PyQt6", "pyqtgraph"):
    tmp = collect_all(pkg)
    datas += tmp[0]
    binaries += tmp[1]
    hiddenimports += tmp[2]

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
