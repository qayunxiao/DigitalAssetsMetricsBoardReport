#!/usr/bin/env bash
# serv00 侧部署／重载 DigitalAssetsMetricsBoardReport（Passenger WSGI 站点，没有守护进程可管）
#
#   bash deploy_app.sh              拉两个仓库 → 停应用 → 装到站点根 → 重载并拉起 Passenger → 冒烟
#   bash deploy_app.sh --reload     只重载 + 冒烟（代码没动，单纯想让进程换个新的）＋ 治 .sh（去 CR + 补 x 位）：
#                                   scp 单独传上去的 alert_cron.sh / shutdown_app.sh 就靠这一条救活
#   bash deploy_app.sh --no-pull    不 pull，用仓库目录里现有的内容装机（GitHub 不可达时用）
#   bash deploy_app.sh --zip [包]   用上传的 damb-public-*.zip 装机，完全不碰 git（离线退路）
#   bash deploy_app.sh --force-data 连 data/report_quota.json 与 data/risk_history.csv 一起覆盖
#   bash deploy_app.sh --no-stop    装机前不停应用（默认停：TERM → 等 3 秒 → 没退的 KILL）
#
# **每次都会停一下应用**（2026-09-25 加，这是脚本的第 2.5 步）：装机那一段是往站点根铺几百个文件，
# 应用进程还在跑有两个代价——① 它正占着几百 MB（账户内存你看过 96%），铺文件的时候一起挤；
# ② `cp` 是就地截断再写，并发请求可能 import 到半抄的 `.py`。停一下只多几秒 downtime，两个都躲掉。
# 停机刻意放在 `git fetch` **之后**：拉仓库可能几十秒网络等待，没必要让站点跟着空这几秒。
# 「停止」为什么是自己 kill 而不是 devil：serv00 的 `devil www` 没有 stop 这个功能（见下面那段
# 「关于 python 服务有没有启动」的实测），而 Passenger 的应用进程本来就是「请求来了才 spawn、
# 杀掉就等于重启」的模型，kill 掉不会留下什么需要收拾的。
# 匹配范围收得很窄，见 app_pids()：只杀本用户、命令行里有本站域名、且是 python 的那些。
#
# 可以反复执行：每次都重新铺一遍跟踪文件（没有「比标记新才装」这种短路），运行期状态默认保留，
# config.ini 每次覆盖前都留一份带时间戳的 .bak。
# ⚠ 但别把它当「带事务的部署」：2.5 之后、6 之前任何一个 `exit 1`（比如 3.5 那两份 \$HOME 下的覆盖文件不见了）
#    会让脚本停在中途，站点根就此半新半旧。好消息是**不会一直停着**——Passenger 有请求就重新 spawn，
#    盘上的文件立刻能服务；坏消息是没摸 restart.txt，仍活着的那个进程（2.5 只杀带本站域名的 python）
#    可能还在跑旧代码。补救就两条：`bash deploy_app.sh --reload` 重跑一遍，或手工
#    `touch tmp/restart.txt` 再 `curl $URL/api/health` 确认 pid 变了。
#
# 装机来源跟他的 cryptoTrader 脚本一个路子：仓库常驻 `~/vevns/<仓库名>`，有 .git 就更新、没有就 clone，
# 然后把 `git ls-files` 列出来的跟踪文件铺到 Passenger 站点根（$SITE）。
#
# 为什么默认**不**覆盖 data 里那两个文件：它们是运行期状态。`data/report_quota.json` 在仓库里有记录
# （.gitignore 加得晚，已经跟踪上了），照抄一次部署就等于把服务器上「今天已点几次」清回旧值、白送几次点击。
#
# 关于「python 服务有没有启动」：Passenger 是按需拉起的，站点空闲时 `ps` 里一个进程都没有，
# 所以不能拿 ps 当判据。原本想用面板 `devil www list` 的 running/stopped —— 2026-09-24 在 s11 实测
# 那份输出**只有域名/类型/路径三列，没有状态列**（`devil www stop` 也不存在：This function does not exist），
# 所以下面取到的 panel 会是「未知」、running 恒为 0，那条 devil www restart 只是尽力而为（摸 restart.txt 才是真通路）。
# 真正判「到底部署过没有」还是看站点根有没有 api/app.py。
# 本脚本只碰 $SITE 和 $HOME/vevns 下这两个仓库，绝不碰别的应用。
#
# 私有仓库第一次要有凭证（token 当密码），跑一次这两行、再跑本脚本即可：
#   git config --global credential.helper store
# 注意 `store` 是明文写进 ~/.git-credentials，serv00 上自己权衡；token 无论如何不要进本脚本、config.ini 或聊天记录。

