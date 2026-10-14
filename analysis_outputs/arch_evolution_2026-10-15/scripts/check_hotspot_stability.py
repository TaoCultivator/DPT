"""核查「热点函数名单是否仍然指向现行代码」。

动机：本议题的所有测量都在**分支检出的 `937dc8ad`** 上完成，而主工作树
`E:\\Works\\DPT` 当时带着未提交改动（产品代码比 HEAD 多约 5 000 行）。
若主工作树已经把这些热点函数改掉，热点名单就过期了。

做法（只读、不做数值，不需要重跑剖析）：
1. 读 `raw/hotspots.json` 的 Top-N 项目内热点（文件 + 行号 + 函数名）；
2. 在本工作树与另一棵树里各按**缩进**切出该函数体；
3. 逐字符比对（忽略行尾空白），给出：一致 / 有差异 / 缺失。

用法::

    python scripts/check_hotspot_stability.py --other-root E:\\Works\\DPT --top 20
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from _harness import RAW_DIR, REPO_ROOT, write_json  # noqa: E402


def _extract_block(path: Path, func: str, start_line: int | None = None) -> str | None:
    """按缩进切出 ``def func(...)`` 的函数体（含嵌套）。"""
    if not path.exists():
        return None
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    candidates: list[int] = []
    for i, line in enumerate(lines):
        if line.lstrip().startswith(f"def {func}(") or line.lstrip().startswith(f"async def {func}("):
            candidates.append(i)
    if not candidates:
        return None
    if start_line is not None:
        near = [i for i in candidates if abs(i + 1 - start_line) <= 2]
        chosen = near[0] if near else candidates[0]
    else:
        chosen = candidates[0]
    indent = len(lines[chosen]) - len(lines[chosen].lstrip())
    out = [lines[chosen]]
    for line in lines[chosen + 1 :]:
        if line.strip() and (len(line) - len(line.lstrip())) <= indent:
            break
        out.append(line)
    return "\n".join(s.rstrip() for s in out).strip()


def main() -> int:
    top = 20
    other = None
    if "--top" in sys.argv:
        top = int(sys.argv[sys.argv.index("--top") + 1])
    if "--other-root" in sys.argv:
        other = Path(sys.argv[sys.argv.index("--other-root") + 1])

    hotspots = json.loads((RAW_DIR / "hotspots.json").read_text(encoding="utf-8"))
    entries = hotspots["top_project_by_tottime"][:top]

    rows = []
    for e in entries:
        rel = e["file"]
        func = e["func"]
        primary = _extract_block(REPO_ROOT / rel, func, e["line"])
        row = {
            "file": rel,
            "line": e["line"],
            "func": func,
            "share_of_project_tt": e["share_of_project_tt"],
            "primary_present": primary is not None,
        }
        if other is not None:
            peer = _extract_block(other / rel, func, None)
            row["other_present"] = peer is not None
            if primary is None or peer is None:
                row["status"] = "缺失"
            elif primary == peer:
                row["status"] = "一致"
            else:
                row["status"] = "有差异"
                row["primary_lines"] = primary.count("\n") + 1
                row["other_lines"] = peer.count("\n") + 1
        rows.append(row)

    payload = {
        "purpose": "核查热点函数是否与现行（主工作树）代码保持一致",
        "primary_root": str(REPO_ROOT),
        "other_root": str(other) if other else None,
        "source": "raw/hotspots.json top_project_by_tottime",
        "top": top,
        "rows": rows,
        "summary": {
            "identical": sum(1 for r in rows if r.get("status") == "一致"),
            "different": sum(1 for r in rows if r.get("status") == "有差异"),
            "missing": sum(1 for r in rows if r.get("status") == "缺失"),
            "compared": sum(1 for r in rows if "status" in r),
        },
    }
    out = write_json("verify_hotspot_stability.json", payload)
    for r in rows:
        print(
            f"  {r.get('status', 'N/A'):4s} {r['file'].split('dpt_extractor/')[-1]}:{r['line']:<5} {r['func']}"
            f"  ({r['share_of_project_tt'] * 100:.2f}%)"
        )
    print("summary:", json.dumps(payload["summary"], ensure_ascii=False))
    print("raw ->", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
