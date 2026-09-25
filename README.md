# DigitalAssetsMetricsBoard · 数字资产指标看板

四个本地实时监控面板 + 一个主页导航，由**同一个零依赖 Python 服务**托管：

| 页面 | 地址 | 内容 |
|---|---|---|
| 主页 | `http://127.0.0.1:8888/Index.html` | 四模块健康探针、数据链路总览、顶栏右侧「BTC监控」入口 |
| BTC 指标监控 | `…/staic/btc.html` | 恐慌贪婪指数 + 12 项 BTC 日线指标（AHR999 / CBBI / CVDD / EMA / EMA_new / KDJ / LookIntoBitcoin / MACD / MVRV / NUPL / SOPR Z-Score / 2年MA乘数通道），各张卡各取各的数 |
| 全球宏观流动性 | `…/staic/Liquidity.html` | WALCL / TGA / ON RRP / SOFR / IORB / US10Y / BTC / 核心CPI / PPI / 失业率（萨姆规则）/ 零售 等 13 项 |
| 美股崩盘风险监测 | `…/staic/USStockCrashMonitor.html` | VOO/QQQ 六因子评分（巴菲特指标、席勒PE、HY OAS、2Y-10Y、技术面乖离、恐慌贪婪指数），当日评分累积到 `data/risk_history.csv` |
| 全球优质资产配置 | `…/staic/GlobalQualityAssetAllocation.html` | 8 个全球市场 + TLT 观察位的「贪婪恐慌深度」十年分位模型、2Y/10Y 利差、DGS3/DGS10 十年分位 |

- 代码目录：`D:\Qorder_ws\DigitalAssetsMetricsBoardReport`
- 定位：**本地决策工具**。本机版取数依赖本机代理与 `127.0.0.1` 绑定；2026-09-22 起另有一个公网镜像（serv00 / Passenger WSGI，第 7.2 节），它按 `PUBLIC=1` 收敛掉持仓报告与非前端文件，边界见第 9 节。
- 技术栈：Python 3.11+ 标准库 HTTP 服务（`ccxt` 仅用于 BTC 多所现价，缺失时自动降级；BTC 指标页不用 ccxt，自己的 K 线全部走公开 REST）+ 单文件原生 HTML/JS（无框架、内联 SVG、`staic/common.css|js` 五页共享）。

---

## 1. 为什么需要本地服务

FRED、纽约联储、美国财政部等官方节点**不返回 CORS 头**，浏览器无法直取；代理能解决网络可达，解决不了 CORS。因此必须由本项目同源服务做中转：

```
浏览器页面 ──/api/*（同源，绕 CORS）──► 装配层 api/app.py + 公共层 api/core.py（本机 main.py 监听 127.0.0.1:8888／公网 passenger_wsgi.py 由 Passenger 调起）
                                        │  ├─ gov_lock 串行队列 ──代理──► FRED / 财政部 / Yahoo / CNBC / CNN / multpl / gurufocus
                                        │  ├─ mkt_lock 串行队列 ──代理──► ccxt（OKX/Kraken/Coinbase…，binance 451 / bybit 403 属预期剔除）
                                        │  └─ api/btc.py：不用上面两条队列，自己按「主机」各一把锁 + 线程池并发（各项分属 6 个主机，共用一把锁会让整页等串行）
                                        └─ TTL 缓存 + single-flight；上游失败时回退旧值并让页面标注「○ 快照」
```

**判级与评分全部在页面代码里按公开阈值实时生成**，服务端只回原始序列——不改代码即可复核每一级红黄绿。
唯一例外是 **BTC 指标页**：那一组指标的阈值是从 `api/Crypto/handle_*.py`（cryptoTrader 同名文件的仓库内只读副本）逐条移植过来的——只有 looknode 那条「2年MA乘数通道」例外，cryptoTrader 里没有它，判据照抄上游页面自己的「指标描述」。判级就写在 `api/btc.py` 的对应函数里、紧跟口径出处注释，页面只渲染 `verdict/tone`。放在服务端是为了让「一段判级代码」对上「一段上游原始序列」，不至于同一套阈值在 Python 和 JS 里各存一份、改一处漏一处；复核照样翻开那个文件，每张卡的规则也印在页面「口径与阈值」块。

## 2. 目录结构

```
DigitalAssetsMetricsBoard/
├── Index.html                 主页（模块健康探针、持仓报告按钮、顶栏右侧「BTC监控」入口）
├── main.py                    本机入口：起 127.0.0.1 单一服务
├── passenger_wsgi.py          公网入口（serv00/Passenger 用面板指定的解释器 import 它），见第 7 节
├── config.ini                 运行配置（代理/端口/日志/页面开关/公网模式/落库），见第 4 节
├── indicator.ini              出处项目（cryptoTrader）的配置快照 + 凭据副本；**2026-09-24 起它的 `[html_alert_top]`/`[html_alert_bottom]` 两段是运行时配置**——页面指标日报的阈值与每天时刻都在那里，见 4.1
├── local.ini                  可选：同目录、已 gitignore，`api/db.py` 读它优先于 `config.ini`（放口令用），没有这文件也照常跑
├── start_app.bat              Windows 一键启动（= python main.py --open）
├── start_app.sh               Linux／FreeBSD 启动器（本机模式用这个；优先它自己的 venv 解释器、不沿用 Windows 代理）
├── deploy_app.sh              serv00 公网侧部署／重载脚本（判断是否已部署 → 解压或只重载，见 7.2）
├── staic/                     前端（目录名就是 "staic"，勿改）
│   ├── common.css / common.js 五页共享样式、导航、探针、自动刷新工具（色板在 `common.css` 顶部那两块：`:root` 深、`html[data-theme=light]` 亮；顶栏「☀ 亮色 / ☾ 深色」按钮切换，状态存 `localStorage['board-theme']`，默认深色）
│   └── btc.html / Liquidity.html / USStockCrashMonitor.html / GlobalQualityAssetAllocation.html
├── api/
│   ├── core.py                公共层：config 应用、日志、TTL 缓存、串行队列、remote()、dispatch()/wsgi_app()、路由与静态托管
│   ├── app.py                 装配层：两个入口共用的模块注册表（本机版与公网版注册同一张路由表）
│   ├── btc.py                 /api/btc/*（BTC 指标页全部指标取数 + 判级，口径多数抄自 Crypto/handle_*.py）
│   ├── Crypto/                cryptoTrader `api_list/handle_*.py` 的仓库内只读副本（2026-09-23 用户抄入，逐字节一致）——口径对照用，不参与 import
│   ├── liquidity.py           /api/liquidity/*   ├── crash.py      /api/crash/*
│   ├── allocation.py          /api/allocation/*（资产配置页的取数全在这一个文件里，没有同名目录）
│   ├── db.py                  可选落库层（MySQL 旁路 + `/api/db/health`）：建表、写入、状态自检
│   ├── notify.py              Telegram 推送出口（`QA` / `ALVIN` 两个机器人，令牌读 `config.ini` 的 `[TG]`，见第 4 节；**没有任何 HTTP 接口调它**，BTC 极值播报走 `--btc`、三张卡的指标日报走 `--html-alert` 命令行，阈值见 4.1）
│   ├── Liquidity/             流动性模块详档（README.md 接口契约/阈值表、Qoder.md 审计纪律）与 _legacy/ 归档
│   └── USStockCrashMonitor/   原 Streamlit 版归档（_legacy/，README.md 为旧版说明）
├── utils/                     cryptoTrader `utils/` 的仓库内只读副本（含 `operationMysql.py`），对照用、不参与 import，见 7.3
├── sql/board_schema.sql       落库表结构（6 张表），`python api/db.py --init` 就是逐句执行它
├── INTODB.md                  落库地图：哪些指标真入库、哪些只存元数据、哪些完全不落库、哪些走日缓存
├── data/risk_history.csv      崩盘页每日评分累积（同日覆盖）
├── data/report_quota.json     两个持仓报告的当日点击计数（crypto/us 各记各的，跨天自动作废，限次见 [report]）
├── data/notify_state.json     TG 播报的去重与每日限额记录（`api/notify.py`，见第 4 节；只留最近一条，删掉等于「今天没发过」）
├── data/notify_html_state.json 指标日报「今天已经发过」的那一本账（见 4.1；删掉等于「今天还没发」，当天会再打一次上游、多发一条）
├── data/daycache/             磁盘日缓存：每个缓存键一份「今天取到的原始结果」（见 7.4，可整目录删除）
├── logs/board_server.log      午夜轮转，保留 14 天
└── Qoder.md                   给 agent 的项目约定（审计提示词、硬性纪律、边界）
```

## 3. 启动

### 3.1 一次性前置

1. Python **3.11+**（标准库即可运行；`pip install ccxt` 可选，仅 BTC 实时现价中位数需要，缺失时相关项自动标为取数失败）。
2. 本机 HTTP/HTTPS 代理可用（**仅 Windows**：默认 `127.0.0.1:3067`，在 `config.ini` 改；FreeBSD/Linux 上这一段被代码跳过，要用代理得显式传 `HTTPS_PROXY=...`）。无代理时上游基本不可达，页面会整体退回「○ 快照」标注，不会把滞后值冒充实时值。

### 3.2 启动 / 停止

| 方式 | 操作 |
|---|---|
| 最快（Windows 10） | 双击 `start_app.bat` —— 起服务并自动打开主页 |
| 最快（Linux／FreeBSD，含 serv00） | `sh start_app.sh`（先 `chmod +x start_app.sh` 就能 `./start_app.sh`）—— 前台运行、Ctrl+C 停止；解释器优先用 `/home/myaibtc/vevns/web3/bin/python`，存在就用它，否则退回 `python3`→`python`（`PYTHON=/path/to/python sh start_app.sh` 显式指定）；**不会**沿用 `config.ini` 的 Windows 代理。`--open` 也支持，但服务器上没浏览器会静默失败 |
| 命令行 | `python main.py`（加 `--open` 自动开主页） |
| PyCharm | 直接运行 `main.py`（入口已把 `api/` 加入 `sys.path`） |
| 停止 | Ctrl+C；或结束对应 python 进程（端口 8888） |

启动时 `liquidity.warm()` 会预热 ccxt（每家交易所 `load_markets` 实测约 27 秒），首屏不空等；日志 `logs/board_server.log` 里每个上游请求都有耗时/字节行，判断「实时还是快照」以日志为准，不靠印象。

## 4. 配置（config.ini 是唯一事实源）