set -euo pipefail

# ---------- 0. 先把自已复制一份再执行 ----------
# git pull 会改掉仓库里这份**正在被 bash 逐行读取**的脚本（bash 边读边执行，改了就跑飞），
# 所以第一件事是换一个 git 碰不到的副本继续跑。
if [ -z "${DAMB_DEPLOY_TMP:-}" ]; then
  t="${TMPDIR:-/tmp}/damb_deploy_$$.sh"
  cp "$0" "$t"
  rc=0
  DAMB_DEPLOY_TMP="$t" bash "$t" "$@" || rc=$?
  rm -f "$t"
  exit "$rc"
fi

DOMAIN="${DOMAIN:-myaibtc.serv00.net}"            # 下面这些都能用环境变量覆盖，方便换域名或演练
SITE="${SITE:-$HOME/domains/$DOMAIN}"
DOCROOT="${DOCROOT:-$SITE/public_python/public}"
VENV_PY="${VENV_PY:-$HOME/vevns/web3/bin/python}"
URL="${URL:-http://$DOMAIN}"
BRANCH="${BRANCH:-main}"
REPO_URL="${REPO_URL:-https://github.com/qayunxiao/DigitalAssetsMetricsBoardReport.git}"
REPO_DIR="${REPO_DIR:-$HOME/vevns/$(basename "${REPO_URL%.git}")}"
CRYPTO_REPO="${CRYPTO_REPO:-https://github.com/qayunxiao/cryptoTrader.git}"
CRYPTO_DIR="${CRYPTO_DIR:-$HOME/vevns/cryptoTrader}"    # 持仓报告按钮真跑的就是这里的两个 tests/*.py

MODE="git"; SYNC=1; FORCE_DATA=0; ZIP=""; STOP=1
while [ $# -gt 0 ]; do
  a="$1"; shift
  case "$a" in
    --reload)     MODE="reload" ;;
    --no-pull)    SYNC=0 ;;
    --no-stop)    STOP=0 ;;
    --force-data) FORCE_DATA=1 ;;
    --zip)        MODE="zip"; if [ $# -gt 0 ] && [ "${1#--}" = "$1" ]; then ZIP="$1"; shift; fi ;;
    --zip=*)      MODE="zip"; ZIP="${a#--zip=}" ;;
    # 用法就是文件头那一段注释：整段打到「第一行真代码」为止，不用维护行号（加注释就不用改这里）
    -h|--help)    awk 'NR==1{next} /^#/{sub(/^# ?/, ""); print; next} !NF{print; next} {exit}' "$0"; exit 0 ;;
    --redeploy)   echo "（--redeploy 已不需要：默认每次都重新铺一遍）" ;;
    *) echo "未知参数：$a（-h 看用法）" >&2; exit 2 ;;
  esac
done
if [ "$MODE" != "reload" ]; then                      # 失败也要收掉 /tmp 里那份副本
  trap 'rm -f "$DAMB_DEPLOY_TMP"' EXIT
fi
if [ "$MODE" = "zip" ] && [ -z "$ZIP" ]; then
  ZIP="$(ls -1t "$SITE"/damb-public-*.zip "$HOME"/damb-public-*.zip 2>/dev/null | head -1 || true)"
fi

cd "$SITE"

