"""BOSS Job Assistant 的安全启动入口。

不包含业务逻辑，仅把命令转交给 main.py。无参数启动时打开本地控制台，
控制台不会在未经点击确认时执行真实沟通。
"""
from __future__ import annotations

import sys

from main import main


if __name__ == "__main__":
    if len(sys.argv) == 1:
        sys.argv.append("ui")
    raise SystemExit(main())
