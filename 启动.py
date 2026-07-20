"""BOSS Job Assistant 的安全启动入口。

不包含业务逻辑，仅把命令转交给 main.py。无参数启动时默认显示状态，
避免双击文件后直接执行真实沟通。
"""
from __future__ import annotations

import sys

from main import main


if __name__ == "__main__":
    if len(sys.argv) == 1:
        sys.argv.append("status")
        print("未指定命令，安全默认执行 status；真实运行请使用：启动.py run")
    raise SystemExit(main())
