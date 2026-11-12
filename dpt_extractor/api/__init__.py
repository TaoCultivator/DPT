"""DPT local API protocol package.

设计原则：
- 只依赖标准库 + 项目已有依赖（numpy/scipy/openpyxl/yaml），不引入 http 框架。
- 核心 :class:`ApiService` 不 import 任何 Qt 符号，因此既能挂在 GUI 主进程的
  后台线程里，也能通过 ``python -m dpt_extractor.api.server`` 独立运行。
- 协议只消费 GUI 同一条权威计算路径（``run_extraction`` / ``*_measurement_context``
  / ``export_to_excel``），避免出现第二套数值口径。
"""

from __future__ import annotations

from dpt_extractor.api.service import ApiError, ApiService
from dpt_extractor.api.server import (
    ApiServerHandle,
    create_server,
    serve_forever,
    start_in_thread,
)

__all__ = [
    "ApiError",
    "ApiService",
    "ApiServerHandle",
    "create_server",
    "serve_forever",
    "start_in_thread",
]