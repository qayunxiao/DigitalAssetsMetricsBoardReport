#!/usr/bin/env bash
# serv00 侧「把公网看板彻底停掉」，并用同一个口径对比内存 —— deploy_app.sh 的反向操作
#
#   bash shutdown_app.sh --status  只拍快照，什么都不改（**先跑这条**：看清楚 ps 探测和 worker 明细再决定）
#   bash shutdown_app.sh           停：杀本站点残留的 Passenger worker（先列 PID 等你 y/N），停前停后各拍一张
#   bash shutdown_app.sh --detach  连入口一起摘（三份 passenger_wsgi.py 改名 .stopped）——**这才是停得住的那条**
#   bash shutdown_app.sh --yes     不询问直接动手（非交互环境必须显式加：读不到终端时默认按取消处理）
#   bash shutdown_app.sh --start   反向恢复：把入口搬回原位 + 摸 restart.txt + 打一次 /api/health 唤醒，再拍快照
#
# 为什么要这个脚本：面板那个 512 MB 是**账户级**的，Passenger 又按「并发慢请求」横向扩进程，
# 所以想知道「这 1.5G 里站点占多少、别的占多少」，唯一的办法是把它彻底停掉再称一次。
#
# 两条在服务器上量出来的事实（2026-09-24，别再按直觉改）：
# · **serv00 没有 `devil www stop`**：回 `[Error] This function does not exist`，`devil www list` 里也只有
#   域名/类型/路径三列，压根没有 running/stopped 那种状态。所以「停」在这里 = 杀进程 +（要停得住）摘入口。
# · **`ps -axo …` 与 `ps -o rss= -u 用户` 在这台机器上一行都不吐**（那次跑出来的快照三行全 0，连 SSH 自己
#   都没算进去，那个 0 是假的）。所以脚本先探测哪种取法有数再用哪种，两种都没数就明说「这一张不可信」，
#   而不是把 0 当真值报出去。手工核：`ps aux | head -5`。
#
# 三条口径说明（对比时别踩）：
# 1. 内存按 `ps` 里本账户进程的 RSS 直加，跟面板一个算法。注意 RSS 会把共享页重复计一次：
#    4 个 worker 停掉 3 个，账户总量降幅往往**小于** 3×单进程 —— 看趋势就够，别拿差值除以单进程当进程数。
# 2. 停完**别再 curl 站点**（本脚本停的时候也就不会打）：Passenger 是按需拉起的，任何一次请求都会立刻
#    再生一个 worker，你会以为「没停干净」。验证靠 ps，不靠 curl。
# 3. 本脚本只碰命令行里带 $DOMAIN 的 python 进程，绝不 `pkill -U`（那会连 cryptoTrader 和你的 SSH 一起送走）。
#    快照里刻意把「其它 python 进程」单独列一行，就是让你自己确认没误伤。
#
# 只读接口：全脚本唯一打出去的 HTTP 请求是 --start 里那一次 /api/health（不碰上游、不写数据）。
# 绝不碰 /api/allocation/report?kind= —— 那是真跑报表脚本 = 真发一条 Telegram。
#
# 和 deploy_app.sh 一样：这个脚本不在上传包里，要单独传（脚本自己覆盖自己会让 bash 读到半截）。

set -uo pipefail

DOMAIN="${DOMAIN:-myaibtc.serv00.net}"
USER="${USER:-$(id -un 2>/dev/null || echo unknown)}"   # Git Bash 里 $USER 可能没设，ps -u 要它
SITE="${SITE:-$HOME/domains/$DOMAIN}"
DOCROOT="${DOCROOT:-$SITE/public_python/public}"
VENV_PY="${VENV_PY:-$HOME/vevns/web3/bin/python}"
URL="${URL:-http://$DOMAIN}"
# serv00 是 FreeBSD，本地没法验 ps 的列格式；PSBIN 指到一个假 ps 脚本就能离线跑解析/求和/展示这条路。
PSBIN="${PSBIN:-ps}"