优先级：**同名环境变量 > `config.ini` > 代码默认**。临时改一次不必动文件：`set HTTPS_PROXY=http://127.0.0.1:7890 && python main.py`。
本节这个「唯一」有一处例外：`--html-alert` 那三张卡的阈值与每天时刻住在 `indicator.ini` 的 `[html_alert_top]` 与 `[html_alert_bottom]`（优先级同一套），见 4.1——2026-09-24 用户明示要「改配置不改代码」；其余判级数值仍在代码里。

| 节 | 键 | 环境变量 | 当前值 / 说明 |
|---|---|---|---|
| `[proxy]` | `http` / `https` | `HTTP_PROXY` / `HTTPS_PROXY` | `http://127.0.0.1:3067`；留空 = 不走代理。**只在 Windows 生效**：`apply_config()` 在非 `nt` 系统直接跳过本段（同一份文件传到 FreeBSD/Linux 服务器上并不存在那个出口），Unix 要用代理必须显式给环境变量 |
| `[server]` | `port` | `PORT` | `8888`；监听地址固定 `127.0.0.1`，**故意不做成配置项**（只对本机版 `main.py` 有意义，公网版没有监听端口这回事）。页面与 `/api/*` 同源共用这一个端口，**没有第二个「前端端口」**：浏览器经 15888 访问是你自己的反向代理／端口映射（15888 → 127.0.0.1:8888）在转发，本项目不参与、也不因它放开绑定 |
| `[server]` | `public` | `PUBLIC` | 留空 = 本机版。`1` = 公网版（静态只放 html/css/js/svg/ico、不走本机代理）。**持仓报告在两个版本里同一口径**（按钮都显示、点了就执行，2026-09-22 改过两次后的最终结论），不再有「公网版整段不出现」那回事。公网版由 `passenger_wsgi.py` 在导入核心层前写死，服务器上不必改本文件 |
| `[log]` | `dir` / `level` | `LOG_DIR` / `LOG_LEVEL` | `logs`（相对项目根）/ `INFO`（DEBUG 含缓存命中明细，每日轮转留 14 天） |
| `[page]` | `show_fix` | `SHOW_FIX` | `1`；控制页面底部「修订记录」块，由服务端替换 HTML 标记 `{{SHOW_FIX}}` 实现，一次刷新即生效 |
| `[report]` | `python` / `crypto_script` / `us_script` / `daily_limit` / `us_daily_limit` | `REPORT_PY`（两个 kind 共用解释器）/ `REPORT_CRYPTO_SCRIPT` / `REPORT_US_SCRIPT` / `REPORT_DAILY_LIMIT` / `REPORT_US_DAILY_LIMIT` | 覆盖两个报告脚本的路径（留空 = 按 OS 用内置默认）与各自每天可点次数（默认加密 `3`、美股 `2`）。本机 `python` 已填 cryptoTrader 自己的 venv（`E:/UserTools/py311_envs/WEB3/Scripts/python.exe`，含 openpyxl/pandas/requests；系统 python 缺 openpyxl，用它跑加密报表只会得到「无数据」） |
| `[cache]` | `day` / `dir` | `CACHE_DAY` / `CACHE_DIR` | 磁盘日缓存（`api/core.py` 的 `cached()`）。`day=0` 整层关掉 = 回到「缓存只在进程内存里」的老行为；`dir` 相对项目根（`data/daycache`，已 gitignore，删掉无后果）。为什么要有这层见 7.4 |
| `[mysql]` | `ENABLE` / `HOST` / `PORT` / `USER` / `PASSWD` / `DADABASES` / `CHARSET` / `STORE_BTC` / `STORE_SERIES` / `STORE_RISK` / `STORE_REPORT` | `MYSQL_HOST` / `MYSQL_PORT` / `MYSQL_USER` / `MYSQL_PASSWD` / `MYSQL_DATABASE` / `MYSQL_CHARSET` / `MYSQL_ENABLE` / `MYSQL_STORE_BTC` / `MYSQL_STORE_SERIES` / `MYSQL_STORE_RISK` / `MYSQL_STORE_REPORT` | **整段可选的落库层**，见 7.3。`ENABLE=0` 或 `HOST/USER/DADABASES/PASSWD` 任缺其一 = 完全不连库，页面照常有数。键名 `DADABASES` 是出处项目（cryptoTrader）的原始拼写，保留兼容。四个 `STORE_*` 分别关掉「指标日读数 / 历史序列 / 崩盘评分 / 报表留痕」，都只在 `ENABLE=1` 时有效 |
| `[dingding]` | `SECRET` / `ACCESS_TOKEN` / `SECRET_MYSELF` / `ACCESS_TOKEN_MYSELF` / `SECRET_QA` / `ACCESS_TOKEN_QA` | `DD_SECRET` / `DD_ACCESS_TOKEN` / `DD_SECRET_MYSELF` / `DD_ACCESS_TOKEN_MYSELF` / `DD_SECRET_QA` / `DD_ACCESS_TOKEN_QA` | 三组钉钉机器人（默认 / 我自己 / QA）的加签密钥与 webhook token。2026-09-24 从 `indicator.ini` 挪进来，**当前只有读取路径，没有代码真发钉钉**（保留出处项目的键名与拼写，接上时不必再搬一次） |
| `[TG]` | `BOT_TOKEN_QA` / `CHAT_ID_QA` / `BOT_TOKEN_ALVIN` / `CHAT_ID_ALVIN` | `TG_BOT_TOKEN_QA` / `TG_CHAT_ID_QA` / `TG_BOT_TOKEN_ALVIN` / `TG_CHAT_ID_ALVIN` | 两个 Telegram 机器人，`api/notify.py` 读的就是这一段（`QA` / `ALVIN`）。⚠ **明文口令/令牌，见下面那段**：这批值此刻在公开的 `origin/main` 里，也随 `deploy_app.sh` 上到公网机器 |
| `[notify]` | `tg_bot` / `daily_limit` | `NOTIFY_TG_BOT` / `NOTIFY_DAILY_LIMIT` | BTC 极值播报（`api/notify.py --btc`）的两个运行参数：默认发给哪个机器人（`QA`）、每天最多几条（`1`）。**看哪几张卡、什么档算触发不在这里**——那是判级口径，写在 `api/notify.py` 的 `BTC_WATCH` / `HOT_TONES`，改它要提交代码。状态记在 `data/notify_state.json`（已 gitignore，删掉等于「今天还没发过」） |

新增配置项需同时登记 `api/core.py` 的 `CONFIG_ENV`、`config.ini` 注释与本表。**例外：`[mysql]` 走 `api/db.py` 自己的解析（环境变量 > `local.ini` > `config.ini`），不进 `CONFIG_ENV`**——它要在缺 `pymysql` 时也照常启动，不能让 core 去 import 一个第三方包。

**Telegram 推送怎么用（`api/notify.py`）**：这是个独立脚本，**没有挂到任何 HTTP 路由上**，页面上按不到它，所以不存在「刷新页面就把消息发出去」这种事故。

```bash
python api/notify.py                                   # 只自检：两个机器人各问一次 getMe（只读，问 bot 自己是谁），不发任何消息
python api/notify.py --text "测试正文"                  # 同上，外加把这条正文打印出来预览，仍不发
python api/notify.py --send --bot QA --text "测试正文"   # 真发一条到 QA 那个群（--send 必须搭配 --bot，否则拒绝并退码 2）
python api/notify.py --status                           # 纯本地：两本当天记录（--btc 极值播报 + 指标日报）+ 今日额度 + 两段的生效阈值，不打网络也不打库
python api/notify.py --btc                              # BTC 极值播报：取数 → 挑卡 → 组正文 → 报会不会被闸门挡；**不发**
python api/notify.py --btc --send                       # 真发（机器人取 `--bot`，没给就用 `[notify] tg_bot`）
python api/notify.py --btc --send --force               # 连过两道闸门（同一业务日已发过时手工补发）
python api/notify.py --html-alert                       # 页面指标日报：取数 → 两段各自判定 → 并成一张表，**顺带报「真到 cron 那一刻会不会被闸门挡」**；不发、不记账
python api/notify.py --html-alert --send                # 真发一条（cron 挂这条；时刻与阈值见 4.1）
python api/notify.py --html-alert --send --force        # 跳过「不早于 ALERT_AT」和「一个日历日只发一条」（手工补发用）
```

**`--btc` 的触发口径**（2026-09-24 定，策略常量在 `api/notify.py` 里，运行参数在 `[notify]`）：

| 环节 | 口径 |
|---|---|
| 看哪几张卡 | `BTC_WATCH = two_year_multiply / fear / ahr999 / cbbi` —— 只有这四张有明确的极值档，其余九张的 `tone` 不代表「极端」 |
| 什么算触发 | 卡片自己算好的 `tone ∈ {green, red}`（绿=底部档、红=顶部档）。**播报层一律不重算阈值**，判级改了就跟着改，这里不存第二份口径 |
| 一条 vs 每张 | 一次事件 = 一条消息，命中几张列几张；正文全用卡片现成字段（`name`/`value`+`dp`/`verdict`/`asof`/`src`），末尾一句交代未触发与取数失败 |
| 没有命中 | **什么都不发**（宁可不发，也不把中性区刷成日常播报） |
| 闸门一 | 同一 `(机器人, 业务日)` 只发一条。业务日 = 命中项里最新的 `asof`，**不是跑脚本那天**——上游可能整天不更新，用当天当键会让同一条极值在群里刷成一串 |
| 闸门二 | `[notify] daily_limit`（默认 1）按日历日计数 |
| 记账时机 | 只在真发成功之后写 `data/notify_state.json`；失败不计数（一次网络抖动不该烧掉当天额度）。预览跑一百遍也不扣 |

发信走 `core.PROXY`（本机），公网机器上 `[proxy]` 被 `win_only` 跳过所以直连。正文不设 `parse_mode`（Markdown/HTML 里一个裸 `_` 或 `<` 就整条 400），超 4096 字按 Telegram 上限截断。**没有定时器**：要每天自动播，自己挂 cron／计划任务跑 `python api/notify.py --btc --send`（盯那三张卡的定时版是 `--html-alert --send`，见 4.1）—— 服务代码里没有一行会自己发（见第 9 节）。`--btc` 走的就是 `btc.summary()`，所以顺带把 13 项读数 UPSERT 进库（7.3），与页面刷新同一语义；`--status` 才是完全不碰外部的自检。

