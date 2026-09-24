#!/bin/sh
# serv00 的 cron 入口：定时跑一次「页面那三张卡 → 顶部/底部两段各自判定 → TG 播报」（阈值在 indicator.ini 里）
#
# 挂法（和你那条 runningOrder.py 同形状：命令写绝对路径）：
#   10,40 8 * * *   /usr/home/myaibtc/domains/myaibtc.serv00.net/alert_cron.sh
#
# 2026-09-24 按你的要求改了口径：**这个脚本不再判「几点」**（它把**两段**的时刻 HTML_ALERT_TOP_AT /
# HTML_ALERT_BOTTOM_AT 显式设空，绕开 indicator.ini 里那两个 ALERT_AT），执行时机完全由 crontab 那五个字段
# 决定——你什么时候跑它，它就什么时候真去取数、真去比阈值。只保留「一个日历日只评一次」那一道（各段各记一笔），
# 因为它是**防重复推送**的（08:10 发成功后 08:40 那次兜底不能再发一条），不是防早跑的。
# 当天想再评一次（比如刚改完阈值想立刻看结果）：ALERT_ARGS='--html-alert --send --force' ./alert_cron.sh
# 注意手工 --force 评过之后，当天那个正常 tick 会被「已评估过一次」挡掉，这是同一道闸门的两面。
# 只想跑一段：ALERT_ARGS='--html-alert-bottom --send' ./alert_cron.sh（另一段那条链不受影响）。
#
# 为什么要中间隔这一层，而不是把 python 直接写进 cron（三件事都得靠这层）：
#   1) 编码。cron 的环境里 LANG 常是 C/POSIX，`api/notify.py` 满屏中文 print 有当场 UnicodeEncodeError
#      把这次评估崩掉的风险——和 start_app.sh 里那两行同源，照抄。
#   2) 日志。闸门挡没挡、命中几项、发没发出去，事后只能看 `logs/notify_cron.log`；cron 不接 stdout 就等于没日志。
#   3) 不赌面板。有些 cron 实现不过 sh，`VAR=值` 前缀和 `>>` 根本不生效；包一层就不用猜它用不用 shell。
#
# 时刻既然不在这判了，cron 的**密度**就成了唯一的成本项：每个 tick 都会起一个 python 进程、
# 真打一轮上游（闸门②在取数之前，两段当天都评过的那些 tick 会立刻退出、不打上游）。账户内存已经 96%
# 就是建议只挂两个时刻（08:10 首发、08:40 兜底补发）而不是每分钟一条的原因：
# 那一刻要正好取数全挂（退出码 1、当天不记账），08:40 那次就是当天的补发窗口。
#
# 路径全按自身位置解析：本脚本必须和 `api/`、`config.ini`、`indicator.ini` 同一层（也就是站点根）。
# 覆盖用环境变量：ALERT_PY=/绝对路径/python 换解释器，ALERT_ARGS='--html-alert' 改成预览（只看不发，
# 预览永不记账、也永不碰 TG），ALERT_TIME=1 把「不早于 ALERT_AT」那道时刻闸门加回来（两段都加）。

set -u

ROOT="$(cd "$(dirname "$0")" && pwd)"
PY="${ALERT_PY:-/usr/home/myaibtc/vevns/web3/bin/python}"
ARGS="${ALERT_ARGS:---html-alert --send}"
LOG="$ROOT/logs/notify_cron.log"

# 「几点跑」整个交给 crontab 那五个字段，脚本里不再判时刻：把**两段**的时刻各显式设空，
# notify.py 的 alert_cfg() 认这个空 = 不设时刻（indicator.ini 里那两个 ALERT_AT 就此被绕过）。
# 段名前缀是 HTML_ALERT_TOP_ / HTML_ALERT_BOTTOM_（2026-09-24 拆两段之后 env 名跟着换了，别只清一个）。
# 时刻闸门拿掉之后**只留「一个日历日只评一次」这一道**（每段各一本账）——它是防重复推送的，不是防早跑的：
# 同一分钟里 cron 打两次、或者 08:10 发成功后 08:40 那次兜底，都靠它挡成一条。
# 要退回「脚本也判一次 ALERT_AT」（比如 indicator.ini 里那两行你打算认真用）：ALERT_TIME=1 ./alert_cron.sh
if [ "${ALERT_TIME:-0}" != 1 ]; then
    HTML_ALERT_TOP_AT=""
    HTML_ALERT_BOTTOM_AT=""
    export HTML_ALERT_TOP_AT HTML_ALERT_BOTTOM_AT
    GATE="时刻闸门=关（两段都不判几点，跑不跑由 crontab 决定）"
else
    GATE="时刻闸门=开（各自用 indicator.ini 里那段的 ALERT_AT）"
fi

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
echo "----- $(date '+%F %T %Z') $GATE  $PY $ARGS -----" >> "$LOG" 2>&1
"$PY" "$ROOT/api/notify.py" $ARGS >> "$LOG" 2>&1
rc=$?
echo "----- exit=$rc（0=闸门挡/没触发/已发出；1=取数全挂或 TG 发送失败，都不记账，下次 tick 自续；2=触发但没配 [notify] tg_bot）-----" >> "$LOG" 2>&1
# stdout 只留这一行指路：判定明细全在日志里，cron 的邮件也就能看清「跑过了、去哪看」。
echo "跑完了：exit=$rc（0=闸门挡/没触发/已发出，1=取数全挂或发送失败，2=触发但没配 tg_bot）  明细看 $LOG"
echo "  $GATE ；当天要再评一次：ALERT_ARGS='--html-alert --send --force' $0"
exit $rc
