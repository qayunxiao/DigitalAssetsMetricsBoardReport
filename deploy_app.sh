#!/usr/bin/env bash
# serv00 侧部署／重载 DigitalAssetsMetricsBoardReport（Passenger WSGI 站点，没有守护进程可管）
#
#   bash deploy_app.sh              拉两个仓库 → 装到站点根 → 重载 Passenger → 冒烟
#   bash deploy_app.sh --reload     只重载 + 冒烟（代码没动，单纯想让进程换个新的）
#   bash deploy_app.sh --no-pull    不 pull，用仓库目录里现有的内容装机（GitHub 不可达时用）
#   bash deploy_app.sh --zip [包]   用上传的 damb-public-*.zip 装机，完全不碰 git（离线退路）
#   bash deploy_app.sh --force-data 连 data/report_quota.json 与 data/risk_history.csv 一起覆盖
#
# 装机来源跟他的 cryptoTrader 脚本一个路子：仓库常驻 `~/vevns/<仓库名>`，有 .git 就更新、没有就 clone，
# 然后把 `git ls-files` 列出来的跟踪文件铺到 Passenger 站点根（$SITE）。
#
# 为什么默认**不**覆盖 data 里那两个文件：它们是运行期状态。`data/report_quota.json` 在仓库里有记录
# （.gitignore 加得晚，已经跟踪上了），照抄一次部署就等于把服务器上「今天已点几次」清回旧值、白送几次点击。
#
# 关于「python 服务有没有启动」：Passenger 是按需拉起的，站点空闲时 `ps` 里一个进程都没有，
# 所以不能拿 ps 当判据。这里以面板 `devil www list` 的 running/stopped 为准，
# 再叠一个「站点根有没有 api/app.py」判断到底部署过没有。
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

MODE="git"; SYNC=1; FORCE_DATA=0; ZIP=""
while [ $# -gt 0 ]; do
  a="$1"; shift
  case "$a" in
    --reload)     MODE="reload" ;;
    --no-pull)    SYNC=0 ;;
    --force-data) FORCE_DATA=1 ;;
    --zip)        MODE="zip"; if [ $# -gt 0 ] && [ "${1#--}" = "$1" ]; then ZIP="$1"; shift; fi ;;
    --zip=*)      MODE="zip"; ZIP="${a#--zip=}" ;;
    -h|--help)    sed -n '2,26p' "$0"; exit 0 ;;
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
echo "=== 现状 === 已部署=$deployed  面板状态=$panel  站点根=$SITE  模式=$MODE"

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

# ---------- 3. 装机：把跟踪文件铺到站点根 ----------
cp /home/myaibtc/allocation.py /home/myaibtc/domains/myaibtc.serv00.net/api/allocation.py
cp /home/myaibtc/config.ini /home/myaibtc/domains/myaibtc.serv00.net/config.ini
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

[ -f "$SITE/api/app.py" ] || { echo "!! 站点根没有 api/app.py，装机没成功（包/仓库不对？）" >&2; exit 1; }

if [ "$MODE" != "reload" ]; then
  echo "=== 3. 清掉 docroot 里的首页（留着会被 nginx 直出，绕过服务端替换）==="
  rm -f "$DOCROOT/index.html" "$DOCROOT/Index.html"
  stray="$(find "$DOCROOT" -maxdepth 1 -name '*.html' 2>/dev/null || true)"
  if [ -n "$stray" ]; then echo "    ⚠ docroot 里还有别的 HTML，自己确认要不要留：$stray"; fi

  echo "=== 4. 入口多放两份（app root 认哪一层没有权威文档，_find_root() 会从任一份向上找到真根）==="
  cp -p "$SITE/passenger_wsgi.py" "$SITE/public_python/passenger_wsgi.py"
  cp -p "$SITE/passenger_wsgi.py" "$DOCROOT/passenger_wsgi.py"

  echo "=== 5. 补可执行位与运行目录（zip 不带 x 位；git checkout 带，但幂等没坏处）==="
  chmod +x "$SITE/start_app.sh" "$SITE/deploy_app.sh" 2>/dev/null || true
  mkdir -p "$SITE/data" "$SITE/tmp"
  touch "$SITE/.deployed"
fi

# ---------- 4. 重载：Passenger 没有「启动」这一步，摸 restart.txt 即热重载 ----------
echo "=== 6. 重载 Passenger ==="
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
  h="$(curl -s -m 30 "$URL/api/health" || true)"
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