**凭据的去处**：这条规矩在 2026-09-24 被用户**明示改口**过，现在的边界是「**该段口令可以入库，但任何接口/日志/聊天都不许回显**」。原先写的是「运行参数可以入库，口令不行」，因为 `config.ini` 是 git 跟踪文件、`deploy_app.sh` 又按 `git ls-files` 打上传包，写进去等于把口令发到公开仓库和公网机器上——这个后果今天**已经成立**：`[dingding]` `[TG]` 两段明文此刻在公开的 `origin/main` 里，也上了 serv00 那台机器。用户明知这一点仍要求这么做（原话：「确认要把明文密钥写进 config.ini 并提交到公开仓库，之后我BTC 相关指标需要发TG 需要使用到这样的功能」），所以要轮换/收回是他的动作，**后来的 agent 别默默把它改回去、也别不吭声地再往里加新凭据**。`[mysql] PASSWD` 那段的**书面**规矩仍是「优先 `local.ini` 或 `set MYSQL_PASSWD=…`，提交前先 `PASSWD =` 留空」；2026-09-23 曾把整段挪进 `local.ini`，同日按用户要求挪回 `config.ini` 并保留两级覆盖。**但 2026-09-24 核对：这段口令已经在公开的 `origin/main` 里了**（`git show origin/main:config.ini` 能查到那行 `PASSWD`，来自 `63b9101`），所以上一句「提交前清空」对历史已经无效——要么清空后重新提交、要么视同已泄露去轮换，这是他的动作，我们只提示不代执行。`COINGLASS_KEY` 从一开始就是纯环境变量（故意不进 `CONFIG_ENV`，也不写任何 ini），这条没变。另核对一笔：`indicator.ini`（出处项目的凭据快照）**并非**「已 gitignore 所以不在仓库里」——它早在 `63b9101` 就被跟踪，gitignore 只挡未跟踪文件，那批 CoinGlass/CryptoQuant Key、钉钉与 TG 令牌、TradingView 口令一直在远端历史里；要挡住得先 `git rm --cached indicator.ini` 再提交，且必须轮换。

### 4.1 页面指标日报（`--html-alert`，阈值住在 `indicator.ini` 的 `[html_alert_top]` 与 `[html_alert_bottom]`）

2026-09-24 用户要的功能：**每天定点盯看板那三张卡**，并且「这几档要能改配置不改代码」。
同日第二次加口径：拆成顶部/底部两段各自判、各自发。**同日第三次改口径 = 现在生效的这套**：
`[html_alert_top]`（「可能顶部」，阈值往高了判）与 `[html_alert_bottom]`（「可能底部」，往低了判）**并成一条日报**——
**不论触没触发，每天固定发一条**，正文是一张**等宽表格**：一行一张卡，列为
「指标 / 当前值 / 数据日期 / 可能顶部 / 可能底部」（后两列 = 该段条件 + `✓`/`✗`），末尾一行缺口；
头条每段各一行「命中几/几 · 有数几项 · 要求几项 → 触发/未触发」。
于是 `ALERT_HITS` **只决定那句结论写什么，不再是发不发的开关**，记账也跟着并回**一本**。
这是全站**唯一**一处把判级数值放进 ini 的地方（其余口径都在代码常量里，理由见 `Qoder.md` 第 2 节），
所以引用下面这几个数之前**先重读那份文件**——他会手改。

| 键（env 名 = `HTML_ALERT_TOP_…` / `HTML_ALERT_BOTTOM_…`） | 顶部段现值 | 底部段现值 | 含义 |
|---|---|---|---|
| `ALERT_AT` | `13:28` | `13:28` | 每天的时刻，`hh:mm`（24 小时制，按**跑脚本那台机器的本地时区**）。语义是「不早于此时刻」：到点后第一次真评，08:10 那分钟机器没起来则 08:11 之后补。留空 = 不设时刻。env 名是 `HTML_ALERT_TOP_AT` / `HTML_ALERT_BOTTOM_AT`（时刻这条不带键名）。**走 `alert_cron.sh` 时这一档被脚本用空的这两个变量覆盖掉**，时刻以 crontab 为准 |
| `ALERT_HITS` | `1` | `1` | 该段算「触发」需要同时命中几项，**只写进正文那句结论、不决定发不发**。`1`=任一、`2`=任意两项、`3`=三项全中；留空 = 有几项算几项全中（停用一项就按两项算）。代码默认两段都是 `3`，现值是他手改的 |
| `AHR999_MAX` | `0.67` | `0.4` | 项① AHR999 定投指数：卡片头条值 `<=` 此数即满足（两段同方向，只是数值不同）。留空或写坏 = 停用本项 |
| `FEAR_GREED_MIN` | `70` | — | 项②（顶部）恐慌贪婪指数：头条值 `>=` 此数即满足。留空或写坏 = 停用本项 |
| `FEAR_GREED_MAX` | — | `20` | 项②（底部）同一个卡，方向反过来：头条值 `<=` 此数即满足。**两段的键名不同不是笔误**——一个盯贪婪一个盯恐慌 |
| `TWM_CLOSE_ABOVE_SUPPORT` | `1` | — | 项③（顶部）2年MA乘数通道：**日线收盘** > 同一根上的支撑 730MA 即满足。没有数值阈值，`1`=启用、`0` 或留空=停用 |
| `TWM_CLOSE_BELOW_SUPPORT` | — | `0`（当前停用） | 项③（底部）同一根、方向反过来：收盘 < 支撑 730MA |

- **数从哪来**：`btc.summary()`，也就是 `staic/btc.html` 那一份，播报层**不重算任何指标**，只比大小。
  项③刻意不用首页那个多所现价中位数——收盘取通道卡 `bands` 最后一根的 `px`（Yahoo `BTC-USD` 日线），
  与同一根的 `lo` 比，两边日期必然一致；末行缺收盘就退到最近一根齐的，整列都不齐就是缺数据，**不外推**。
  一次 tick 只调 `btc.summary()` **一次**，两列判定用同一批数（分两段各取一遍等于把上游打两遍）。
- **缺数怎么办**：取不到数的项记为「缺口」，既不算满足**也照样占该段 `ALERT_HITS` 的额**（写着 3 就要三项都成立）。
  代价说清楚：并成日报之后缺数不再会让整条链哑掉——**当天照发**，那一格是 `—`、末尾单列进「缺口」，只是那段的结论变成「未触发」。
  「停用的项」（值为空/写坏）不占额，表格里两类都会列出来（`✓`/`✗`/`—`/`·`），列全三段数才读得出当时是什么状态。
- **两道闸门都走在取数前面**：① 不早于各段 `ALERT_AT`（两段各写时刻时取**较晚**那个，早段没到点整条都不发）；
  ② 日报**一个日历日只发一条**——这是「每天必发」之后唯一的防刷屏闸门，所以 cron 每分钟拉起一次，一天也只打一次上游。
  记录只有**一本**：`data/notify_html_state.json`（已 gitignore，与 `--btc` 那份 `data/notify_state.json` 各记各的、
  互不消耗；两段共用一本，因为它们本来就在同一条消息里。拆两段那一阵的 `..._top_state.json` / `..._bottom_state.json`
  已经没人读了，留在服务器上无害）。**预览（不带 `--send`）从不记账**，也照样能看数：
  看一眼配置不该把当天该发的日报哑掉。真发失败同样不记，下一分钟的 cron 自己再试；
  只有「各段阈值全被停用」这种发了也没得比的情况会记一笔「没发」，为的是别让每分钟的 cron 反复打上游。
  `alert_cron.sh` 从 2026-09-24 起**自己完全不判时刻**（原来那个 `ALERT_TIME` 开关已经删掉），时刻来源只剩 crontab；
  闸门②保留，因为它防的是**重复推送**不是早跑。
- **每次执行都留一行完整命令**：`alert_cron.sh` 把真正调用那一行原样打进日志头、也回显到 stdout——
  `HTML_ALERT_TOP_AT= … PYTHONPATH=<根>:<根>/api "<venv>/bin/python" <根>/api/notify.py --html-alert --send`，
  事后不必读脚本猜解释器和参数，ssh 里照抄就能手工复跑（那几个变量在脚本里是 `export` 进环境的，所以带前缀的打印行与实际调用逐字等价）。
- **日志里另有一行对照**：表后面跟着 `对照 [top] 键: 查询值 (设置阈值) 标记 ; …`（`alert_compare()`），顶部底部各一行，
  进 `logs/notify_cron.log`，**不在 TG 正文里**——那张表要等宽对齐，流水串塞进去会把代码块撑歪。
  跑 `--html-alert` 这条命令行时记得先 `set PYTHONIOENCODING=utf-8`（同 `alert_cron.sh` 里那两行），
  否则 Windows 的 GBK 控制台会在 `✓` 上当场 `UnicodeEncodeError`。
- **只出一段的条件列**：`python api/notify.py --html-alert-top` / `--html-alert-bottom`（各自也能加 `--send`）；
  不带段名就是两段都并进来。当前值那几列照旧，**账本也是共用的**——单独发过一段，当天那条完整日报就一并算发过了。
- **收件人**：`[notify] tg_bot`（`--bot` 覆盖）。**这条路径不消耗 `[notify] daily_limit`**（那条只管 `--btc`），闸门②自己封顶。
- **怎么挂**：走根目录的 `alert_cron.sh`（编码、日志、`PYTHONPATH` 三件事都靠它兜），crontab 只写绝对路径：
  `10,40 8 * * *   /usr/home/myaibtc/domains/myaibtc.serv00.net/alert_cron.sh`。
  两个时刻是「首发 + 兜底补发」，不是判两次——闸门②保证**一天最多一条日报**。
  **两列判定互相矛盾是常态不是异常**：2026-09-24 实测就是顶部「AHR999 0.569 ✓ + 恐慌 71 ✓」中 2/3、
  底部中 0/2（底部那两项一个要恐慌 <=20、一个要收盘 < 支撑，而当天恐慌正在贪婪区）——
  `ALERT_HITS = 1` 配在顶部段等于「AHR999 一个偏便宜的数就能点亮可能顶部」，现在它就摆在同一行的两列里，谁中谁没中一眼看得见。
  想要真共振就把那段的 `ALERT_HITS` 调到 2 或 3，别改判定代码。
  时刻按服务器本地时区解释——**别猜偏移**，先在服务器上 `date`、或看主页「浏览器 − 服务端」那一格对一下再定。