MODE="stop"; ASK=1
while [ $# -gt 0 ]; do
  case "$1" in
    --status)   MODE="status" ;;
    --start)    MODE="start" ;;
    --detach)   MODE="detach" ;;
    --yes|-y)   ASK=0 ;;
    -h|--help)  sed -n '2,31p' "$0"; exit 0 ;;
    *) echo "未知参数：$1（-h 看用法）" >&2; exit 2 ;;
  esac
  shift
done

# ---------- 快照用的几个小函数 ----------
# serv00 实测（2026-09-24 用户跑的回显）：`ps -axo …` 和 `ps -o rss= -u 用户` 在这台机器上**一行都不吐**
# （快照三行全 0），而他平时用 `ps aux` 是能看见那 4 个 worker 的。所以这里先探测哪种取法有数、再用那种，
# 两种都没数就**明说探测失败**——把 0 当真值报出去，比没有数字更坏。
# 两种取法都归一成同四列：`pid rss user when ARGS…`，下面的 grep/awk 与 kill 只认这个形状。
PS_STYLE="${PS_STYLE:-}"            # 空=自动探测；出问题时可 PS_STYLE=oneline|aux 强制，方便对着 ps 手校

ps_raw_oneline() { "$PSBIN" -axo user=,pid=,rss=,etime=,args= 2>/dev/null; }
ps_raw_aux()     { "$PSBIN" -wwaux 2>/dev/null; }

ps_rows() {
  case "$PS_STYLE" in
    oneline) ps_raw_oneline | awk 'NF > 4 {printf "%s %s %s %s ", $2, $3, $1, $4;
                                          for (i = 5; i <= NF; i++) printf "%s ", $i; print ""}' ;;
    aux)     ps_raw_aux | awk 'NF > 10 && $2 + 0 > 0 {printf "%s %s %s %s ", $2, $6, $1, $9;
                                          for (i = 11; i <= NF; i++) printf "%s ", $i; print ""}' ;;
    *)       ;;                     # 没探测／都没数：宁可可空，不编
  esac
}

ps_probe() {
  [ -n "$PS_STYLE" ] && return
  if [ -n "$(ps_raw_oneline | head -3)" ]; then PS_STYLE=oneline
  elif [ -n "$(ps_raw_aux | head -3)" ];   then PS_STYLE=aux
  else PS_STYLE=none; fi
}

app_ps() {   # 本站点 Passenger 拉起的 python：pid rss user when args
  ps_rows | grep -F "$DOMAIN" | grep -v -e grep -e shutdown_app -e 'ps_raw' | awk '/python/ {print}'
}

app_pids() { app_ps | awk '{print $1}'; }

sum_mb() { awk '{s += $2} END {printf "%.0f", s / 1024}'; }   # stdin 读归一化行，第 2 列是 KB

other_py() {   # 不属于本站点的 python 进程（核对没误伤 cryptoTrader）
  ps_rows | awk -v d="$DOMAIN" '$0 !~ d && /python/ && $0 !~ /awk|shutdown_app|ps_raw/ {print}'
}

panel_state() {
  command -v devil >/dev/null 2>&1 || { echo "（这台机器没有 devil 命令）"; return; }
  local line; line="$(devil www list 2>/dev/null | grep -F "$DOMAIN" || true)"
  [ -n "$line" ] && echo "$line" || echo "（devil www list 里没有 $DOMAIN 这一行）"
}

