"""代码体量统计（可复现口径）。

用途：把「产品代码多少行、GUI 多少行、测试多少行」这类数字从口头结论变成
**可复跑的脚本产出**，并允许同时统计两棵树（本分支检出 vs 主工作树当前状态），
避免把不同版本的体积混在一张表里比较。

口径：
* 只统计 ``.py``；
* ``产品代码`` = ``dpt_extractor/**`` 去掉 ``tests`` 目录；
* ``测试代码`` = 任意路径下 ``test_*.py``；
* 行数 = ``str.splitlines()`` 的长度（即最后一行没有换行符也计入）；
* 跳过任何以 ``.`` 开头的目录（``.pytest_tmp`` / ``.tmp`` / ``.venv`` 等）。

用法::

    python scripts/count_code_stats.py                       # 只统计本工作树
    python scripts/count_code_stats.py --compare E:\\Works\\DPT   # 同时统计另一棵树
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from _harness import REPO_ROOT, write_json  # noqa: E402

SKIP_DIRS = {"__pycache__"}

MODULES = ["gui", "metrics", "export", "io", "pipeline", "models", "utils", "detect", "config", "cli"]


def _py_files(root: Path, sub: str | None = None):
    base = root / "dpt_extractor" / sub if sub else root
    for path in base.rglob("*.py"):
        rel_parts = path.relative_to(root).parts
        if any(part.startswith(".") or part in SKIP_DIRS for part in rel_parts):
            continue
        yield path


def _lines(path: Path) -> tuple[int, int]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    return len(lines), sum(1 for ln in lines if ln.strip())


def collect(root: Path) -> dict:
    product_total = product_nonempty = 0
    modules: dict[str, dict] = {}
    for mod in MODULES:
        files = [p for p in _py_files(root, mod) if "tests" not in p.parts]
        total = nonempty = 0
        for f in files:
            a, b = _lines(f)
            total += a
            nonempty += b
        modules[mod] = {"files": len(files), "lines": total, "nonempty": nonempty}
        product_total += total
        product_nonempty += nonempty

    top = sorted(p for p in (root / "dpt_extractor").glob("*.py"))
    top_lines = sum(_lines(p)[0] for p in top)
    top_nonempty = sum(_lines(p)[1] for p in top)
    if top:
        modules["(dpt_extractor 顶层)"] = {
            "files": len(top),
            "lines": top_lines,
            "nonempty": top_nonempty,
        }
    main_py = root / "main.py"
    if main_py.exists():
        a, b = _lines(main_py)
        modules["main.py"] = {"files": 1, "lines": a, "nonempty": b}
        top_lines += a
        top_nonempty += b
    product_total += top_lines
    product_nonempty += top_nonempty

    tests = [p for p in _py_files(root) if p.name.startswith("test_") and p.suffix == ".py"]
    test_lines = sum(_lines(p)[0] for p in tests)

    big = []
    for p in _py_files(root):
        if "tests" in p.parts:
            continue
        n, _ = _lines(p)
        big.append({"rel": str(p.relative_to(root)), "lines": n, "kb": round(p.stat().st_size / 1024, 1)})
    big.sort(key=lambda r: r["lines"], reverse=True)

    return {
        "root": str(root),
        "product_files": sum(m["files"] for m in modules.values()),
        "product_lines": product_total,
        "product_nonempty_lines": product_nonempty,
        "test_files": len(tests),
        "test_lines": test_lines,
        "modules": modules,
        "largest_product_files": big[:10],
    }


def main() -> int:
    root = REPO_ROOT
    compare = None
    if "--compare" in sys.argv:
        compare = Path(sys.argv[sys.argv.index("--compare") + 1])

    payload = {"primary": collect(root)}
    if compare is not None:
        payload["compare"] = collect(compare)

    def show(tag: str, d: dict) -> None:
        print(f"== {tag}: {d['root']}")
        for name, m in d["modules"].items():
            print(f"   {name:22s} 文件={m['files']:3d} 行={m['lines']:7d} 非空={m['nonempty']:7d}")
        print(f"   产品代码合计: 文件={d['product_files']} 行={d['product_lines']} 非空={d['product_nonempty_lines']}")
        print(f"   测试代码合计: 文件={d['test_files']} 行={d['test_lines']}")
        print("   最大产品文件:")
        for r in d["largest_product_files"][:5]:
            print(f"     {r['rel']:48s} {r['lines']:6d} 行  {r['kb']:8.1f} KB")

    show("本工作树", payload["primary"])
    if compare is not None:
        print()
        show("对照工作树", payload["compare"])

    out = write_json("code_stats.json", payload)
    print("\nraw ->", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