- 与 `--btc` 一样，这条链也走 `btc.summary()`，所以顺带把 13 项读数 UPSERT 进库（见 7.3）。
- **表格能对齐的唯一前提是等宽**：所以这条链路的 `sendMessage` 带 `parse_mode=Markdown` + ``` 代码块
  （`send(..., mono=True)`），列宽按**显示宽度**补齐（东亚全角字符算两列，`unicodedata.east_asian_width`）。
  这是全站唯一用 `parse_mode` 的一条路：`--btc` 与 `--text` 仍然纯文本不带 `parse_mode`，别把它改成带。

## 5. 接口契约（/api/*）

全部只读，除 `crash/record` 外不写业务数据盘。统一响应含 `ok` 字段；`force=1` 跳过缓存强拉上游（页头「刷新」按钮即走此路径，磁盘日缓存也照样穿透，见 7.4）。通用探活：`GET /api/health` 返回 mode（local/public）/runtime/proxy/config/modules/daycache（磁盘日缓存有多少项、多大、今天写了几项）。

### /api/btc（`api/btc.py` · BTC 指标页）
| 端点 | 说明 |
|---|---|
| `summary[?force=1]` | 全部指标一次给齐：**缓存打在每一项上，没有整页缓存**，`force=1` 穿透全部上游（首屏约 8~12 秒，之后命中各自 TTL）。响应：`items[]` + `count{total,ok,failed}` + `order` + `live_age` + `hist_points`（迷你图抽样目标点数，实际每卡条数在它附近）+ `spot`/`kline_from`/`asof`（日线现价与最后一根已收盘）+ `failed[]`（缺位项及其上游原因）。只要有一项有数就回 200，全挂回 502 |
| `one?k=<指标>&force=1` | 单卡重取（卡片上的「重试」按钮）。`k` 白名单就是 `INDICATORS` 的键（`btc.py` 里加一张卡即自动进名单，当前为 `fear ahr999 two_year_multiply cbbi ema_new kdj cvdd ema litb macd mvrv nupl sopr`），其余 400。**这张表同时就是页面的卡片顺序**（`pool.map` 保序返回、页面照 `items[]` 原样铺卡，所以前端不再存一份顺序）；卡片区每行两张由 `staic/btc.html` 里的 `#grid{grid-template-columns:repeat(2,...)}` 决定（窄屏退回一列，覆盖的是 `common.css` 的共享 `.grid`，不影响流动性页与崩盘页） |
| `health` | 模块探活（纯自述，不打上游）：`indicators` / `sources` / `live_age` / `hist_points` |

每张卡的统一形状：`{key,name,unit,dp,value,text,tone,verdict,asof,src,hist[],extras[],note,ok,store}`，通道卡（`two_year_multiply`）额外多一个 `bands[]`（见下）。`tone` 只有 `red`（顶部/空头）·`green`（底部/多头）·`gray`（中性或上游没给阈值）·`bad`（取不到）四种，页面不做综合评分。`store` 是**这张卡的落库标识**（`daily` / `daily+hist` / 空 = 不落库，卡片右上角显示成「⌗ 入库」小标）：各项一律落「日读数」，**取数失败的那张也写一行**（`value=NULL` + `error` 有值），这样库里能区分「那天没数」和「那天没跑」；只有真带 `hist[]` 序列的卡才多落一份 `daily+hist`。上游清单与 TTL：日 K 线 `binance→kraken→okx→coinbase→bybit`（900s，各家解析后统一为「已收盘」日线收盘，当天那根剔除）、`alternative.me/fng`（900s）、`colintalkscrypto.com/cbbi`（3600s，合成分由上游服务端算，本页只做 0~1→0~100）、`looknode.com`（3600s，MVRV、CVDD、AHR999 与 2年MA乘数通道，NUPL 由 MVRV 推算；`twoYearMultiply` 回的是 `v1`/`v2` 两条线，走 `looknode_band()` 解析，`v1 ≡ 5×v2`）、`finance.yahoo.com` 图表接口（21600s = 6h，`BTC-USD` 的 `20y` 日线收盘，实测 4390 根、2014-09-17 起，**只服务通道卡放大图那条黄色现价线**，`api/btc.py` 的 `btc_closes()`）、`ahr999`（3600s，首选 looknode `/api/Ahr999`，其后 coinsoto→soulbab→可选 CoinGlass）、`production.lookintobitcoin.com`（3600s）。**除 CoinGlass 外全部公开无密钥**：环境里设了 `COINGLASS_KEY` 才会多试那条 Key 版路径（鉴权头 `CG-API-KEY`），密钥不进仓库、不进 `config.ini`、不进上传包——目前这条路径回 `Upgrade plan`，要套餐里有该指标才出数。取不到的项一律以 `tone:"bad"` 的虚线卡片显示原因，页面「已知缺口（宁缺毋假）」块列全，不补估算值（AHR999 尤其：`api/Crypto/handle_AHR999.py` 自己也只是 `requests.get` 取现成表格、没有任何公式，本模块拒绝发明公式）。

**卡片放大（点开不另发请求）**：`staic/btc.html` 放大入口有三个，**卡片右上角的「⤢ 放大」按钮是看得见的那个**（另有双击卡片任意位置、Tab 到卡片按 Enter；Esc / 点遮罩空白 / ✕ 收起），弹出大图，用的就是这一张卡在 `summary` 里已经拿到的那串点，只是把 `common.js` 的 `lineChart` 画到 960×320。横轴只标得出首/中/末三个日期，所以放大图带**悬浮读数**：鼠标移到曲线上（触屏点一下）按 x 找最近的那个点，画虚线十字线 + 高亮点，气泡显示该点「日期 · 数值」，落在画框外的点会把气泡拉回框内。几何一律用 `lineChart` 这次**回传**的那份（`{Y, dom, log, w, h, pad}`）：`zPaint` 存进 `ZGEO`，渲染与命中共用同一个 Y 映射，自己再算一份必然错位。MVRV 这类倍数值在 2010 年有一个极端点（实测 2010-07-19 的 45.92），按全域画整条线会被压成一条平线，所以放大图只在「2%~98% 分位那一段不足全域 1/4」时按分位截断纵轴，并在弹层里写明真实全域与被裁到尺度外的点数——**数据一条没删，只是纵轴不再被单点绑架**；卡片刻度图仍按全域画，不走这个截断。

**通道卡放大图是三条线 + 对数纵轴（2026-09-24）**：只有 `two_year_multiply` 走这条路。服务端在这一张卡上多下发一份 `bands[]`：`{d, lo, hi, px}`，等间隔抽 `BAND_POINTS`（默认 400）根，实际条数在它附近（当前 433），`lo`/`hi` 是 looknode 那两条线，`px` 是 Yahoo `BTC-USD` 收盘——按「该日或之前最近一个交易日」前向填充对齐（`bisect`，不是精确等值匹配：Yahoo 的收盘序列会缺根，实测就缺了 2026-09-23 那根，精确匹配会让最后一点没有现价）。**上游没有的日期就是 `px:null`，不填 0、不外推**：通道起点 2012-07 早于 Yahoo 起点 2014-09，所以左边那一截只有两条线，卡片的「价格线覆盖」一行与图脚都写明从哪天起、缺多少个采样点。前端画三条语义色线——**绿=支撑 730MA、红=压力 730MA×5、黄=现价**（这张卡的判据就是「现价落在通道哪一侧」，颜色跟语义走、不跟 `tone` 走），配一行图例；纵轴**对数**，且轴只上下各留 8% 的对数余量、不把 min/max 硬凑到整十倍档（数据跨约 4 个数量级，凑档要多空出近两格，三条线全挤在上半截，就是「跟上游那张图差很多」的直接原因）。悬浮气泡一次报全该日的支撑 / 压力 / 现价与「现价 ÷ 支撑」，高亮点钉在现价线上（那日缺现价就退到支撑线）。

> **修订记录**：本节上一版写着「**悬浮层只挂在 `#z-chart` 容器上，`lineChart` 一行没改**——崩盘页那四张图共用它……不值得为这点交互去动共享层」。这句到 2026-09-24 已经不成立：为了让通道卡三条线共用一套轴，`lineChart` 加了三个可选参数（`lines`、`log`）并改成**回传几何**，仍然全部向后兼容（不传就跟原来一模一样），但**共享层确实被动了**，崩盘页那四张图属于回归范围。改的另一个原因是它原先连纵轴范围都要调用方自己传，对数轴下没法只靠猜。


### /api/liquidity（`api/liquidity.py`）
| 端点 | 说明 |
|---|---|
| `fred?series=<白名单>` | FRED CSV；白名单：walcl tga rrp sofr iorb dgs10 cpi ppifd unrate rsafs pce cpiall ppi（TTL 日频 300s / 周频 600s / 月频 3600s） |
| `treasury` | 美国国债曲线（2Y/10Y） |
| `btc` | ccxt 多所现价中位数 + MA120/MA200（被 allocation 页共用） |
| `health` | 模块探活 |

### /api/crash（`api/crash.py`）
| 端点 | 说明 |
|---|---|
| `market?ticker=VOO\|QQQ` | Yahoo 日线收盘 + 200 日均线 |
| `yields` | 2Y/10Y 现值与利差历史（CNBC 实时 → FRED 降级；崩盘页与配置页共用） |
| `credit` / `shiller` / `buffett` / `fear` | HY OAS（FRED）/ 席勒PE（multpl）/ 巴菲特指标（gurufocus → FRED 换算）/ CNN 恐慌贪婪 |
| `record?ticker&score` | 当日评分写入 `data/risk_history.csv`（同日覆盖） |
| `history?ticker` | 评分历史（趋势图） |

