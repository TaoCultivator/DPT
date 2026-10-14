"""PoC-0：Rust 工具链环境核查（如实记录，不编造）。

在给出任何「用 Rust 重写会更快」的结论之前，先确认本机是否具备 Rust 工具链。
本脚本 **只读探测**：不安装任何东西、不修改任何文件。

用法::

    python analysis_outputs/arch_evolution_2026-10-15/scripts/check_rust_toolchain.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from _harness import write_json  # noqa: E402

PROBES = [
    ("rustc", ["rustc", "--version"]),
    ("cargo", ["cargo", "--version"]),
    ("rustup", ["rustup", "--version"]),
    ("matu", ["maturin", "--version"]),
    ("cl", ["cl"]),  # MSVC 链接器（Rust Windows 默认工具链需要）
    ("link", ["link"]),
    ("gcc", ["gcc", "--version"]),
]

CARGO_HOME = Path(os.environ.get("CARGO_HOME", Path.home() / ".cargo"))
RUSTUP_HOME = Path(os.environ.get("RUSTUP_HOME", Path.home() / ".rustup"))


def _probe(name: str, cmd: list[str]) -> dict:
    exe = shutil.which(cmd[0])
    if exe is None:
        return {"name": name, "found": False, "path": None, "output": None}
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        out = (proc.stdout or proc.stderr or "").strip().splitlines()
        return {
            "name": name,
            "found": True,
            "path": exe,
            "output": out[0] if out else "",
            "returncode": proc.returncode,
        }
    except Exception as exc:  # noqa: BLE001
        return {"name": name, "found": True, "path": exe, "output": f"error: {exc}"}


def main() -> int:
    print("== Rust 工具链环境核查（本机实测）==\n")
    results = [_probe(name, cmd) for name, cmd in PROBES]

    for r in results:
        if r["found"]:
            print(f"  [有] {r['name']:8s} {r.get('path','')}")
            if r.get("output"):
                print(f"           -> {r['output']}")
        else:
            print(f"  [无] {r['name']:8s} 未在 PATH 中找到")

    print("\n== 目录痕迹 ==")
    dirs = {}
    for label, path in (("CARGO_HOME", CARGO_HOME), ("RUSTUP_HOME", RUSTUP_HOME)):
        exists = path.is_dir()
        dirs[label] = {"path": str(path), "exists": exists}
        print(f"  {label:12s} {path}  存在={exists}")

    rustc_found = next(r["found"] for r in results if r["name"] == "rustc")
    cargo_found = next(r["found"] for r in results if r["name"] == "cargo")
    msvc_found = any(r["found"] for r in results if r["name"] in ("cl", "link"))
    gcc_found = next(r["found"] for r in results if r["name"] == "gcc")

    verdict = {
        "rust_toolchain_available": bool(rustc_found and cargo_found),
        "msvc_linker_available": bool(msvc_found),
        "gnu_linker_available": bool(gcc_found),
        "blocker": None,
    }
    if not verdict["rust_toolchain_available"]:
        verdict["blocker"] = "未安装 rustc/cargo，无法在本机编译任何 Rust 代码"
    elif not (msvc_found or gcc_found):
        verdict["blocker"] = "有 rustc 但无可用链接器，无法产出可执行/扩展模块"

    print("\n== 结论 ==")
    print(f"  Rust 工具链可用 : {verdict['rust_toolchain_available']}")
    print(f"  MSVC 链接器可用 : {verdict['msvc_linker_available']}")
    print(f"  GNU 链接器可用  : {verdict['gnu_linker_available']}")
    print(f"  阻塞项          : {verdict['blocker'] or '无'}")

    print("\n== 若需补齐工具链（供决策，本脚本不执行）==")
    print("  1) 安装 rustup（Windows x86_64）:")
    print("     https://win.rustup.rs/x86_64  ->  rustup-init.exe")
    print("     或 winget: winget install --id Rustlang.Rustup")
    print("  2) 默认工具链（MSVC ABI，需 VS Build Tools 的 C++ 工作负载）:")
    print("     rustup default stable-msvc")
    print("     若不便装 MSVC，可改用 GNU ABI: rustup default stable-gnu")
    print("  3) PyO3 扩展打包（方案 A 需要）:")
    print("     python -m pip install maturin")
    print("     maturin new --bindings pyo3 dpt_kernel   # 骨架")
    print("  4) 纯 crate 验证（不涉及 Python）:")
    print("     cargo new --lib dpt_kernel && cargo bench")

    payload = {
        "probes": results,
        "dirs": dirs,
        "verdict": verdict,
        "install_plan": [
            "https://win.rustup.rs/x86_64 (rustup-init.exe) 或 winget install Rustlang.Rustup",
            "rustup default stable-msvc（或 stable-gnu）",
            "python -m pip install maturin（方案 A 需要）",
        ],
        "note": "本脚本只做只读探测；未安装任何组件。",
    }
    out = write_json("rust_toolchain.json", payload)
    print(f"\nraw -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
