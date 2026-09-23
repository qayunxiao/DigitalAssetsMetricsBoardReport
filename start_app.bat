@echo off
chcp 65001 >nul
rem 数字资产指标看板 — 本地取数服务启动器（合并版，单服务托管 Index + 3 个子页面）
rem 页面自身无法直取 FRED/财政部（无 CORS），必须由本脚本启动的 main.py 经代理中转。
rem 代理地址、端口、日志目录与级别都在根目录 config.ini 里改；临时覆盖用 set HTTPS_PROXY=... 即可。
rem --open：服务起来后自行打开主页（端口取自 config.ini，不在这里写死）。
cd /d %~dp0

python main.py --open