snapshot() {   # $1 = 这一张快照叫什么
  local tag="$1" n tot rows mine odd
  ps_probe
  rows="$(ps_rows | grep -c . || true)"
  mine="$(ps_rows | awk -v u="$USER" '$3 == u' | grep -c . || true)"
  n="$(app_ps | grep -c . || true)"
  tot="$(ps_rows | awk -v u="$USER" '$3 == u {s += $2} END {printf "%.0f", s / 1024}')"
  echo "--- 快照：$tag ---"
  printf "  ps 探测         : PS_STYLE=%s（ps 里 %s 行，用户名 %s 匹配 %s 行）\n" "$PS_STYLE" "$rows" "$USER" "$mine"
  if [ "$PS_STYLE" = none ] || [ "$rows" = 0 ] || [ "$mine" = 0 ]; then
    echo "  ⚠ 这一张的 0 **不可信**：ps 取不到行（或取到的行里没有本账户用户名）。"
    echo "    手工核一眼：$(basename "$PSBIN") aux | head -5   和   $PSBIN -axo user=,pid=,rss=,etime=,args= | head -5"
    echo "    对上了就强制指定取法再跑：PS_STYLE=aux bash $0 --status"
  fi
  printf "  本账户 RSS 合计 : %s MB（面板上限 512 MB，那一格就是这个口径）\n" "$tot"
  printf "  本站点 worker   : %s 个，合计 %s MB\n" "$n" "$(app_ps | sum_mb)"
  if [ "$n" != "0" ]; then
    app_ps | awk '{printf "      pid=%-7s %6.0f MB  %-9s  %s\n", $1, $2/1024, $4, substr($0, index($0, $5))}'
  fi
  printf "  其它 python 进程: %s 个，合计 %s MB（不属于本站点，本脚本不会动它们）\n" \
    "$(other_py | grep -c . || true)" "$(other_py | sum_mb)"
  # 兜底：Passenger 有时把标题写成 `Passenger: App …` 之类不带 python 的样子，那条既不进 worker 也不进
  # 「其它」，会静默漏掉。所以把带域名又不像 python 的行摊开给你看。
  odd="$(ps_rows | grep -F "$DOMAIN" | grep -v -e grep -e shutdown_app -e 'ps_raw' -e python || true)"
  if [ -n "$odd" ]; then
    echo "  ⚠ 带 $DOMAIN 但不像 python 的进程（没算进上面 worker，自己看一眼是什么）："
    printf '%s\n' "$odd" | sed 's/^/      /'
  fi
  echo "  面板            : $(panel_state)"
  LAST_TOTAL="$tot"
}

BEFORE=""; BEFORE_N=""

# ---------- status ----------
if [ "$MODE" = "status" ]; then
  echo "站点根 $SITE"
  snapshot "现状（--status，什么都没改；故意不打 $URL，一次请求就会拉起一个 worker）"
  exit 0
fi

# ---------- detach 的开与关 ----------
ENTRIES=("$SITE/passenger_wsgi.py" "$SITE/public_python/passenger_wsgi.py" "$DOCROOT/passenger_wsgi.py")

detach_entries() {
  for f in "${ENTRIES[@]}"; do
    if [ -f "$f" ]; then
      mv "$f" "$f.stopped" && echo "    摘掉 $f → $f.stopped"
    elif [ -f "$f.stopped" ]; then
      echo "    已经是摘掉状态：$f.stopped"
    else
      echo "    这里本来就没有入口文件：$f"
    fi
  done
}

reattach_entries() {
  for f in "${ENTRIES[@]}"; do
    [ -f "$f.stopped" ] || continue
    if [ -f "$f" ]; then
      echo "    ⚠ $f 和 $f.stopped 同时存在（中间跑过 deploy_app.sh？），保留现文件，把备份留在原地不动"
      continue
    fi
    mv "$f.stopped" "$f" && echo "    恢复 $f"
  done
}

# ---------- start（恢复）----------
if [ "$MODE" = "start" ]; then
  echo "=== 恢复站点 ==="
  reattach_entries
  mkdir -p "$SITE/tmp" "$SITE/public_python/tmp" "$DOCROOT/tmp"
  touch "$SITE/tmp/restart.txt" "$SITE/public_python/tmp/restart.txt" "$DOCROOT/tmp/restart.txt"
  if command -v devil >/dev/null 2>&1; then
    devil www restart "$DOMAIN" 2>&1 | sed 's/^/    devil www restart: /' || true
  fi
  echo "    摸过 restart.txt（Passenger 没有「启动」这一步，下个请求来才起进程）"
  if command -v curl >/dev/null 2>&1; then
    h="$(curl -s -m 45 "$URL/api/health" || true)"
    echo "    唤醒探针 /api/health：$(printf %s "$h" | grep -o '"mode": *"[a-z]*"' || echo '没拿到 mode —— 站点没起来，看首页那段纯文本诊断')"
    [ -n "$h" ] && echo "    $(printf %s "$h" | grep -o '"pid": *[0-9]*\|"rss_mb": *[0-9.]*\|"stale": *[a-z]*' | tr '\n' ' ')"
    echo "    （rss_mb 是**这一个进程**的峰值，不是账户总量；两个口径别混着比）"
  fi
  sleep 2
  snapshot "恢复后"
  exit 0