### /api/allocation（`api/allocation.py`）
| 端点 | 说明 |
|---|---|
| `asset?sym=<白名单>` | 10 年日线收盘（Yahoo chart API，全量不降采样，供前端滚动分位）。白名单：`GC=F ^NSEI ^STOXX50E ^N225 ^HSI ^GSPC 000001.SS BTC-USD ^NDX TLT`；附 sma200/sma50/20 日动量/MA200 斜率。TTL 600s |
| `btc` | 委托 liquidity 的 ccxt 现价中位数（共享缓存），BTC 卡叠加「● 实时」角标 |
| `macro` | DGS3 / DGS10 十年历史分位（TTL 3600s） |
| `report?kind=crypto` | **本机版与公网版同一口径，不设访问凭据**（2026-09-22 用户定：报表正文发到他自己的 Telegram，页面成功时只弹一句「已发送」（3 秒自动消失），stdout 不在页面展示（2026-09-23 用户定：报表正文看 Telegram，接口仍回传 stdout 但前端不渲染）；公网版唯一约束就是下面的每日次数上限）。**不落缓存、不判级**：服务端直接运行外部 cryptoTrader 的持仓统计脚本，把 stdout 原样回传。解释器与脚本按 OS 选择（Windows `python` + `D:/Qorder_ws/cryptoTrader/tests/runningOrder.py`；Linux/FreeBSD `/home/myaibtc/vevns/web3/bin/python` + `/home/myaibtc/vevns/cryptoTrader/tests/runningOrder.py`），`config.ini [report]` 可覆盖（仍是固定值，不接受页面传入；其中 `python` 那行和 `[proxy]` 一样**只在 Windows 被读取**，服务器上换解释器用 `REPORT_PY` 环境变量）；超时 180s、同一时刻仅一个报表进程（并发直接 502「已有报表进程在跑」，且这次不计数）、**每天最多 `[report] daily_limit` 次（默认 3）**：计数落盘在 `data/report_quota.json`，按本地日期零点自动清零、服务重启不清零，点满后接口回 429「今天已发送 3 次了，明天再来」，首页按钮同步置灰。成功 = 右下角绿色弹框「已发送 · 报表已推送到 Telegram」3 秒自动消失（2026-09-23 用户定，不再往页面里铺一整块脚本输出）；失败 = 红色弹框不自动消失，只给 `error` 摘要（脚本失败时里面已带 stderr/stdout 末 500 字符）；页面不再有「持仓报告 · 脚本输出」那块，「查看报表 / 看输出」两处链接与弹层一并删掉。⚠️ 该脚本无参数即**默认把报表推送到 Telegram**（`--DD` 为仅钉钉），点一次就发一条。已知障碍：本机出口下 binance 返回 HTTP 451（本项目 BTC 现价同样把它剔除、改用 okx/kraken/gate/coinbase），而该脚本只查 binance，所以报表会在拉价阶段以退出码 1 失败，页面弹框显示这段报错摘要（完整 stdout 不再展示）。 |
| `report?kind=us` | 与 `kind=crypto` **完全同一套流程**（2026-09-23 接上，不再是 501 桩）：运行 `tests/runningStorcksOrder.py`（按人员分组统计 `cryptoTrader/data/us_stocks` 的美股 CSV，读单即可，比加密报表快得多），stdout 回接口但页面不渲染。默认路径同样按 OS 选，`[report] us_script` 或 `REPORT_US_SCRIPT` 可覆盖；限次独立：`[report] us_daily_limit` 默认 **2 次/天**，超限同样 429；成功与失败都只有右下角那一行状态（2026-09-23 同日去掉 stdout 展示）。⚠️ 该脚本无参数运行也是**默认推 Telegram**，实测 3.0s / 1042 字符成功回过一次。子进程统一带 `PYTHONUTF8=1` + `PYTHONIOENCODING=utf-8`：2026-09-23 实测本机不带的话脚本按 GBK 吐中文、服务端按 UTF-8 解出来满屏乱码。 |

### /api/db（`api/db.py` · 可选落库层，只读自述）
| 端点 | 说明 |
|---|---|
| `health` | 落库层状态（**不打上游、不写库**）：`enabled` / `reason`（没启用时是人话，如「没有口令：set MYSQL_PASSWD=…」）/ `password_from`（只说来自哪一层）/ `switches`（四个 `STORE_*`）/ `schema_present` / `statements` / `tables`（6 张表各自行数，表不存在为 `null`）/ `meta` / `version_ok`。**不回显 host、账号、口令**，公网版也挂着这一个接口 |

写入没有接口：它挂在取数路径的末尾当旁路（详见 7.3）。

跨模块共用序列（DGS10、BAMLH0A0HYM2）刻意使用相同缓存键去重。**白名单只增不减**；`/api/*` 绝不能变成任意 URL 转发器。

## 6. 页面判级规则（速览）

- **流动性页**：13 项红黄绿阈值逐条列在 `api/Liquidity/README.md` 第 6 节，页面代码与其一致。
- **崩盘页**：六因子加权（risk_model v1.3：分位数 + 非线性 + 共振 + 红线托底），规则在页面「判级规则」区公开。
- **BTC 指标页**：各张卡各自判定，不合成总分；阈值逐条抄自 `api/Crypto/handle_*.py`（`operationConfig.py:213-218,327-328` 的那几档，那份配置表在 cryptoTrader 的 `utils/` 里、没抄进本仓库）——`two_year_multiply` 是唯一的例外，cryptoTrader 没有这一项，两条线（730MA / 730MA×5）与判据都照抄 looknode 该页「指标描述」原文，连它自己写的回测衰减提示也搬进卡片 note，本页不另设阈值（**判级始终只看这两条线与现价的关系**；放大图里那条黄色现价线只是把「现价」画出来好读，来自 Yahoo，不参与判级）。页面「口径与阈值」块把每一项的公式、参数、上游文件行号原样印出来。KDJ 的 K/D 是「近 3 根算术均值」（不是行业常见的 1/3 平滑），MACD 信号线只对 `macd[25:]` 做 EMA9——这两处最容易抄错，所以行号写在卡片注释里。
- **配置页**：「贪婪恐慌深度」= 三个子分位（价/MA200 乖离、20 日动量、距 52 周高点回撤）各自在最近 756 交易日窗口内的百分位取均值（≥2 个子分位才成立）；恐慌档 2/5/8/18（4~1 级，配额 40/30/20/10%），贪婪档 65/78/88/95 只标注不卖出；全球温度 = 可得标的等权均值，缺口剔除并列入「检索缺口」。公式完整印在页面「判级规则」块。
- 已知口径限制（页面同时声明）：分位按收盘价计算，不随盘中价变动；指数为本币计价，未做汇率换算；中国利率板块无已验证取数源，按缺口列示不臆造。

## 7. 部署

### 7.1 本机版（默认，`main.py`）

1. **换机迁移**：复制整个目录 → 装 Python 3.11+（可选 ccxt）→ 改 `config.ini` 的代理与端口 → 双击 `start_app.bat`。`data/`、`logs/` 可带走（历史评分连续性）或删除（自动重建）。
2. **常驻运行（仅 Windows）**：任务计划程序开机触发 `python main.py`，或 `nssm` 包成服务。仅监听 `127.0.0.1`，防火墙无需开任何入站端口。
3. **Linux／FreeBSD（serv00 = FreeBSD 14.3）**：`sh start_app.sh` 前台跑，`Ctrl+C` 停。与 Windows 版的差异都在脚本与 `apply_config()` 里，不在 `config.ini` 里加 OS 分支：
   - 解释器优先 `/home/myaibtc/vevns/web3/bin/python`（存在即用），否则 `python3`→`python`，`PYTHON=` 可覆盖；
   - `config.ini` 的 `[proxy]` **在非 Windows 系统被跳过**（那是本机 Windows 代理客户端的端口，服务器上不存在），要代理就显式 `HTTPS_PROXY=... sh start_app.sh`；
   - 脚本强制 `PYTHONUTF8=1`：服务器 locale 常是 `C/POSIX`，中文启动横幅会直接把进程崩掉；
   - FreeBSD 上没有 systemd、`nssm` 那套，且 serv00 会收走 SSH 会话遗留的进程——`nohup` 也别指望常驻，对外服务走 7.2。自测时用 `ssh -L 8888:127.0.0.1:8888 ...` 转发到本地浏览器。

### 7.2 公网版（serv00，2026-09-22 用户明示授权后新增）

serv00 的 python 站点类型 = Phusion Passenger **WSGI**：面板用「Interpreter path」那个解释器
`import` 站点目录里的 `passenger_wsgi.py`，取模块级 `application` 处理请求。它**不允许**自启端口监听、
常驻守护或后台线程，所以本机版的 `ThreadingHTTPServer` 在那儿跑不起来 —— 公网入口因此是 `passenger_wsgi.py`，
它做四件事：设 `PUBLIC=1`、清掉代理环境变量、`_find_root()` 定位项目根（从自身位置向上探 4 层、再向下探
`public`/`public_python`/`public_html`/`www`，判据是「这层下面有 `api/app.py`」，`BOARD_ROOT` 可强制指定；serv00 实测 Passenger 的 app root 在 `public_python`，探到的真根是外层 `~/domains/<域名>`）、
把 `<根>` 和 `<根>/api` 两条都交给 `sys.path`（`api/` 用来 `import app`/`core`，根用来满足 `api/*.py` 里的 `from api import xxx` 包路径；
只给 `api/` 那一条就在装配时报 `ModuleNotFoundError: No module named 'api'`——本机版跑 `main.py` 时解释器自动把项目根放进 `sys.path[0]`，所以这条只在服务器上暴露）；
装配路由后交出 `core.wsgi_app`。**没有「启动服务」这一步**：请求进来时 Passenger 才 import，空闲后自己退出，
改完代码 `touch tmp/restart.txt` 重载即可。2026-09-22 已实测跑通（`http://myaibtc.serv00.net/` 出首页，
`运行时 python 3.11.13 · 代理 (未配置) · config.ini 已加载`）。

`PUBLIC=1` 带来的**一处**收敛（代码位置：`api/core.py` 的 `_static`/`dispatch`）：

| 收敛 | 效果 |
|---|---|
| 静态扩展名白名单 | 只放 `.html/.css/.js/.svg/.ico`；`config.ini`、`api/*.py`、`logs/`、`data/` 顺着 URL 拿不到（回 404），`/../` 一律 400 |

持仓报告**两边同口径**（2026-09-22 用户最终定的）：`Index.html` 的两个按钮本机版／公网版都显示、都能点，
点「加密持仓报告」即在服务所在机器上执行 `/home/myaibtc/vevns/web3/bin/python /home/myaibtc/vevns/cryptoTrader/tests/runningOrder.py`，
stdout 也只在按需展开时显示；约束只有 `[report] daily_limit`（加密 3 次/天）、`us_daily_limit`（美股 2 次/天）与「同一时刻只有一个报表进程」。
点「US股持仓报告」跑的是它自己的脚本（`runningStorcksOrder.py`），额度独立算每天 2 次。**没有令牌、没有登录**——报表正文本来就发到他自己的 Telegram，页面只是再显示一遍；
凭据原则上不要出现在 `config.ini` 或上传包里——**2026-09-24 用户明示开了一个口子**：`[dingding]` / `[TG]` 两段明文入库并随包上公网（见第 4 节那段「凭据的去处」），除这两段外仍按老规矩办，任何接口、日志与聊天都不许回显它们。曾经的 `?key=` 令牌门已于 2026-09-22 撤除，别再往回加。

上传与面板（2026-09-22 实测有效的布局）：