# ---------- 1. 现状 ----------
deployed=0
if [ -f "$SITE/api/app.py" ] && [ -f "$SITE/passenger_wsgi.py" ]; then deployed=1; fi
running=0
panel="未取到"
if command -v devil >/dev/null 2>&1; then
  line="$(devil www list 2>/dev/null | grep -F "$DOMAIN" || true)"
  case "$line" in
    *running*) running=1; panel="running" ;;
    *stopped*) panel="stopped" ;;
    *) if [ -n "$line" ]; then panel="未知（$line）"; fi ;;
  esac
fi
echo "=== 现状 === 已部署=$deployed  面板状态=$panel  站点根=$SITE  模式=$MODE  装机前停应用=$STOP"

# ---------- 2. 拉仓库：只允许快进，服务器上的本地改动绝不悄悄丢掉 ----------
# 没有可用凭证时让 git 直接失败，而不是挂在那里等输入（面板/无 tty 环境下会卡死）。
export GIT_TERMINAL_PROMPT="${GIT_TERMINAL_PROMPT:-0}"
sync_repo() {
  local dir="$1" url="$2"
  if [ ! -d "$dir/.git" ]; then
    mkdir -p "$(dirname "$dir")"
    echo "    clone $url"
    git clone --branch "$BRANCH" "$url" "$dir" || return 1
  fi
  git -C "$dir" fetch origin "$BRANCH" || return 1
  git -C "$dir" checkout "$BRANCH" || return 1
  git -C "$dir" merge --ff-only "origin/$BRANCH" || return 1
  echo "    $dir @ $(git -C "$dir" rev-parse --short HEAD)  $(git -C "$dir" log -1 --format=%s)"
}

sync_failed=""
if [ "$MODE" = "git" ] && [ "$SYNC" = 1 ]; then
  echo "=== 1. 同步仓库 ==="
  sync_repo "$REPO_DIR" "$REPO_URL"   || sync_failed="看板仓库 $REPO_DIR（clone/fetch/快进失败：网络、凭证，或目录里有本地改动。本地改动请自己 git -C $REPO_DIR status 看过再决定，本脚本不会替你 reset；急着装现有内容就加 --no-pull）"
  sync_repo "$CRYPTO_DIR" "$CRYPTO_REPO" || echo "    ⚠ cryptoTrader 没同步成功，沿用目录里现有的脚本与持仓数据（$CRYPTO_DIR）"
fi

# ---------- 2.4 停机前的前置检查 ----------
# 放在 2.5 **之前**的理由：这两处缺文件下面都是当场 `exit 1`，既然要失败，就别先把站点停一遍再告诉人失败。
# `~/allocation.py`、`~/config.ini` 不在 git 里（是服务器上手工维护的那两份，3.5 每次都会盖到站点根），
# 所以改了仓库里的 `api/allocation.py` / `config.ini` 而忘了同步 `~` 下那两份，站点上仍是旧的 —— 反过来，
# 手工挪动过 `~` 的话这里会提前拦住，而不是铺完文件才崩。
if [ ! -f /home/myaibtc/allocation.py ] || [ ! -f /home/myaibtc/config.ini ]; then
  echo "!! 3.5 要用的 /home/myaibtc/allocation.py 与 /home/myaibtc/config.ini 有缺（这两份是服务器上手工维护的，不在 git 里）" >&2
  echo "   —— 没停应用、没装机；把文件放回去再重跑" >&2
  exit 1
fi
if [ "$MODE" = "git" ] && [ ! -f "$REPO_DIR/api/app.py" ]; then
  echo "!! $REPO_DIR 里没有 api/app.py（仓库没拉下来？先看过再用 --no-pull）—— 没停应用、没装机" >&2
  exit 1
fi

