"""pytest 配置：把业务包与 src 加入 sys.path。

测试目录位于 ``basic-service/app/tests/``，业务包 ``jonhon_taskbook`` 与受控
``config/``、``prompts/`` 目录位于 ``basic-service/app/src/service/``。本文件
确保无论从哪个工作目录启动 pytest，``jonhon_taskbook`` 与 ``src`` 均可被导入。
"""
from __future__ import annotations

import sys
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent.parent  # basic-service/app
_SERVICE_DIR = _APP_DIR / "src" / "service"
_SRC_DIR = _APP_DIR / "src"

for _candidate in (str(_SERVICE_DIR), str(_SRC_DIR)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)