1. 打包排除 `.git/`、`.idea/`、`logs/`、`__pycache__/`、`requirements.txt`、`data/report_quota.json`、`deploy_app.sh`
   （正在跑的脚本被自己覆盖会让 bash 的增量读取错位）、
   `api/Liquidity/_legacy/`、`api/USStockCrashMonitor/`；产物 `D:\Qorder_ws\damb-public-20260923.zip`（或同名 `.tgz`，文件名里的日期 = 打包当天）。
   Windows 上打的包**必须字节级验行尾**（`start_app.sh` 要 LF／无 BOM）。zip 不携带可执行位，但不用手工
   `chmod +x` 一个个点名：`deploy_app.sh` 的「5.5 站点根所有 .sh：去 CR + 补执行位」会扫一遍根目录下的
   `*.sh`，先把 Windows 上传带进来的 `\r` 就地剥掉、再补 x 位（`--reload` 也走这段，所以 scp 单独传上去的
   `alert_cron.sh` / `shutdown_app.sh` 补跑一次 `--reload` 就治好了）。
   两个必须治的理由：① `#!/bin/sh\r` 会让 FreeBSD 去找叫 `sh\r` 的解释器，报出来却是
   `No such file or directory`（2026-09-24 在 s11 上 `./deploy_app.sh` 就是这么栽的）；② `alert_cron.sh`
   **必须**有 x 位，crontab 里它是直接当命令执行的，少 x 位＝每天一次静默 permission denied，
   只有 cron 的邮件里露一下，`logs/notify_cron.log` 连一行都没有。
   本地侧**没有**收口：仓库根没有 `.gitattributes`，`core.autocrlf=true` 下工作副本里的 `*.sh` 就是带 `\r` 的 CRLF，
   scp／打包上去也带着它。所以行尾这件事**完全由上面那段 deploy 的 5.5 兜底**——包里的 `\r` 无害，前提是服务器端
   真的跑过 `deploy_app.sh`（或 `--reload`）。绕开它手工上传 `.sh` 就是自己承担 `sh\r` 那个报错，别去加 `.gitattributes`
   装作问题在源头解决了：那只会让已经检出的工作副本继续是 CRLF，除非同时重 checkout 一遍。
2. 解到**站点根** `/usr/home/myaibtc/domains/myaibtc.serv00.net`（= `~/domains/...`，FreeBSD 上同处）：
   `tar -xf ~/damb-...zip`（FreeBSD 的 `tar` 就是 bsdtar，原生读 zip；兜底 `python -m zipfile -e <zip> <目标目录/>`）。
   第 1～3 步外加「重载 + 冒烟」已经写进根目录的 `deploy_app.sh`，站点根或 `~` 放着包时直接
   `bash deploy_app.sh` 即可：**每次都重新铺一遍**跟踪文件（没有「比 `.deployed` 新才装」那种短路，
   `--redeploy` 因此已是个只打印一句提示的空参数），铺之前会**先停一下应用**（2.5 步：TERM → 等 3 秒 →
   没退的 `KILL -9`），装完再摸 `restart.txt`、由冒烟那第一个 `/api/health` 请求把它带回来。
   停这一步的理由：几百个文件往站点根铺，旧进程一边占着几百 MB 内存（账户内存看过 96%）、一边可能在
   并发请求里 import 到半抄的 `.py`；`cp` 是就地截断再写，不是原子替换。downtime 只有几秒。
   `--no-stop` 跳过（想装完再自己挑时机重启时用）。serv00 没有 `devil www stop`，所以「停止」只能自己 kill
   进程，匹配范围收在「本用户 + 命令行带本站域名 + 带 python」，并排掉 `deploy`（不然就是自杀）、`awk`、
   `passenger-`（那是 Passenger 的 spawner）、`notify.py`（cron 正在发的日报，杀了白扔一轮上游）。
   解压前会把服务器上的 `config.ini` 备份成 `config.ini.bak.<时间戳>`。
   **这个脚本不在上传包里**，要单独传（脚本自己覆盖自己会让 bash 读到半截，历史上真出过这种事故）。
   单独传上来的一定是 Windows 的 CRLF 那份，而 5.5 段只扫**站点根**、不管 `~` 下这份，所以：
   `./deploy_app.sh` 直接执行会被内核当成解释器名带 `\r`，报一行 `: No such file or directory`
   （2026-09-25 实测）。引导一次的命令是 `tr -d '\r' < ~/deploy_app.sh > /tmp/d.sh && bash /tmp/d.sh`；
   脚本第 0 步现在自己复制时就去 CR，所以**之后**用 `bash ~/deploy_app.sh` 直接跑也行，
   但 `~` 下那份要恢复可执行还得手工 `tr` + `chmod +x` 一次。
   注意「服务在不在跑」不能拿 `ps` 当判据（Passenger 按需拉起，空闲时一个进程都没有），也不能拿
   `devil www list`（2026-09-24 实测那份输出只有域名/类型/路径三列，**没有状态列**）；看 `/api/health`。
3. 站点根下面板自建的 `public_python/`（其 `public/` 是 nginx docroot）与 `public_php/` 里**不要留任何 HTML**，
   否则被 nginx 直出、绕过 `{{SHOW_FIX}}` 替换；`private_python/` 是另一套应用，**绝不往那儿丢 `passenger_wsgi.py`**（会抢它的入口）。
   由于 app root 到底认哪一层没有权威文档，保险做法是把同一份 `passenger_wsgi.py` 再拷进 `public_python/` 与
   `public_python/public/` 各一份——`_find_root()` 会从任何一份向上找到真根，行为完全一致。
4. 面板建议把 **Number of processes 改成 1**：TTL 缓存与串行队列是进程内的，4 个进程 = 4 份缓存、4 倍上游请求，不同进程的回答还会互相不一致（磁盘上的报表计数不受影响）。
5. 改完代码 `touch tmp/restart.txt`（或 `devil www restart myaibtc.serv00.net`）让 Passenger 重载。
   **必须重载才生效的是 Python**：静态 HTML 每个请求现读磁盘，所以传完包首页立刻是新版；而 `api/*.py` 是进程启动时
   import 进内存的，不重启就一直用旧路由——「首页按钮出来了、点下去却回 `未知接口 /api/allocation/report`」就是这么来的。
   用 `curl -s .../api/health` 一眼分辨：`stale=true` = 盘上的 .py 比内存里的新（该 restart.txt 了）；
   `routes` 里没有 `report` = 内存里跑的还是把报告摘掉的那版；`pid` 在重载后会变。
   `rss_mb` = **本进程**峰值内存（MB。Unix 走 `resource.ru_maxrss`：**Linux 与 FreeBSD 都是 KB，只有 macOS 给字节**（FreeBSD `getrusage(2)` 明写 "in kilobytes"）；
   Windows 没有 `resource`，改问 `K32GetProcessMemoryInfo`/`psapi` 的 `PeakWorkingSetSize`，两条路都取不到才回 `null`）。
   2026-09-24 之前这里把 FreeBSD 也按字节除，`/api/health` 报的是 `2.1`，实际是 `ru_maxrss ≈ 2,202,009 KB ≈ 2.1G`——差了 1024 倍。
   这个值**只待在 `/api/health` 里**：主页「主机配额 · serv00」的内存那一格从前拿它现算，但它是**单进程峰值**，和那一格想说的**账户总占用**（ serv00 账户级上限 512 MB）不是一个口径，2026-09-24 起那一格改成手工抄的**账户总用量**（当天早上 4 个 Passenger worker 挂着时抄的 `1500M` = 300%，处理后下午是 `496.1M` = 96.89%，限额一直是 `512.0M`），四条同一个口径，页面只按 `used/limit` 现算百分比。
6. 冒烟五条（都**不会**执行报表脚本）：
   `curl -s https://myaibtc.serv00.net/api/health` 里应有 `"mode": "public"`，并且 `routes.allocation` 含 `report`、`stale` 为 `false`；
   `curl -o /dev/null -w '%{http_code}\n' https://myaibtc.serv00.net/config.ini` 应 `404`；
   `curl -s https://myaibtc.serv00.net/Index.html | grep -c 'id="rpt-crypto"'` 应 `1`，`rpt-us` 同理（两个按钮公网版都在）；
   `curl -s 'https://myaibtc.serv00.net/api/allocation/report'`（不带 kind）应回 400「kind 仅支持 crypto|us」——**只有这条探针是免费的**，`kind=crypto` / `kind=us` 都会真跑脚本、真发一条 TG。
   额度看一眼不花钱：`curl -s https://myaibtc.serv00.net/api/allocation/health` 里的 `report_quota`。
   **两个 kind 都别拿来冒烟**：都没有凭据门槛，curl 一下就是真跑脚本 = 真发一条 Telegram + 吃掉当天对应额度（`deploy_app.sh` 因此只打不带 kind 的 400 探针）。

已知代价：公网版没有启动预热（Passenger 每进程都预热 = 重复打上游），首个请求要现场串行取数（FRED 约 10s、行情约 40~60s）；机房 IP 被 FRED/Yahoo 拦（429/451）时页面会如实标「取数失败」而不是拿旧值冒充实时 —— 需要出口代理时在 `passenger_wsgi.py` 里把清空代理那两行填上地址，而不是改 `config.ini`。

若访问域名根路径得到光秃秃的 403（连诊断文本都没有）：说明 Passenger 压根没接管，是 nginx 按静态目录在处理（FreeBSD 大小写敏感，docroot 里放 `Index.html` 不算 `index.html`），回到第 2、3 条核对，再查面板的 Website type / Interpreter path / Directory。若站点根有 `passenger_wsgi.py` 却装配失败，页面会直接回一段纯文本诊断（实际 `__file__`、Passenger cwd、解释器、试过的候选目录、目录清单），照着它搬文件即可。

### 7.3 落库（可选旁路，2026-09-23 新增）

**它不是主路**：页面取数与 MySQL 无关，没装 `pymysql`、库不通、表没建，都只让 `/api/db/health` 少一项、日志里多一行 warning，BTC 页照常有数。这也是本服务第一次引入第三方包，所以 `import pymysql` 写在函数里而不是文件头——缺包时连连接都不尝试。

写入点全部挂在取数路径的末尾（`btc.summary()` / `crash.record()` / `allocation.r_report()` 各一行旁路调用，`store_*` 内部吞异常，双保险外层还包了一层 `try`）。表结构定义在 `sql/board_schema.sql`，6 张表：

| 表 | 存什么 | 一天一行怎么保证 |
|---|---|---|
| `board_indicator_daily` | 各指标的**日读数**：值、判级、判定文案、上游、`hist` 点数、`extras_json`、失败原因、`run_id` | `UNIQUE(metric_key,date)` + UPSERT；失败项也写（`value=NULL`、`error` 有值），用来区分「那天没数」与「那天没跑」 |
| `board_series_daily` | 长表历史序列：`series_key` 带命名空间（`btc:mvrv` / `price:daily` / `fred:WALCL`），值精度给到 `DECIMAL(24,8)` 是因为价格与 MVRV 倍数要同住一列 | `PRIMARY KEY(series_key,date)` + UPSERT |
| `board_risk_score_daily` | 崩盘页当日评分（`score` + `factors_json`） | `PRIMARY KEY(date,ticker)`；CSV 仍是权威，库里是同日覆盖的镜像 |
| `board_run_log` | 每轮 `summary` 的元数据：成功数/总数、耗时、现价、K 线源、失败项 | 只增（一次取数一行，`board_indicator_daily.run_id` 指它） |
| `board_report_run` | 报表执行**元数据**：kind、成没成、退出码、耗时、stdout 字符数、当天已用额度、报错摘要 | 只增。**stdout 正文故意不落库**——里面是持仓金额，共享库里不放 |
| `board_meta` | `schema_version` / `schema_file` / 首次建表时间 | `k` 主键 |

