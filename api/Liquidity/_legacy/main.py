# -*- coding: utf-8 -*-
"""RealtimeCoreMetricsBoard 入口：启动本地取数服务。

等价于双击 start_app.bat；在 PyCharm 里直接跑本文件即可。
代理、端口、日志目录与级别都在 config.ini 里改（同名环境变量优先覆盖），
由 fetch_server 导入时应用，因此这里不再设置任何默认值。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fetch_server

if __name__ == "__main__":
    fetch_server.serve()
