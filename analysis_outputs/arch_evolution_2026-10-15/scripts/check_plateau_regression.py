"""回归检查：PoC-2 曾经失败的退化用例现在必须按位一致。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from _harness import ensure_repo_on_path  # noqa: E402

ensure_repo_on_path()

from dpt_extractor.metrics import plateau_level as pl  # noqa: E402
import poc_plateau_vectorize as poc  # noqa: E402


def main() -> int:
    cases = [
        ("linspace(0,5,26) low", np.linspace(0, 5, 26), "low"),
        ("linspace(0,5,26) high", np.linspace(0, 5, 26), "high"),
        ("linspace(0,5,26) none", np.linspace(0, 5, 26), "none"),
        ("linspace(0,5,27) low", np.linspace(0, 5, 27), "low"),
        ("linspace(0,5,25) low", np.linspace(0, 5, 25), "low"),
        ("linspace(0,5,40) low", np.linspace(0, 5, 40), "low"),
        ("zeros(26) low", np.zeros(26), "low"),
        ("const 7 low", np.full(26, 7.0), "low"),
    ]
    all_ok = True
    for name, band, prefer in cases:
        a = pl._quiet_plateau_mid(band, prefer=prefer)
        b = poc._quiet_plateau_mid_vectorized(band, prefer=prefer)
        same = float(a) == float(b)
        all_ok = all_ok and same
        flag = "OK  " if same else "FAIL"
        print(f"[{flag}] {name:24s} original={a!r}  vectorized={b!r}")
    print(f"\n全部按位一致: {all_ok}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