四条口径值得单独记：① 全部 `utf8mb4`（`verdict`/`note`/`error` 里有中文和上下标）；② 序列按业务日 UPSERT，页面每 15 分钟自动刷一次，不做幂等库里就全是同一天的重复行、历史曲线直接废掉；③ 进程内还有一层「值没变就不再打库」的指纹（上游一天只更新一次，所以一天通常只写一遍）；④ 表结构是**长表**而非每项一列，新增指标不必改表——这是刻意的，12 项变 13 项（2026-09-23 加 `two_year_multiply` 正是这一档，只动了 `btc.py` 与文档，DDL 一行没改）不该牵扯建表语句。

```bash
# 建表：在「能连到那台 3306」的机器上跑。[mysql] 现在指向本机（HOST=127.0.0.1），所以 Windows 就地建：
python .\api\db.py --init            # 幂等，可反复跑
python .\api\db.py                   # 再跑一次自检，确认 tables 全变成数字、version_ok True
# 服务器上那套库（mysql11.serv00.com：本机实测连不到它的 3306，就在服务器上说），换它的解释器：
/home/myaibtc/vevns/web3/bin/python api/db.py --init
python api/db.py --print-sql         # 只列 9 条语句、不连库（本机就能核对 SQL）
python api/db.py --help              # 完整说明
```
`--init` 就是把 `sql/board_schema.sql` 逐句执行（`SET NAMES` + 6 个 `CREATE TABLE IF NOT EXISTS` + 2 个版本戳 UPSERT，共 9 条），所以脚本本身可以拿 `mysql -h mysql11.serv00.com -u <user> -p <db> < sql/board_schema.sql` 手工跑，两条路结果一致。切到落库前确认 `pymysql` 在 venv 里（`/home/myaibtc/vevns/web3/bin/python -m pip install pymysql`），没装的话它整段空转、不报错。

**只有 `--init` 会动库**：不带参数 = 按 `--status` 跑只读自检（不会建表，这是刻意的——自检命令该能随时敲），所以「跑完没建表」是正确结果，不是故障。看输出认状态：`tables` 里 `null` = 这张表**不存在**，数字 = 这张表的行数；`version_ok false` 在表没建时同样是必然结果。建表成功后再自检，应看到 `board_meta 2` + 其余五张 `0` + `version_ok true`。

**逐指标的清单在 `INTODB.md`**：哪几项真进库、哪几张表只存元数据、哪些页面一行都不写、哪些键走日缓存，那份文件按接口逐个列全（含当前实际行数状态）。本节只讲机制与边界。

**为什么不用 `utils/operationMysql.py`**（cryptoTrader 那份 2019 年的封装，仓库内有只读副本）：三条实测理由，任一条都足以让它在服务进程里崩掉——① 它调 `OperationConfig.getMysqlConfig()`，而那个类**根本没有这个方法**（只有 `get_testenv_mysql`），装了 pymysql 也是 `AttributeError`；② 它读的是 `config/config.ini`，本仓库没有 `config/` 目录（配置在根 `config.ini`）；③ 它在 `import` 期就要 pymysql、且 `exec_updata()` 执行完把连接关掉——Web 进程里一次写入断一次连接不可接受。所以那份文件按 `api/Crypto/` 同规矩处理：**只读对照，不 import、不改**。

离线自证（本机没有库也能验 SQL 与参数）：桩连接注入 `db._conn_for_test` + 把 `socket.socket.connect` 换成抛异常 + 断言本机无 `pymysql`，三重之下 9 条建表语句、`store_btc` 的 run_log→读数→序列 executemany、同日同值第二次调用零新增语句、`status()` 响应体不含口令/账号/主机名，全部逐条打印核对过。

### 7.4 磁盘日缓存（`cached()` 的第二层，2026-09-23 新增）

**要解决的问题**：TTL 缓存活在一个进程的内存里。本机版一重启、公网版 Passenger 一收进程（空闲就退，一天若干次），缓存就空了，下一个访客又要现场打 8~23 秒上游。而这些上游里有一批**一天只变一次**——同一天里第 N 次请求和第 1 次请求拿到的是同一份数据，纯属重复劳动。

**做法**：取数成功后在 `data/daycache/<键>.json` 落一份原始结果（含 `saved_on`），两层行为故意不同：

| 层 | 哪些键 | 行为 |
|---|---|---|
| ①「今天取过就不再取」 | `btc:looknode:*`（MVRV/CVDD）、`btc:cbbi`、`btc:litb`、`btc:ahr999`、`btc:fng`、`crash:shiller`、`crash:buffett` | 当天已有磁盘文件 → 直接回那份，**一次上游都不打**；日志 `[cache] <键> 磁盘日缓存命中（今天 … 已取过，未打上游）` |
| ②只做失败兜底 | 其余全部（FRED 各序列、`btc:klines`、`btc:yahoo:BTC-USD`（通道卡现价线，6h TTL；**故意不进白名单**——它那串日线的最后一根是今天没收盘的 bar，缓存一整天就是把未收盘值当收盘价用）、`mkt:*`、`crash:yields`、`alloc10:*`…） | 照常按 TTL 打上游；只在**取数失败且内存里没有旧值**时退回磁盘那份，日志写「沿用磁盘上 X 取的旧值」 |

第②层为什么不也给 FRED 它们开①：这些键盘中还会变（WALCL/TGA 是当天晚些时候才发布），拿①挡就等于把当天的新值关在门外——那与本项目「绝不把滞后值冒充实时」的纪律冲突。

三条设计取舍，改这段代码前先看清：

- **`force=1` 永远穿透**。页头「刷新」与卡片「重试」走的就是这条路，所以这层不会挡住任何东西；`[cache] day=0` 是整层关闭的总闸。
- **失败不写盘**。失败结果一个字节都不落（否则 2026-09-23 那天三条上游全挂的 AHR999 会被钉在磁盘上一整天，把后来修好的机会也挡掉 —— 那天傍晚补上的第四条正是它的替代源）。
- **不做「只取当天那一个点」**。这些上游本来就是一次回整段历史（looknode 回 5910 个点、K 线回 499 根），没有「只给今天」的端点，所以省下的是**整次调用**、不是把响应变小；也没做「按日期从 `board_series_daily` 拼回 hist 再补当天一点」——那要改每个 builder 的取数形状，换来的收益与①完全重叠。按天累积的权威在 MySQL（7.3），跨进程/跨重启的快速路径在这堆 JSON 里，两份各司其职。

`GET /api/health` 的 `daycache` 字段是 `{enabled, dir, items, bytes, today}`（只看目录里各文件的 mtime，不解析内容），用来一眼确认这层有没有在干活。换机时 `data/daycache/` 可整目录拷走，也可直接删——下次取数自动重建。离线自证同 7.3（`socket.connect` 全程封死，假 `run()` 只数被调用几次）：日频键当天第二次调用 `run()` 次数为 1、`force=1` 时增 1、非日频键过期后仍为 2、冷进程 + 失败能退到磁盘那份、失败不落盘、`day=0` 时整层空转。

## 8. 故障排查

