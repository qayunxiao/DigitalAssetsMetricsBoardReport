#!/bin/sh
# serv00 的 cron 入口：定时跑一次「页面那三张卡 → 顶部/底部两段各自判定 → 并成一条 TG 指标日报」（阈值在 indicator.ini 里）
#
# 挂法（和你那条 runningOrder.py 同形状：命令写绝对路径）：
#   10,40 8 * * *   /usr/home/myaibtc/domains/myaibtc.serv00.net/alert_cron.sh
#
# 2026-09-24 按你的要求改了口径：**这个脚本不判「几点」**，执行时机完全由 crontab 那五个字段决定——
# 你什么时候跑它，它就什么时候真去取数、真去比阈值（怎么做到不判时刻的，见下面那两条 export）。
# 只保留「一个日历日只发一条」那一道（并成日报之后**只有一本账**），因为它是**防重复推送**的
# （08:10 发成功后 08:40 那次兜底不能再发一条），不是防早跑的。
# 当天想再发一次（比如刚改完阈值想立刻看结果）：ALERT_ARGS='--html-alert --send --force' ./alert_cron.sh
# 注意手工 --force 发过之后，当天那个正常 tick 会被「今天已经发过」挡掉，这是同一道闸门的两面。
# 只想出一段的条件列：ALERT_ARGS='--html-alert-bottom --send' ./alert_cron.sh（账本共用，发过就当今天这条日报发过了）。
#
# ⚠ 2026-09-24 第三次改口径（这条链现在叫**指标日报**）：**不论有没有触发阈值，每天固定发一条**，
# 正文一行一张卡、两段的「条件 + ✓/✗」并排两列。但**cron 密度不等于每天收到几条**：闸门②仍然保证一天一条，
# 改 crontab 那五个字段只是改「几点发」，不会改成「发几条」。
#
# 为什么要中间隔这一层，而不是把 python 直接写进 cron（三件事都得靠这层）：
#   1) 编码。cron 的环境里 LANG 常是 C/POSIX，`api/notify.py` 满屏中文 print 有当场 UnicodeEncodeError
#      把这次评估崩掉的风险——和 start_app.sh 里那两行同源，照抄。
#   2) 日志。闸门挡没挡、命中几项、发没发出去，事后只能看 `logs/notify_cron.log`；cron 不接 stdout 就等于没日志。
#   3) 不赌面板。有些 cron 实现不过 sh，`VAR=值` 前缀和 `>>` 根本不生效；包一层就不用猜它用不用 shell。
#
# 时刻既然不在这判了，cron 的**密度**就成了唯一的成本项：每个 tick 都会起一个 python 进程、
# 真打一轮上游（闸门②在取数之前，当天那条日报已经发过的那些 tick 会立刻退出、不打上游）。账户内存已经 96%
# 就是建议只挂两个时刻（08:10 首发、08:40 兜底补发）而不是每分钟一条的原因：
# 那一刻要正好取数全挂（退出码 1、当天不记账），08:40 那次就是当天的补发窗口。
#
# 路径全按自身位置解析：本脚本必须和 `api/`、`config.ini`、`indicator.ini` 同一层（也就是站点根）。
# 覆盖用环境变量：ALERT_PY=/绝对路径/python 换解释器，ALERT_ARGS='--html-alert' 改成预览（只看不发，
# 预览永不记账、也永不碰 TG）。
#
# 2026-09-24 再收两处：① 原来那个 `ALERT_TIME` 开关（把时刻闸门加回来的口子）整个删了——本脚本从此
#    不判任何时刻，时刻只有 crontab 一个来源；② 每次执行都**原样打印那一行 python 命令**（见文件末尾），
#    进日志也回显，照着它在 ssh 里就能手工复跑，不必回头读脚本猜解释器和参数。

set -u

ROOT="$(cd "$(dirname "$0")" && pwd)"
PY="${ALERT_PY:-/usr/home/myaibtc/vevns/web3/bin/python}"
ARGS="${ALERT_ARGS:---html-alert --send}"
LOG="$ROOT/logs/notify_cron.log"

# 「几点跑」整个交给 crontab 那五个字段，脚本里不再判时刻（原来那个 ALERT_TIME 开关已删）。
# 但**这两行设空不能删**：`indicator.ini` 里两段各自还写着 `ALERT_AT = 13:28`，不清空的话
# notify.py 的 alert_gate() 会照它挡到 13:28 —— 那样时刻就有了两个来源，cron 上写的钟点说了不算。
# 段名前缀是 HTML_ALERT_TOP_ / HTML_ALERT_BOTTOM_（2026-09-24 拆两段之后 env 名跟着换了，别只清一个）。
# 于是本脚本只剩一道闸门：「一个日历日只发一条」（一本账 data/notify_html_state.json）。
# 它是防重复推送的，不是防早跑的：同一分钟里 cron 打两次、或者 08:10 发成功后 08:40 那次兜底，都靠它挡成一条。
HTML_ALERT_TOP_AT=""
HTML_ALERT_BOTTOM_AT=""
export HTML_ALERT_TOP_AT HTML_ALERT_BOTTOM_AT

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
# 这一行就是本次真正执行的命令（上面那几个 export 已经设进环境，所以它与实际调用逐字等价）：
# 打进日志头，也回显一份到 stdout —— 事后不必读脚本猜解释器和参数，ssh 里照抄就能复跑。
CMD="HTML_ALERT_TOP_AT= HTML_ALERT_BOTTOM_AT= PYTHONIOENCODING=utf-8 PYTHONUTF8=1 PYTHONPATH=$ROOT/api:$ROOT \
\"$PY\" $ROOT/api/notify.py $ARGS"
# %Z 顺带把服务器时区打进日志：第一次跑完照它和 config.ini 的时区对一眼，别猜偏移
echo "----- $(date '+%F %T %Z')  $CMD -----" >> "$LOG" 2>&1
echo "$CMD"
"$PY" "$ROOT/api/notify.py" $ARGS >> "$LOG" 2>&1
rc=$?
echo "----- exit=$rc（0=闸门挡/已发出；1=取数全挂或 TG 发送失败，都不记账，下次 tick 自续；2=没配 [notify] tg_bot）-----" >> "$LOG" 2>&1
# stdout 只留这两行指路：判定明细全在日志里，cron 的邮件也就能看清「跑过了、执行的哪条、去哪看」。
echo "跑完了：exit=$rc（0=闸门挡/已发出，1=取数全挂或发送失败，2=没配 tg_bot）  明细看 $LOG"
echo "  当天要再发一次：ALERT_ARGS='--html-alert --send --force' $0 ；只看数不发：ALERT_ARGS='--html-alert' $0"
exit $rc
