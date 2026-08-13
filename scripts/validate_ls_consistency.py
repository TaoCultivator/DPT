"""Validate commutation-loop stray-inductance consistency across current points."""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dpt_extractor.config.loader import load_config  # noqa: E402
from dpt_extractor.io.waveform_loader import load_waveform  # noqa: E402
from dpt_extractor.models.bridge_profile import guess_profile_from_path  # noqa: E402
from dpt_extractor.pipeline.extract import extract_all  # noqa: E402


_CURRENT_RE = re.compile(r"(?:_|-)(\d+(?:\.\d+)?)A_000\.tss$", re.IGNORECASE)
_TEMPERATURES = {"LT", "RT", "HT"}


def _relative_spread_percent(values: list[float]) -> float:
    mean = float(np.mean(values))
    if not np.isfinite(mean) or abs(mean) <= 1e-12:
        return float("inf")
    return float((max(values) - min(values)) / abs(mean) * 100.0)


def _temperature(path: Path) -> str:
    for part in path.parts:
        upper = part.upper()
        if upper in _TEMPERATURES:
            return upper
    return "UNKNOWN"


def _stats(values: list[float]) -> tuple[float, float, float]:
    arr = np.asarray(values, dtype=np.float64)
    return (
        float(np.median(arr)),
        float(np.percentile(arr, 90)),
        float(np.max(arr)),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--currents", nargs=3, type=float, required=True)
    parser.add_argument("--expected-groups", type=int)
    parser.add_argument("--max-on-close", type=float)
    parser.add_argument("--max-off-close", type=float)
    parser.add_argument("--max-on-span", type=float)
    parser.add_argument("--max-off-span", type=float)
    args = parser.parse_args()

    root = args.root.resolve()
    targets = tuple(float(value) for value in args.currents)
    target_set = set(targets)
    cfg = load_config()
    groups: dict[tuple[str, str], dict[float, tuple[float, float, Path]]] = (
        defaultdict(dict)
    )
    errors: list[str] = []

    for path in sorted(root.rglob("*.tss")):
        match = _CURRENT_RE.search(path.name)
        if match is None:
            continue
        current = float(match.group(1))
        if current not in target_set:
            continue
        try:
            bundle = load_waveform(path)
            profile = guess_profile_from_path(str(path))
            result = extract_all(bundle, profile, cfg)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{path}: {exc!r}")
            continue
        if result.single_pulse_mode or result.short_circuit_mode:
            errors.append(f"{path}: expected double-pulse result")
            continue
        groups[(_temperature(path.relative_to(root)), profile.code)][current] = (
            float(result.turn_on.ls_on),
            float(result.turn_off.ls_off),
            path,
        )

    complete: list[tuple[tuple[str, str], dict[float, tuple[float, float, Path]]]] = []
    for key, values in sorted(groups.items()):
        missing = [current for current in targets if current not in values]
        if missing:
            errors.append(f"{key[0]}/{key[1]}: missing currents {missing}")
            continue
        complete.append((key, values))

    if args.expected_groups is not None and len(complete) != args.expected_groups:
        errors.append(
            f"complete groups {len(complete)} != expected {args.expected_groups}"
        )

    on_close: list[float] = []
    off_close: list[float] = []
    on_span: list[float] = []
    off_span: list[float] = []
    current_labels = "/".join(f"{value:g}A" for value in targets)
    print(f"root={root}")
    print(f"currents={current_labels}")
    print("temp\tprofile\tLs_on[nH]\tLs_off[nH]\ton_close[%]\toff_close[%]\ton_span[%]\toff_span[%]")
    for (temperature, profile_code), values in complete:
        on_values = [values[current][0] for current in targets]
        off_values = [values[current][1] for current in targets]
        group_on_close = _relative_spread_percent(on_values[1:])
        group_off_close = _relative_spread_percent(off_values[1:])
        group_on_span = _relative_spread_percent(on_values)
        group_off_span = _relative_spread_percent(off_values)
        on_close.append(group_on_close)
        off_close.append(group_off_close)
        on_span.append(group_on_span)
        off_span.append(group_off_span)
        print(
            f"{temperature}\t{profile_code}\t"
            f"{'/'.join(f'{value:.3f}' for value in on_values)}\t"
            f"{'/'.join(f'{value:.3f}' for value in off_values)}\t"
            f"{group_on_close:.2f}\t{group_off_close:.2f}\t"
            f"{group_on_span:.2f}\t{group_off_span:.2f}"
        )

    summaries = {
        "on_close": _stats(on_close) if on_close else (float("inf"),) * 3,
        "off_close": _stats(off_close) if off_close else (float("inf"),) * 3,
        "on_span": _stats(on_span) if on_span else (float("inf"),) * 3,
        "off_span": _stats(off_span) if off_span else (float("inf"),) * 3,
    }
    for label, (median, p90, maximum) in summaries.items():
        print(f"summary\t{label}\tmedian={median:.2f}%\tp90={p90:.2f}%\tmax={maximum:.2f}%")

    limits = {
        "on_close": args.max_on_close,
        "off_close": args.max_off_close,
        "on_span": args.max_on_span,
        "off_span": args.max_off_span,
    }
    for label, limit in limits.items():
        if limit is not None and summaries[label][2] > float(limit):
            errors.append(
                f"{label} max {summaries[label][2]:.2f}% > {float(limit):.2f}%"
            )

    if errors:
        for error in errors:
            print(f"FAIL\t{error}")
        return 1
    print(f"PASS\tgroups={len(complete)} files={len(complete) * len(targets)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
