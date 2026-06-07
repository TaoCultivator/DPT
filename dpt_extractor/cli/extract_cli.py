"""Headless extraction: python -m dpt_extractor.cli.extract_cli file.csv [--bridge upper|lower]"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dpt_extractor.config.loader import load_config
from dpt_extractor.io.waveform_loader import load_waveform
from dpt_extractor.models.bridge_profile import PROFILES, guess_profile_from_path, make_profile
from dpt_extractor.pipeline.extract import extract_all


def main() -> int:
    parser = argparse.ArgumentParser(description="DPT parameter extraction (CLI)")
    parser.add_argument("csv", type=Path, help="Tekscope CSV or TSS session path")
    parser.add_argument(
        "--bridge",
        choices=[
            "upper", "lower",
            "UH", "UL", "VH", "VL", "WH", "WL",
            "u_upper", "u_lower", "v_upper", "v_lower", "w_upper", "w_lower",
        ],
        default=None,
        help="Bridge: upper/lower or phase code UH/UL/VH/VL/WH/WL",
    )
    parser.add_argument("--phase", choices=["U", "V", "W"], default=None, help="Phase with --bridge upper/lower")
    parser.add_argument("--vdc", type=float, default=None, help="Override Vdc (V)")
    args = parser.parse_args()

    cfg = load_config()
    if args.vdc is not None:
        cfg.vdc_override = args.vdc

    profile = guess_profile_from_path(args.csv)
    if args.bridge:
        key = args.bridge
        if key in ("upper", "lower") and args.phase:
            profile = make_profile(args.phase, key)
        elif key in PROFILES:
            profile = PROFILES[key]
        elif "_" in key:
            phase, br = key.split("_", 1)
            profile = make_profile(phase, br)
        else:
            profile = PROFILES[key.upper()]

    bundle = load_waveform(args.csv)
    result = extract_all(bundle, profile, cfg)

    out = {
        "vdc": result.vdc,
        "idc": result.idc,
        "turn_off": asdict(result.turn_off),
        "turn_on": asdict(result.turn_on),
        "reverse_recovery": asdict(result.reverse_recovery),
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