# ---------- 2.5 停应用：装机之前把本站点那几个 python 进程收掉（--no-stop 跳过）----------
# 匹配范围收得很窄，四条都是必要的：
#   · 只认「本用户 + 命令行里带本站域名 + 带 python」，别的账户/别的应用一概不碰。
#   · 排 deploy：你很可能就是 `bash /usr/home/.../myaibtc.serv00.net/deploy_app.sh` 这样进来的，
#     自己那一行命令行里同样带着域名，不排掉就是脚本自杀。
#   · 排 awk：域名是从 `-v d=...` 传进去的，awk 自己的命令行里就有它，会把自家这条算成应用进程。
#   · 排 passenger-：那是 Passenger 的 spawner，归 Passenger 核心管，不该由部署脚本杀。
#   · 排 notify.py：cron 那条日报进程（`alert_cron.sh` 起的）命令行里也带着本站域名，会被上面的规则捞进来。
#     它一次要跑一两分钟取数，杀了不丢账（真发失败本来就不记账，下一分钟的 tick 自己再试），
#     但白扔一轮上游 + 在日志里留一坨半截输出，所以不碰。
# 持仓报告的子进程（cryptoTrader/tests/*.py）命令行里没有本站域名，天然不在匹配范围内——这也是故意的，
# 正跑着的报表别被一次部署掐断（它还会往 TG 发消息，掐在中间比慢几秒糟得多）。
app_pids() {
  ps -ww -o pid=,command= -u "$(id -un)" 2>/dev/null | awk -v d="$DOMAIN" '
    index($0, d) > 0 && index($0, "python") > 0 && $0 !~ /deploy|awk|passenger-|notify\.py/ { print $1 }' || true
}

if [ "$STOP" = 1 ]; then
  echo "=== 2.5 停应用（腾出内存、避开半抄的 .py；--no-stop 跳过，6/7 两步负责把它带回来）==="
  pids="$(app_pids)"
  if [ -z "$pids" ]; then
    echo "    没有在跑的应用进程（Passenger 按需拉起，空闲时本来就一个都没有）"
  else
    echo "    TERM $(printf %s "$pids" | tr '\n' ' ')"
    kill $pids 2>/dev/null || true
    sleep 3
    left="$(app_pids)"
    if [ -n "$left" ]; then
      echo "    3 秒没退，KILL -9 $(printf %s "$left" | tr '\n' ' ')"
      kill -9 $left 2>/dev/null || true
      sleep 1
    fi
    echo "    已停，现在还剩 $(app_pids | grep -c . || true) 个（0 = 干净）"
  fi
fi

# ---------- 3. 装机：把跟踪文件铺到站点根 ----------
if [ "$MODE" = "reload" ]; then
  echo "=== 2/3. 跳过装机（--reload）==="
elif [ "$MODE" = "zip" ]; then
  if [ -z "$ZIP" ] || [ ! -f "$ZIP" ]; then
    echo "!! 站点根或 \$HOME 里找不到 damb-public-*.zip，先上传再跑（或去掉 --zip 走 git）" >&2
    exit 1
  fi
  echo "=== 2. 解压部署：$ZIP → $SITE ==="
  if [ -f "$SITE/config.ini" ]; then                       # config.ini 在包里，会被覆盖，先留一份
    cp -p "$SITE/config.ini" "$SITE/config.ini.bak.$(date +%Y%m%d-%H%M%S)"
  fi
  if tar -xf "$ZIP" 2>/dev/null; then
    echo "    tar（bsdtar 原生读 zip）OK"
  else
    echo "    tar 解不动，改用 python -m zipfile"
    "$VENV_PY" -m zipfile -e "$ZIP" "$SITE/"
  fi
