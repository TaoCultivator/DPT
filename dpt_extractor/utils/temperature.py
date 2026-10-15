"""Temperature-condition token parsing shared by the GUI and report writer."""

from __future__ import annotations

import re


_TEMPERATURE_TOKEN_RE = re.compile(
    r"(?<![A-Z0-9])(?P<value>-?40|25|150|175)"
    r"(?:(?:℃|°C|C|DEG)(?![A-Z0-9])|(?![A-Z0-9]))",
    re.IGNORECASE,
)


def infer_temperature_token_code(stem: str) -> str | None:
    """Return a temperature code from an isolated filename temperature token.

    The unit suffix is optional for compatibility with existing filenames, but
    a following alphanumeric character is never accepted.  Thus ``150V`` and
    ``40A`` remain voltage/current tokens instead of becoming temperatures.
    ``175`` (with or without a temperature unit) is treated as the HT
    condition used by the current test report.
    """

    for match in _TEMPERATURE_TOKEN_RE.finditer(str(stem or "").upper()):
        value = match.group("value")
        if value == "25":
            return "RT"
        if value in {"150", "175"}:
            return "HT"
        if value in {"40", "-40"}:
            return "LT"
    return None
