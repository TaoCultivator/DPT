from __future__ import annotations

from enum import Enum


class TestMode(str, Enum):
    """测试类型：双脉冲、短路与偏移测量相互隔离。"""

    DPT = "dpt"
    SHORT_CIRCUIT = "short_circuit"
    OFFSET_MEASUREMENT = "offset_measurement"


MODE_UI_LABELS: dict[TestMode, str] = {
    TestMode.DPT: "双脉冲计算",
    TestMode.SHORT_CIRCUIT: "短路计算",
    TestMode.OFFSET_MEASUREMENT: "偏移测量",
}


def parse_test_mode(value: str | TestMode | None) -> TestMode:
    if isinstance(value, TestMode):
        return value
    if value is None:
        return TestMode.DPT
    key = str(value).strip().lower()
    for mode in TestMode:
        if mode.value == key:
            return mode
    return TestMode.DPT
