#!/bin/sh
# serv00 的 cron 入口：定时跑一次「三指标极值判定 → TG 播报」（判定口径与阈值都在代码和 indicator.ini 里）
#
# 挂法（和你那条 runningOrder.py 同形状：命令写绝对路径）：
#   10,40 8 * * *   /usr/home/myaibtc/domains/myaibtc.serv00.net/alert_cron.sh
#
# 为什么要中间隔这一层，而不是把 python 直接写进 cron（三件事都得靠这层）：
#   1) 编码。cron 的环境里 LANG 常是 C/POSIX，`api/notify.py` 满屏中文 print 有当场 UnicodeEncodeError
#      把这次评估崩掉的风险——和 start_app.sh 里那两行同源，照抄。
#   2) 日志。闸门挡没挡、命中几项、发没发出去，事后只能看 `logs/notify_cron.log`；cron 不接 stdout 就等于没日志。
#   3) 不赌面板。有些 cron 实现不过 sh，`VAR=值` 前缀和 `>>` 根本不生效；包一层就不用猜它用不用 shell。
#
# 时刻**不在这个脚本里**：cron 那五个字段只管「什么时候把进程起来」，真正「不早于 ALERT_AT」和
# 「一个日历日只评一次」两道闸门都在 `api/notify.py` 里、**取数之前**判完——所以 cron 挂密一点也不会多打上游，
# 但每 tick 要起一个进程。账户内存已经 96% 就是这里刻意只写两个时刻（08:10 首发、08:40 兜底补发）的原因：
# 那一刻要正好取数全挂（退出码 1、当天不记账），08:40 那次就是当天的补发窗口。
#
# 路径全按自身位置解析：本脚本必须和 `api/`、`config.ini`、`indicator.ini` 同一层（也就是站点根）。
# 覆盖用环境变量：ALERT_PY=/绝对路径/python 换解释器，ALERT_ARGS='--html-alert' 改成预览（只看不发，
# 预览永不记账、也永不碰 TG）。

set -u

ROOT="$(cd "$(dirname "$0")" && pwd)"
PY="${ALERT_PY:-/usr/home/myaibtc/vevns/web3/bin/python}"
ARGS="${ALERT_ARGS:---html-alert --send}"
LOG="$ROOT/logs/notify_cron.log"

PYTHONIOENCODING=utf-8
PYTHONUTF8=1
export PYTHONIOENCODING PYTHONUTF8
# 站点根和 api/ 两条都给 sys.path：api/*.py 之间是平铺互相 import（api/ 那条），而 api/app.py 里
# 用的是 `from api import allocation` 这种包路径（根那条）。播报这条链今天不碰 app.py，但少给一条
# 将来就是 cron 里一句 ModuleNotFoundError: No module named 'api'，日志里还看不见是谁起的。
PYTHONPATH="$ROOT/api:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPATH

if [ ! -f "$ROOT/api/notify.py" ]; then
    echo "$0 旁边没有 api/notify.py（ROOT=$ROOT）——这个脚本要和 api/ 同一层" >&2
    exit 3
fi

mkdir -p "$ROOT/logs"
# %Z 顺带把服务器时区打进日志：第一次跑完照它和 config.ini 的时区对一眼，别猜偏移
echo "----- $(date '+%F %T %Z') $PY $ARGS -----" >> "$LOG" 2>&1
"$PY" "$ROOT/api/notify.py" $ARGS >> "$LOG" 2>&1
rc=$?
echo "----- exit=$rc（0=闸门挡/没触发/已发出；1=取数全挂或 TG 发送失败，都不记账，下次 tick 自续；2=触发但没配 [notify] tg_bot）-----" >> "$LOG" 2>&1
exit $rc