| 症状 | 处置 |
|---|---|
| 页面全标「○ 快照」 | 代理不通：查 `config.ini` `[proxy]`；`grep "上游失败" logs/board_server.log` 看具体域名 |
| `binance HTTP 451` / `bybit 403` | 区域封锁，属预期；BTC 用其余所中位数，剔除所已在页面标注 |
| BTC 指标页 AHR999 以前是虚线框、现在有数（Looknode）；Look Into Bitcoin 与 SOPR Z 仍是虚线 | **AHR999 这条是 2026-09-23 的修订**：原先那句「looknode 没有 `/api/ahr999`」记错了——这条路径**大小写敏感**，页面 slug 是大写 A 的 `Ahr999`，`/api/Ahr999` 就是那张图的原始序列（5700+ 个点、当天更新），已与 MVRV/CVDD 同一条 `looknode()` 通路接成首选源；`avg200`（coinsoto 那个「200 日定投成本」）Looknode 不给，卡片该行留空号，不拿序列均值顶替。原来的三条依然是死的、留着兜底：coinsoto 走代理 TLS 握手即被断开、直连 20s 超时（`api.coinsoto.com`、`coinsoto.com/api` 同样不通）；soulbab 回 530 = Cloudflare 1016「源站 DNS 解析不到」，域名已不存在；CoinGlass 的 `/api/index/ahr999` 端点在、`CG-API-KEY` 认 Key，但回 `Upgrade plan`（免费套餐不含）——同一把 Key 在 CryptoQuant 上连 `mining/hash-rate` 都是整体 403，站内 `capi.coinglass.com` 对任何路径只回一句空 `success`。另外两张：lookintobitcoin 上游 2024 年起废弃、本机出口现在连域名都被代理拒掉；`charts.bitbo.io` 的 `mvrv-z`/`sopr` 回 401，所以 SOPR 那格目前只剩 `nupl_z` 一个分量。原因逐条写在卡片与页面「已知缺口」块里，本模块拒绝为凑数而发明公式或拿旧值顶上 |
| 卡片里出现 `name 'xxx' is not defined` 这类 Python 报错原文 | 这是**代码 bug，不是网络问题**：`btc.one()` 会捕获单项异常并把原文写进那张卡（2026-09-23 就漏过一处 `remote` 没 import，12 张卡全黑）。`grep -A15 "指标 .* 计算异常" logs/board_server.log` 有完整 traceback，照行号修。修完要重启才换代码：本机版 Ctrl+C 再 `start_app.bat`，公网版 `touch tmp/restart.txt`；`/api/health` 的 `stale=true` 就是「盘上的 .py 比内存里新」的信号 |
| BTC 指标页首屏等 10 秒上下 | 正常：`summary` 没有整页缓存，各项各打各的上游（跨主机并行、同主机串行）；之后 15 分钟内命中各自 TTL 就快了。公网版 `warm=False`，每个 Passenger 冷进程的首个请求都要现打这一轮 |
| looknode 两项（MVRV/CVDD）同时变红 | 该源要求响应体 `code == 100` 才算成功，非 100 一律判失败（不是 HTTP 错，是它自己的业务码）；NUPL 由 MVRV 推算，所以 MVRV 挂必然带挂 NUPL，这两个永远一起缺 |
| Yahoo 429 | 已用浏览器 UA + referer 仍偶发；命中 TTL 缓存 600s，稍后重试即可 |
| FRED 请求挂起超时 | FRED 边缘节点会挂起「请求头过简」的客户端——`core.remote()` 已带全套常规头，改动时勿删 |
| 端口被占 | `netstat -ano \| findstr 8888`，改 `config.ini` `[server] port` |
| 公网版域名根路径 403（连诊断文本都没有） | 见 7.2：Passenger 没接管，nginx 按静态目录处理——站点根没解到包、或 docroot（`public_python/public/`）里留了 HTML 被抢先直出 |
| 公网版点「加密持仓报告」回 502 | 就是脚本自己失败了，`error` 里带的是它的 stderr 尾部（常见：binance 451 区域封锁、缺 openpyxl、解释器路径不对）。报告两侧都不设凭据，出现 401/503 说明跑的是还没撤掉令牌门的旧包 |
| 公网版点报告回 `未知接口 /api/allocation/report`（404） | 内存里是旧 Python：HTML 每请求现读、`api/*.py` 只在进程启动时 import，所以传了新包也必须 `touch tmp/restart.txt` 才换代码。`curl -s .../api/health` 看 `stale`（true＝盘上 .py 比进程新）与 `routes.allocation` 有没有 `report`；`stale=true` 就再摸一次 restart.txt，仍不变说明摸错了目录（`deploy_app.sh` 三个候选 `tmp/` 都会摸） |
| 双击 HTML 直接打开 | 无 `/api` 同源中转，页面按内置快照展示且 `{{SHOW_FIX}}` 不生效——属预期，请走 `http://127.0.0.1:8888/...` |
| 怀疑数值新旧 | 看 `logs/board_server.log`：`[http]` 行有耗时/字节；回退旧值会写 `[cache] … 沿用 Ns 前的旧值` |
| 上游换了但页面「刷新」后没变 | 先看是不是**日频项 + 当天已取过**：`grep "磁盘日缓存命中" logs/board_server.log` 有痕迹。页头「刷新」与卡片「重试」都带 `force=1`，照旧穿透；还不放心就删 `data/daycache/` 里对应键的文件（或整目录），下一轮自动重建 |
| 上游全挂、页面却给出一整串数字 | 看角标：`○ 快照` 就是旧值（7.4 的②层：冷进程 + 取数失败时退回磁盘那份）。拿不到日期才显示「取数失败」，本服务不会把滞后值标成实时 |
| 跑 `python api\db.py` 一张表也没建 | 正确行为：不带参数 = 只读的 `--status`，只有 `--init` 会执行 DDL。判状态看 `tables`：`null` = 表不存在，数字 = 行数（`version_ok false` 同因）|
| 卡片有数但库里没行 | 先看 `curl -s http://127.0.0.1:8888/api/db/health`：`enabled=false` 时 `reason` 直接说要补哪一项（缺 HOST/USER/DADABASES，或「没有口令」）；`enabled=true` 而 `tables` 全 `null` = 还没建表，跑 `api/db.py --init`；有表但行数是 0 = 那个 venv 没装 pymysql（日志里是 `[db] 没装 pymysql，本轮跳过入库`，页面不受影响）。`switches` 里某项 false 也会整段不写那一类 |
| 同一天看到多行同指标 | 不该出现：每个写入都按业务日 UPSERT。若真出现了，先确认库里的表是本版 `sql/board_schema.sql` 建的（`board_meta.schema_version` 应为 `1`、`/api/db/health` 的 `version_ok` 为 true）——缺 `UNIQUE(metric_key,date)` 的旧表要手工 `DROP TABLE` 后 `--init` 重建 |
| 双击 HTML 直接打开 | 无 `/api` 同源中转，页面按内置快照展示且 `{{SHOW_FIX}}` 不生效——属预期，请走 `http://127.0.0.1:8888/...` |
| 页面白屏/不更新 | 浏览器控制台 + 页面顶部 `livestat`；内联脚本改动后务必 `node --check`（历史上多次抓到模板字符串/括号事故） |

## 9. 安全边界（硬约束，见 `Qoder.md` 第 7 节）

- 本机版服务只绑定 `127.0.0.1`；`/api/*` 仅接受白名单参数，不做任意 URL 转发。公网版（`PUBLIC=1`）由 Passenger 对外，本服务自身仍不开端口，额外收敛只有第 7.2 节那一条静态扩展名白名单；除此之外**没有鉴权、没有限流**，公开的是取数与判级逻辑；静态白名单不收 `.ini`，所以浏览器拿不到配置文件，但**仓库本身是公开的**，`config.ini` 里那两段明文凭据的来龙去脉与后果见第 4 节。
- 两个持仓报告（`report?kind=crypto` / `?kind=us`）是本服务唯一执行外部程序的路由——共用一把串行锁，同一时刻只有一个报表进程：路径与解释器全部写死在代码里、按 OS 二选一，只能由 `config.ini`／环境变量覆盖，`kind` 只接受 `crypto|us`，不接收任何来自页面的命令、参数或路径。副作用与暴露面（2026-09-22 用户知情后选定，2026-09-23 同样口径接到美股）：两个脚本无参数运行都会把报表推送到 Telegram，点一次发一条；公网版与本机版一样不带凭据，能打开首页的人都能点，唯一闸门是各自的每日次数上限（加密 `[report] daily_limit` 默认 3、美股 `us_daily_limit` 默认 2，超限 429）与上面那把串行锁。计数落盘在 `data/report_quota.json`，形状是 `{date, kinds: {crypto: n, us: m}}`。
- 服务本身不写鉴权、不把凭据写进任何它生成的文件；代理地址只出现在 `config.ini` 或环境变量，日志与响应体里也不写凭据。BTC 指标页各项的上游**全部公开无密钥**；唯一可能的密钥是 AHR999 的备用路径 `COINGLASS_KEY`，它**只能来自环境变量**——`CONFIG_ENV` 里没有这一项，所以既不进 `config.ini`、也不进上传包，没设就完全不试那条路。`/api/btc/one?k=` 的 `k` 走 `_KEYS` 白名单，未知键 400，不接受任何 URL、路径或参数透传。
- **Telegram 出站（`api/notify.py`，2026-09-24）不是路由**：没有任何 HTTP 接口调它，页面上按不到，能真发消息的三条命令（`--text`、`--btc`、`--html-alert`）都必须由人在命令行上敲出 `--send` 才发，其余路径最多发只读的 `getMe`（`--text` 那条还额外要求带 `--bot`，不带就拒发，免得一条消息同时落到两个群）。它也不改变前面那条「唯一执行外部程序的路由」的结论——那两个持仓报告按钮仍然是本服务里唯一会跑外部脚本的地方（`notify.py` 只发一次 HTTPS 请求，不 spawn 进程）。**BTC 指标的自动推送只有命令行这一条路**：`--btc` 的口径见第 4 节（`BTC_WATCH` 四张卡的 `tone` 命中 `green`/`red` 才发，同一 `(机器人, 业务日)` 一条，`[notify] daily_limit` 封顶），`--html-alert` 的口径见 4.1（那三张卡拆「可能顶部 / 可能底部」两段各判各发、阈值在 `indicator.ini` 的 `[html_alert_top]`/`[html_alert_bottom]`、每段一个日历日只评一次、不吃 `daily_limit`）；要「每天自动播」得由你在自己机器上挂 cron／计划任务跑对应那条命令，**服务代码里没有一行会自己发信**，也别给它加路由——理由就是那三次误发：一条会自己发信的链路必须先有「一天最多几条、发什么、发给谁」的明确约定，这条约定 2026-09-24 已经定了，改它要连着改本节。
- 落库层（7.3）的三条边界：① 它是**旁路**，任何失败只记日志，绝不把异常冒到页面路径上；② `/api/db/health` 连主机名、账号、口令都不回（公网版也挂着它），日志里口令只以「来源是哪一层」出现；③ 持仓报告的 stdout **一个字符都不进库**，库里只存元数据（谁、何时、成没成、多长、报错摘要）。`[mysql] PASSWD` 的解析顺序是环境变量 > `local.ini` > `config.ini`，写进 `config.ini` 的那一行提交前应清空——**2026-09-24 核对：那行口令已经在公开的 `origin/main` 上了**，所以这条只对以后的提交有效，已经泄露的那把要么轮换要么清历史，由用户定。
- 不 `git add/commit/push`（未经明示指令）；不使用 Qoder Sites `prepare_site`/`publish_site`。公网托管只走第 7.2 节的 serv00/Passenger 路径（2026-09-22 用户明示授权；此前本项目的部署约定是「只在本机」，此次变更按修订记录公开追加而非静默改写）。
- 数据纪律：绝不把滞后值标成实时；缺测值剔除并入「检索缺口」，不估值；纠错公开追加修订记录，不静默改写。

## 10. 文档索引

| 文档 | 内容 |
|---|---|
| 本 README | 项目全貌、启动、配置、接口、部署、排障（落库层见 7.3） |
| `INTODB.md` | 落库地图（逐指标）：A 层全部 BTC 指标进库、B 层只存分数与执行痕迹、C 层完全不入库、D 层日缓存，附核对方法与当前行数状态 |
| `sql/board_schema.sql` | 6 张表的 DDL 与逐列注释，`api/db.py --init` 逐句执行它；改表结构只改这个文件并升 `board_meta.schema_version` |
| `Qoder.md`（根） | agent 约定：宏观审计提示词、输出规范、硬性纪律、边界 |
| `api/Liquidity/README.md` | 流动性模块详档：接口契约、13 项判级阈值表、实测取数约束、待补锚点 |
| `api/Liquidity/Qoder.md` | 流动性模块原约定（拓扑变更注记在顶部） |
| `api/USStockCrashMonitor/README.md`、`*/_legacy/` | 原 Streamlit 版说明与归档代码（现行实现为 `api/crash.py`） |
| BTC 指标页（无独立文档目录） | 口径就写在代码与页面里：`api/btc.py` 每张卡上方的 `handle_*.py:行号` 注释 + 页面「口径与阈值」「已知缺口」两块；接口形状见第 5 节 `/api/btc`。不再单开一份 README，免得三处各说各话 |
| `api/Crypto/handle_*.py` | cryptoTrader `api_list/` 的仓库内只读副本（2026-09-23 抄入，逐字节一致）：BTC 指标页每一项公式与阈值的出处。只读、不 import、不改；上游项目更新时整份重抄 |