else
  [ -f "$REPO_DIR/api/app.py" ] || { echo "!! $REPO_DIR 里没有 api/app.py，仓库还没拉下来（$sync_failed）" >&2; exit 1; }
  echo "=== 2. 装机：$REPO_DIR 的跟踪文件 → $SITE ==="
  if [ -f "$SITE/config.ini" ]; then
    bak="$SITE/config.ini.bak.$(date +%Y%m%d-%H%M%S)"
    cp -p "$SITE/config.ini" "$bak"
    echo "    config.ini 用仓库那份覆盖，旧的留在 $bak（服务器上调过 limit 的话从这儿抄回去）"
  fi
  n=0; keep=0; skip=0
  while IFS= read -r -d '' f; do
    case "$f" in
      data/report_quota.json|data/risk_history.csv)
        if [ "$FORCE_DATA" = 0 ] && [ -f "$SITE/$f" ]; then
          echo "    保留站点上那份（运行期状态）：$f"; keep=$((keep + 1)); continue
        fi ;;
      api/USStockCrashMonitor/*|api/Liquidity/_legacy/*|*__pycache__*|*.pyc|.idea/*|.qoder-credits/*|logs/*)
        skip=$((skip + 1)); continue ;;                      # 老项目留档与缓存不进公网机器，跟当初的 zip 白名单一致
    esac
    d="$SITE/$(dirname "$f")"
    mkdir -p "$d"
    cp -p "$REPO_DIR/$f" "$SITE/$f"
    n=$((n + 1))
  done < <(git -C "$REPO_DIR" ls-files -z)
  echo "    铺了 $n 个文件，保留站点运行期状态 $keep 个，跳过留档/缓存 $skip 个"
  git -C "$REPO_DIR" rev-parse HEAD > "$SITE/.deployed_commit"
  if ! cmp -s "$DAMB_DEPLOY_TMP" "$REPO_DIR/deploy_app.sh"; then
    echo "    顺带一句：deploy_app.sh 本身也更新了，这次跑的仍是旧版逻辑（新的已铺好，改了部署流程就再跑一次）"
  fi
fi

# ---------- 3.5 用 $HOME 下那两份替换站点上的仓库版 ----------
# 位置不能往前提：这两份都是 git 跟踪文件，放在上面的装机循环之前会被 `cp -p $REPO_DIR/$f` 原样盖回去，
# cp 返回 0 但效果归零。用不带 -p 的 cp，mtime=此刻，面板的 stale 才不会被骗成 false。
echo "=== 3.5 覆盖 allocation.py 与 config.ini ==="
cp /home/myaibtc/allocation.py "$SITE/api/allocation.py"
cp /home/myaibtc/config.ini    "$SITE/config.ini"
echo "    ok  两份都已换成 \$HOME 下那一份"

[ -f "$SITE/api/app.py" ] || { echo "!! 站点根没有 api/app.py，装机没成功（包/仓库不对？）" >&2; exit 1; }

if [ "$MODE" != "reload" ]; then
  echo "=== 3. 清掉 docroot 里的首页（留着会被 nginx 直出，绕过服务端替换）==="
  rm -f "$DOCROOT/index.html" "$DOCROOT/Index.html"
  stray="$(find "$DOCROOT" -maxdepth 1 -name '*.html' 2>/dev/null || true)"
  if [ -n "$stray" ]; then echo "    ⚠ docroot 里还有别的 HTML，自己确认要不要留：$stray"; fi

  echo "=== 4. 入口多放两份（app root 认哪一层没有权威文档，_find_root() 会从任一份向上找到真根）==="
  cp -p "$SITE/passenger_wsgi.py" "$SITE/public_python/passenger_wsgi.py"
  cp -p "$SITE/passenger_wsgi.py" "$DOCROOT/passenger_wsgi.py"

  echo "=== 5. 建运行目录（.sh 的执行位统一在 5.5 补，那里连 --reload 都会走）==="
  mkdir -p "$SITE/data" "$SITE/tmp"
  touch "$SITE/.deployed"
fi

# ---------- 3.9 站点根所有 .sh：先去 CR 再补执行位，刻意放在上面的 if **外面** ----------
# 为什么去 CR：这台开发机 git 的 core.autocrlf=true，checkout 出来的 .sh 工作副本带 CRLF，
# scp 到 FreeBSD 后 `#!/bin/sh\r` 会让内核去找一个叫 "sh\r" 的解释器，报出来的却是
# `No such file or directory`（2026-09-24 在 s11 上 `./deploy_app.sh` 就是这么栽的；
# 站点根那份走 git checkout、是 LF，所以一直没事）。cron 里同样的坑是**静默**失败。
# 为什么补执行位：名字不能只列 start_app.sh / deploy_app.sh —— alert_cron.sh 在 crontab 里是
# **直接当命令执行**的（写的就是 /usr/home/.../alert_cron.sh，没有 `sh` 前缀），少 x 位＝每天一次
# permission denied，只在 cron 的邮件里露一下，logs/notify_cron.log 连一行都没有。
# 放在 if 外面：运维脚本经常是单独 scp 上去的，希望 `--reload` 这一条轻命令就能治，而不是重装站点。
# 用 `tr` + `cmp` 而不是 grep/awk 找 \r：三台机器上 grep 对 CR 的行为不一致（Git Bash 上它把每一行都算命中）。
echo "=== 5.5 站点根所有 .sh：去 CR + 补执行位 ==="
tot=0; cr=0; fixed=0; miss=""
for f in "$SITE"/*.sh; do
  [ -f "$f" ] || continue
  tot=$((tot + 1))
  if tr -d '\r' < "$f" > "$f.nocr" 2>/dev/null; then
    if cmp -s "$f" "$f.nocr"; then
      rm -f "$f.nocr"
    else
      mv "$f.nocr" "$f"
      cr=$((cr + 1))
      echo "    去 CR $(basename "$f")（Windows 上传带进来的 \\r；LF 那份等价，仓库里就是源）"
    fi
  else
    rm -f "$f.nocr"
    miss="$miss $(basename "$f")(读不了)"
    continue
  fi
  [ -x "$f" ] && continue
  if chmod +x "$f"; then fixed=$((fixed + 1)); echo "    +x $(basename "$f")"; else miss="$miss $(basename "$f")"; fi
done
echo "    站点根 .sh 共 $tot 个：去 CR $cr 个，补 x 位 $fixed 个（其余本来就干净又可执行）"
if [ "$tot" = 0 ]; then
  echo "    ⚠ $SITE 下没有任何 .sh —— 运维脚本没铺到站点根，crontab 那条会直接找不到文件"
elif [ -n "$miss" ]; then
  echo "    ⚠ 这几份没处理成：$miss（多半是属主不是你，自己看一下权限）"
fi
for f in alert_cron.sh shutdown_app.sh; do
  [ -f "$SITE/$f" ] || echo "    ⚠ 站点根缺 $f（本地仓库有；上传/装机没铺下来，靠它的那条 cron 或手工流程跑不了）"
done

# ---------- 4. 重载：Passenger 没有「启动」这一步，摸 restart.txt 即热重载 ----------
# 2.5 停过之后这里就是把应用带回来的地方：摸 restart.txt 让核心认定旧进程作废，
# 真正的「起」发生在下面第 7 步那一个 /api/health 请求上（按需 spawn，没人请求就一直没进程）。
echo "=== 6. 重载 Passenger（2.5 停过就靠这一步 + 第 7 步的第一个请求拉起）==="
mkdir -p "$SITE/tmp" "$SITE/public_python/tmp" "$DOCROOT/tmp"
touch "$SITE/tmp/restart.txt" "$SITE/public_python/tmp/restart.txt" "$DOCROOT/tmp/restart.txt"
if command -v devil >/dev/null 2>&1 && [ "$running" = 0 ]; then
  devil www restart "$DOMAIN" || echo "    devil www restart 失败（不影响 restart.txt 这条路）"
fi

# ---------- 5. 自检：只打不会发 Telegram 的接口 ----------
echo "=== 7. 冒烟 ==="
"$VENV_PY" -V
if [ -n "$sync_failed" ]; then echo "    ⚠ $sync_failed"; fi
if command -v curl >/dev/null 2>&1; then
  # 这一发就是 2.5 之后应用真正的「启动」请求：冷启动要把 btc/allocation 那几层 import 完，
  # 几秒到几十秒都正常，所以超时给到 90 秒——别拿一个还没起来的超时去判「应用没起来」。
  h="$(curl -s -m 90 "$URL/api/health" || true)"
  echo "    $(printf %s "$h" | grep -o '"mode": *"[a-z]*"' || echo '/api/health 没拿到 mode（应用没起来，看首页诊断文本）')"
  pid="$(printf %s "$h" | grep -o '"pid": *[0-9]*' | sed 's/[^0-9]//g' || true)"
  stale="$(printf %s "$h" | grep -o '"stale": *[a-z]*' | sed 's/.*: *//' || true)"
  cm="$(printf %s "$h" | grep -o '"code_mtime": *"[^"]*"' | sed 's/.*: *"//; s/"//' || true)"
  rss="$(printf %s "$h" | grep -o '"rss_mb": *[0-9.]*' | sed 's/[^0-9.]//g' || true)"
  echo "    pid=$pid  stale=$stale  rss_mb=$rss  code_mtime=$cm"
  echo "    站点记录 commit=$(cut -c1-8 "$SITE/.deployed_commit" 2>/dev/null || echo 无)  仓库 HEAD=$(git -C "$REPO_DIR" rev-parse --short HEAD 2>/dev/null || echo 未知)"
  case "$h" in
    *'"report"'*) echo "    路由已含 report（内存里是新代码）" ;;
    *) echo "    ⚠ 内存里的 routes 没有 report ⇒ 跑的还是旧 Python。HTML 每请求现读、.py 只在进程启动时 import，"
       echo "      所以光换文件不够，得让 Passenger 真重启：devil www restart $DOMAIN；重启后 pid 应该变" ;;
  esac
  echo "    config.ini 应 404：$(curl -s -o /dev/null -w '%{http_code}' "$URL/config.ini")"
  pg="$(curl -s "$URL/Index.html" || true)"
  echo "    两个报告按钮各应 1：crypto=$(printf %s "$pg" | grep -c 'id=.rpt-crypto.') us=$(printf %s "$pg" | grep -c 'id=.rpt-us.')"
  echo "    成功提示弹框（应 1）：$(printf %s "$pg" | grep -c 'id="toast"')"
  echo "    不带 kind 应 400（这条不跑脚本）：$(curl -s "$URL/api/allocation/report" | head -c 120)"
  echo "    report_quota：$(curl -s "$URL/api/allocation/health" | grep -oE 'report_quota.{0,150}' || echo '（无）')"
  echo "    ⚠ 冒烟刻意不打 kind=crypto / kind=us：两条都没有凭据门槛，curl 一下就是真跑脚本 = 真发一条 Telegram + 吃掉当天一次额度"
fi

echo "=== 8. 持仓报告的外部依赖（这两个按钮是服务端跑 cryptoTrader 的脚本）==="
for f in tests/runningOrder.py tests/runningStorcksOrder.py; do
  if [ -f "$CRYPTO_DIR/$f" ]; then echo "    在 $f"; else echo "    ⚠ 缺 $f —— 页面点这个按钮只会拿到 502「脚本不存在」"; fi
done
echo "    持仓数据：data/us_stocks CSV $(ls -1 "$CRYPTO_DIR/data/us_stocks" 2>/dev/null | grep -c csv || true) 个，data/exchange xlsx $(ls -1 "$CRYPTO_DIR/data/exchange" 2>/dev/null | grep -c xlsx || true) 个（都是 0 = 报表脚本读不到单，美股/加密报表会报「无数据」）"
echo "    $VENV_PY 能不能 import 报表脚本要的包：$( "$VENV_PY" -c 'import requests, openpyxl, ccxt; print("OK")' 2>&1 | tail -1 )"

echo
echo "✅ 完成。首页 $URL/ ；以后再改代码：本地 commit + push，然后服务器上 bash $SITE/deploy_app.sh 一条命令搞定；只想重启就 --reload"
