#!/usr/bin/env bash
# serv00 侧部署／重载 DigitalAssetsMetricsBoard（Passenger WSGI 站点，无守护进程可管）
#
#   bash deploy_app.sh            自动判断：没部署过 → 解压部署；已部署 → 只重载
#   bash deploy_app.sh --redeploy 强制重新解压（面板状态不动）
#
# 关于「python 服务是否启动」：Passenger 是**按需拉起**的，站点空闲时 `ps` 里一个进程都没有，
# 所以不能用 ps 当判据。这里以面板 `devil www list` 的 running/stopped 为准，
# 再叠一个「站点根有没有 api/app.py」来判断到底部署过没有。
# 本脚本只碰 $SITE，绝不碰 $HOME/private_python（那是另一套应用）。

set -euo pipefail

DOMAIN="${DOMAIN:-myaibtc.serv00.net}"          # 四个都能用环境变量覆盖，方便换域名或演练
SITE="${SITE:-$HOME/domains/$DOMAIN}"
DOCROOT="${DOCROOT:-$SITE/public_python/public}"
VENV_PY="${VENV_PY:-$HOME/vevns/web3/bin/python}"
URL="${URL:-http://$DOMAIN}"

cd "$SITE"

# ---------- 1. 现状：部署过吗？面板里在跑吗？ ----------
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
echo "=== 现状 === 已部署=$deployed  面板状态=$panel  站点根=$SITE"

# ---------- 2. 要不要解压：未部署 / --redeploy / 有更新的包 ----------
# 比较基准用 .deployed（解完才 touch 的标记）：包文件的 mtime 是「上传时间」，而解压出来的文件
# 保留的是打包时的 mtime，直接拿 passenger_wsgi.py 比会每次都判定「包更新」而重解一遍。
newest="$(ls -1t "$SITE"/damb-public-*.zip "$HOME"/damb-public-*.zip 2>/dev/null | head -1 || true)"
marker="$SITE/.deployed"
[ -f "$marker" ] || marker="$SITE/passenger_wsgi.py"
need=0
if [ "$deployed" = 0 ] || [ "${1:-}" = "--redeploy" ]; then
  need=1
elif [ -n "$newest" ] && [ "$newest" -nt "$marker" ]; then
  echo "    检测到比上次部署更新的包，一并更新"
  need=1
fi

if [ "$need" = 1 ]; then
  if [ -z "$newest" ]; then
    echo "!! 站点根或 \$HOME 里找不到 damb-public-*.zip，先上传再跑这个脚本" >&2
    exit 1
  fi
  echo "=== 1. 解压部署：$newest → $SITE ==="
  if [ -f "$SITE/config.ini" ]; then                       # config.ini 在包里，会被覆盖，先留一份
    cp -p "$SITE/config.ini" "$SITE/config.ini.bak.$(date +%Y%m%d-%H%M%S)"
  fi
  if tar -xf "$newest" 2>/dev/null; then
    echo "    tar（bsdtar 原生读 zip）OK"
  else
    echo "    tar 解不动，改用 python -m zipfile"
    "$VENV_PY" -m zipfile -e "$newest" "$SITE/"
  fi
  [ -f "$SITE/api/app.py" ] || { echo "!! 解压后站点根仍没有 api/app.py，包可能不对" >&2; exit 1; }

  echo "=== 2. 清掉 docroot 里的首页（留着会被 nginx 直出，绕过服务端替换）==="
  rm -f "$DOCROOT/index.html" "$DOCROOT/Index.html"
  stray="$(find "$DOCROOT" -maxdepth 1 -name '*.html' 2>/dev/null || true)"
  if [ -n "$stray" ]; then echo "    ⚠ docroot 里还有别的 HTML，自己确认要不要留：$stray"; fi

  echo "=== 3. 入口多放两份（app root 认哪一层没有权威文档，_find_root() 会从任一份向上找到真根）==="
  cp -p "$SITE/passenger_wsgi.py" "$SITE/public_python/passenger_wsgi.py"
  cp -p "$SITE/passenger_wsgi.py" "$DOCROOT/passenger_wsgi.py"

  echo "=== 4. zip 不带可执行位；补上 x 位与运行目录 ==="
  chmod +x "$SITE/start_app.sh"
  mkdir -p "$SITE/data" "$SITE/tmp"
  touch "$SITE/.deployed"
else
  echo "=== 跳过解压（代码已在位，包也不比它新）==="
fi

# ---------- 3. 重载：Passenger 没有「启动」这一步，摸 restart.txt 即热重载 ----------
echo "=== 5. 重载 Passenger ==="
mkdir -p "$SITE/tmp" "$SITE/public_python/tmp" "$DOCROOT/tmp"
touch "$SITE/tmp/restart.txt" "$SITE/public_python/tmp/restart.txt" "$DOCROOT/tmp/restart.txt"
if command -v devil >/dev/null 2>&1 && [ "$running" = 0 ]; then
  devil www restart "$DOMAIN" || echo "    devil www restart 失败（不影响 restart.txt 这条路）"
fi

# ---------- 4. 自检：只打不会发 Telegram 的接口 ----------
echo "=== 6. 冒烟 ==="
"$VENV_PY" -V
if command -v curl >/dev/null 2>&1; then
  h="$(curl -s -m 30 "$URL/api/health" || true)"
  echo "    $(printf %s "$h" | grep -o '"mode": *"[a-z]*"' || echo '/api/health 没拿到 mode（应用没起来，看首页诊断文本）')"
  printf %s "$h" | grep -o '"pid": *[0-9]*\|"stale": *[a-z]*\|"code_mtime": *"[^"]*"' | tr -d '\n' | sed 's/"pid"/  pid/; s/"stale"/  stale; /; s/"code_mtime"/  code_mtime/' || true
  echo
  case "$h" in
    *'"report"'*) echo "    路由已含 report（内存里是新代码）" ;;
    *) echo "    ⚠ 内存里的 routes 没有 report ⇒ 跑的还是旧 Python。HTML 每请求现读、.py 只在进程启动时 import，"
       echo "      所以光传包不够，得让 Passenger 真重启：devil www restart $DOMAIN；重启后 pid 应该变" ;;
  esac
  echo "    config.ini 应 404：$(curl -s -o /dev/null -w '%{http_code}' "$URL/config.ini")"
  pg="$(curl -s "$URL/Index.html" || true)"
  echo "    两个报告按钮各应 1：crypto=$(printf %s "$pg" | grep -c 'id=.rpt-crypto.') us=$(printf %s "$pg" | grep -c 'id=.rpt-us.')"
  echo "    不带 kind 应 400（这条不跑脚本）：$(curl -s "$URL/api/allocation/report" | head -c 120)"
  echo "    report_quota：$(curl -s "$URL/api/allocation/health" | grep -o 'report_quota.\{0,150\}' || echo '（无）')"
  echo "    ⚠ 冒烟刻意不打 kind=crypto / kind=us：两条都没有凭据门槛，curl 一下就是真跑脚本 = 真发一条 Telegram + 吃掉当天一次额度"
fi

echo
echo "✅ 完成。首页 $URL/ ；改了代码要再生效只需 touch $SITE/tmp/restart.txt"
