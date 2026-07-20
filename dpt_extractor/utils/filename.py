from __future__ import annotations

import re
from pathlib import Path


_NUMBER_RE = r"\d+(?:\.\d+)?"
_PAIR_RE = re.compile(
    rf"({_NUMBER_RE})\s*(?:VDC|V)[_\-\s]*({_NUMBER_RE})\s*(?:ADC|A)(?![A-Z])",
    re.IGNORECASE,
)
_VOLTAGE_RE = re.compile(rf"(?<!\d)({_NUMBER_RE})\s*(?:VDC|V)(?![A-Z])", re.IGNORECASE)
_CURRENT_RE = re.compile(rf"(?<!\d)({_NUMBER_RE})\s*(?:ADC|A)(?![A-Z])", re.IGNORECASE)
_MIN_BUS_VOLTAGE = 50.0


def _float_group(match: re.Match[str], group: int = 1) -> float:
    return float(match.group(group))


def parse_setpoints_from_filename(path: str) -> tuple[float | None, float | None]:
    """
    Parse setpoints from filenames such as:
    WH_480V_800A_000.tss -> (480.0, 800.0)
    WH_480V_Rg_on3.3ohm_Rg_off3.6ohm_800A_000.tss -> (480.0, 800.0)
    """
    # Parse the complete basename instead of Path.stem. Report waveform labels
    # such as ``900V_494.9A`` have no file extension; Path.stem mistakes the
    # trailing ``.9A`` for a suffix and silently drops the current unit/value.
    # The setpoint regexes already stop at V/A units, so a real suffix such as
    # ``.tss`` does not need to be removed first.
    name = Path(path).name.upper()
    m = _PAIR_RE.search(name)
    if m:
        return float(m.group(1)), float(m.group(2))

    voltage_matches = list(_VOLTAGE_RE.finditer(name))
    current_matches = list(_CURRENT_RE.finditer(name))
    voltage_candidates = [
        match for match in voltage_matches if _float_group(match) >= _MIN_BUS_VOLTAGE
    ]
    if not voltage_candidates:
        voltage_candidates = voltage_matches

    if voltage_candidates and current_matches:
        pairs: list[tuple[int, re.Match[str], re.Match[str]]] = []
        for voltage in voltage_candidates:
            for current in current_matches:
                if current.start() >= voltage.end():
                    pairs.append((current.start() - voltage.end(), voltage, current))
        if pairs:
            _distance, voltage, current = min(pairs, key=lambda item: item[0])
            return _float_group(voltage), _float_group(current)

        def distance(item: tuple[re.Match[str], re.Match[str]]) -> int:
            voltage, current = item
            voltage_mid = (voltage.start() + voltage.end()) // 2
            current_mid = (current.start() + current.end()) // 2
            return abs(voltage_mid - current_mid)

        voltage, current = min(
            (
                (voltage, current)
                for voltage in voltage_candidates
                for current in current_matches
            ),
            key=distance,
        )
        return _float_group(voltage), _float_group(current)

    vdc = _float_group(voltage_candidates[0]) if voltage_candidates else None
    idc = _float_group(current_matches[0]) if current_matches else None
    return vdc, idc

