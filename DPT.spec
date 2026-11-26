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
    (
        str(ROOT / "dpt_extractor" / "io" / "tekvisa_native.cs"),
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
    "dpt_extractor.utils.qt_bootstrap",
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

# MSVC 运行库必须补一份到 _MEIPASS 根目录。
# PyQt6 wheel 把 MSVCP140.dll / MSVCP140_1.dll / MSVCP140_2.dll 放在
# PyQt6\Qt6\bin 子目录里，PyInstaller 只会把 python 自己依赖的 VCRUNTIME140*.dll
# 收进根目录。目标机若没装 VC++ 2015-2022 运行库、又搜不到那个子目录，导入
# QtWidgets 就会报 "DLL load failed while importing QtWidgets: 找不到指定的模块"。
# 根目录是打包器唯一保证会被搜索的位置，因此这里显式再放一份（同名 DLL 放在
# 子目录里的那份保持不变）。优先取 PyQt6 自带副本，保证与 Qt 的编译版本一致。
_MSVC_RUNTIME_DLLS = (
    "MSVCP140.dll",
    "MSVCP140_1.dll",
    "MSVCP140_2.dll",
    "VCRUNTIME140.dll",
    "VCRUNTIME140_1.dll",
)
_MSVC_RUNTIME_SOURCES = (
    Path(sys.prefix) / "Lib" / "site-packages" / "PyQt6" / "Qt6" / "bin",
    Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32",
)
# 注：PyInstaller 6 的 Qt hook 按"文件名"去重，同一个 DLL 名只会留一份，因此
# 根目录这份会取代 PyQt6\Qt6\bin 子目录那份，而不是两处共存。根目录是打包器
# 保证会被搜索的位置（bootloader 登记 _MEIPASS + PyQt6 把 _MEIPASS 前置到
# PATH），所以这是更稳的那一处。
for _dll_name in _MSVC_RUNTIME_DLLS:
    for _dll_dir in _MSVC_RUNTIME_SOURCES:
        _dll_path = _dll_dir / _dll_name
        if _dll_path.is_file():
            binaries.append((str(_dll_path), "."))
            break

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
