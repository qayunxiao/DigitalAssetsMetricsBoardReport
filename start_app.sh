#!/bin/sh
# 数字资产指标看板 — 启动器（Linux／FreeBSD 版，等价于 Windows 的 start_app.bat）
# serv00 是 FreeBSD 14.x：没有 systemd，SSH 会话结束后台进程也会被收走，所以这个脚本只在**前台**跑，
# 用来在服务器／Unix 上自测（另开一个终端 curl，或本地 SSH 端口转发 -L 8888:127.0.0.1:8888 后浏览器打开）。
# 要公网常驻请走 README 第 7.2 节的 Passenger WSGI 入口 passenger_wsgi.py，不要拿本脚本当服务管理器。
#
# 与 Windows 版的两点差异（都是有意为之）：
#   解释器：优先用 /home/myaibtc/vevns/web3/bin/python（serv00 上那个 venv，cryptoTrader 也用它），
#            它不存在才退回 PATH 里的 python3 → python；再可用 PYTHON=/path/to/python 显式指定。
#   代理：  Unix 侧**默认不走出口代理**。规则写在 api/core.py 的 apply_config()：config.ini 的 [proxy]
#            只在 Windows 生效（那是本机代理客户端的 127.0.0.1 端口，同一个文件传到服务器上就是不存在
#            的东西，照抄只会让全部上游取数失败）。这台 Unix 确实有代理时显式传环境变量，优先级更高：
#            HTTPS_PROXY=http://127.0.0.1:7890 sh start_app.sh
#
# 用法：
#   sh start_app.sh                                    # 前台运行，Ctrl+C 停止（默认 8888，见 config.ini）
#   chmod +x start_app.sh && ./start_app.sh            # 第一次可执行化
#   PYTHON=/usr/local/bin/python3.11 sh start_app.sh   # 换解释器
#   PORT=8888 sh start_app.sh                          # 临时覆盖端口（环境变量优先于 config.ini）
#   sh start_app.sh --open                             # 起来后开浏览器（只有桌面环境有意义，服务器上静默失败）
#
# 注意：本脚本起的是「本机模式」（main.py），首页的持仓报告按钮**仍然存在**，点一次就会在服务器上
# 真的执行 cryptoTrader 脚本并推送 Telegram。对外提供访问请用 passenger_wsgi.py（PUBLIC=1 会剥掉它）。

# 服务器默认 LANG 常是 C/POSIX，Python 的 stdout 编码会退化成 ASCII，启动横幅里的中文会当场抛
# UnicodeEncodeError 把进程崩掉——所以强制 UTF-8 模式（FreeBSD 与 Linux 通用，不依赖 locale 已生成）。
PYTHONIOENCODING=utf-8
PYTHONUTF8=1
export PYTHONIOENCODING PYTHONUTF8

# 等价于 bat 的 cd /d %~dp0：无论从哪个目录调用，config.ini / staic / logs 都按项目根解析。
cd "$(dirname "$0")" || exit 1

SERV00_PY=/home/myaibtc/vevns/web3/bin/python
if [ -z "$PYTHON" ]; then
    if [ -x "$SERV00_PY" ]; then
        PYTHON=$SERV00_PY
    elif command -v python3 >/dev/null 2>&1; then
        PYTHON=python3
    else
        PYTHON=python
    fi
fi

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "找不到 Python 解释器：$PYTHON（用 PYTHON=/绝对路径/python 指定，本项目需要 3.11+）" >&2
    exit 1
fi

echo "解释器=$PYTHON  环境变量代理=${HTTPS_PROXY:-${HTTP_PROXY:-（未设置）}}"
exec "$PYTHON" main.py "$@"