fi

# ---------- stop / detach ----------
echo "站点根 $SITE"
snapshot "停止前"
BEFORE="$LAST_TOTAL"; BEFORE_N="$(app_ps | grep -c . || true)"

if [ "$MODE" = "detach" ]; then
  echo
  echo "=== 摘入口（$MODE）：让 Passenger 就算被请求也起不来应用 ==="
  detach_entries
fi

echo
echo "=== 1. 面板级停止：**serv00 没有这个功能** ==="
# 2026-09-24 服务器上实测：`devil www stop <域名>` 回 `[Error] This function does not exist`
# （`devil www list` 里那一行只有 域名/类型/路径 三列，压根没有 running/stopped 状态）。
# 所以「停站点」在这台机器上只有两条真路：把 worker 进程杀掉（下面第 2 步），和把入口摘掉（跑 --detach）。
# 只杀进程不算停干净——Passenger 按需拉起，下一个请求就再生一个；要它**停得住**就得 --detach。
if [ "$MODE" != "detach" ]; then
  echo "    这次没带 --detach，所以入口还在原位：下面杀完之后，任何人访问一次站点就会再起 worker。"
  echo "    想让「停止」这件事站得住：bash $0 --detach（把三份 passenger_wsgi.py 改名，--start 一并搬回）"
fi

echo
echo "=== 2. 本站点残留 worker ==="
pids="$(app_pids)"
if [ -z "$pids" ]; then
  echo "    ps 里已经没有本站点的 python 进程（要么空闲自己退了，要么上一步收干净了）"
else
  echo "    要杀的 PID：$(echo $pids | tr '\n' ' ')"
  echo "    依据：命令行里带 $DOMAIN 的 python 进程（上面快照列的那几行）"
  if [ "$ASK" = 1 ]; then
    printf "    确认执行 kill -TERM？只有 cryptoTrader 或别的应用被你手动跑在这个账户里时才会被牵连 [y/N] "
    # 没有 tty（管道、cron、tee）时**默认取消**，而不是默认开杀——要非交互就显式加 --yes。
    if ! read -r ans 2>/dev/null </dev/tty; then
      ans=""
      echo "（读不到终端，按取消处理；非交互环境请显式加 --yes）"
    fi
    case "$ans" in
      y|Y|yes|YES) ;;
      *) echo "    取消。只做到「面板已停止 + 入口已摘（若 --detach）」，已跑着的 worker 仍在内存里"; exit 0 ;;
    esac
  fi
  for p in $pids; do kill -TERM "$p" 2>/dev/null || true; done
  i=0
  while [ "$i" -lt 10 ]; do
    [ -z "$(app_pids)" ] && break
    sleep 0.5; i=$((i + 1))
  done
  left="$(app_pids)"
  if [ -z "$left" ]; then
    echo "    TERM 收干净了（等了 $i × 0.5s）"
  else
    echo "    TERM 后还剩：$(echo $left | tr '\n' ' ')，补 KILL"
    for p in $left; do kill -KILL "$p" 2>/dev/null || true; done
    sleep 1
  fi
fi

echo
snapshot "停止后"
AFTER="$LAST_TOTAL"
echo "--- 对比 ---"
echo "  停止前 ${BEFORE} MB（worker ${BEFORE_N} 个）  →  停止后 ${AFTER} MB  =  降 $((BEFORE - AFTER)) MB"
echo "  剩下这些**不是**本看站的：cryptoTrader、你的 SSH/scp、系统侧其它进程（上面「其它 python 进程」那一行）"
echo "  ⚠ 现在别用 curl 验证站点，一请求就复活；要恢复：bash $SITE/shutdown_app.sh --start"
if [ "$MODE" = "detach" ]; then
  echo "  这次用了 --detach，入口是改名状态，--start 会一并搬回来（deploy_app.sh 会重新铺，也等于恢复）"
fi
