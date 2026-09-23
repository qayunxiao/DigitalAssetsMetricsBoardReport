# -*- coding: utf-8 -*-
"""DigitalAssetsMetricsBoard 本地入口：启动合并后的单一本机服务（仅 127.0.0.1）。

等价于双击 api/start_app.bat；在 PyCharm 里直接跑本文件即可。
代理、端口、日志目录与级别、页面开关都在根目录 config.ini 里改
（同名环境变量优先覆盖），由 api/core.py 导入时应用，这里不设任何默认值。
路由注册表在 api/app.py，与公网版 passenger_wsgi.py 共用同一份。
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "api"))

import app                     # noqa: E402  装配：注册 liquidity/crash/allocation
import core                    # noqa: E402  公共层：config/缓存/队列/日志/路由框架

app.build()

if __name__ == "__main__":
    core.serve()
