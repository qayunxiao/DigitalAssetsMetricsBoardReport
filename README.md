# DigitalAssetsMetricsBoard · 数字资产指标看板

三个本地实时监控面板 + 一个主页导航，由**同一个零依赖 Python 服务**托管：

| 页面 | 地址 | 内容 |
|---|---|---|
| 主页 | `http://127.0.0.1:8888/Index.html` | 三模块健康探针、数据链路总览 |
| 全球宏观流动性 | `…/staic/Liquidity.html` | WALCL / TGA / ON RRP / SOFR / IORB / US10Y / BTC / 核心CPI / PPI / 失业率（萨姆规则）/ 零售 等 13 项 |
| 美股崩盘风险监测 | `…/staic/USStockCrashMonitor.html` | VOO/QQQ 六因子评分（巴菲特指标、席勒PE、HY OAS、2Y-10Y、技术面乖离、恐慌贪婪指数），当日评分累积到 `data/risk_history.csv` |
| 全球优质资产配置 | `…/staic/GlobalQualityAssetAllocation.html` | 8 个全球市场 + TLT 观察位的「贪婪恐慌深度」十年分位模型、2Y/10Y 利差、DGS3/DGS10 十年分位 |

- 代码目录：`D:\Qorder_ws\DigitalAssetsMetricsBoard`
- 定位：**本地决策工具**。本机版取数依赖本机代理与 `127.0.0.1` 绑定；2026-09-22 起另有一个公网镜像（serv00 / Passenger WSGI，第 7.2 节），它按 `PUBLIC=1` 收敛掉持仓报告与非前端文件，边界见第 9 节。
- 技术栈：Python 3.11+ 标准库 HTTP 服务（`ccxt` 仅用于 BTC 多所现价，缺失时自动降级）+ 单文件原生 HTML/JS（无框架、内联 SVG、`staic/common.css|js` 四页共享）。

---

## 1. 为什么需要本地服务

FRED、纽约联储、美国财政部等官方节点**不返回 CORS 头**，浏览器无法直取；代理能解决网络可达，解决不了 CORS。因此必须由本项目同源服务做中转：

```
浏览器页面 ──/api/*（同源，绕 CORS）──► 装配层 api/app.py + 公共层 api/core.py（本机 main.py 监听 127.0.0.1:8888／公网 passenger_wsgi.py 由 Passenger 调起）
                                        │  ├─ gov_lock 串行队列 ──代理──► FRED / 财政部 / Yahoo / CNBC / CNN / multpl / gurufocus
                                        │  └─ mkt_lock 串行队列 ──代理──► ccxt（OKX/Kraken/Coinbase…，binance 451 / bybit 403 属预期剔除）
                                        └─ TTL 缓存 + single-flight；上游失败时回退旧值并让页面标注「○ 快照」
```

**判级与评分全部在页面代码里按公开阈值实时生成**，服务端只回原始序列——不改代码即可复核每一级红黄绿。

## 2. 目录结构

```
DigitalAssetsMetricsBoard/
├── Index.html                 主页（三模块探针）
├── main.py                    本机入口：起 127.0.0.1 单一服务
├── passenger_wsgi.py          公网入口（serv00/Passenger 用面板指定的解释器 import 它），见第 7 节
├── config.ini                 运行配置（代理/端口/日志/页面开关/公网模式），见第 4 节
├── start_app.bat              Windows 一键启动（= python main.py --open）
├── start_app.sh               Linux／FreeBSD 启动器（本机模式用这个；优先它自己的 venv 解释器、不沿用 Windows 代理）
├── deploy_app.sh              serv00 公网侧部署／重载脚本（判断是否已部署 → 解压或只重载，见 7.2）
├── staic/                     前端（目录名就是 "staic"，勿改）
│   ├── common.css / common.js 四页共享样式、导航、探针、自动刷新工具
│   └── Liquidity.html / USStockCrashMonitor.html / GlobalQualityAssetAllocation.html
├── api/
│   ├── core.py                公共层：config 应用、日志、TTL 缓存、串行队列、remote()、dispatch()/wsgi_app()、路由与静态托管
│   ├── app.py                 装配层：两个入口共用的模块注册表（本机版与公网版注册同一张路由表）
│   ├── liquidity.py           /api/liquidity/*   ├── crash.py      /api/crash/*
│   ├── allocation.py          /api/allocation/*（资产配置页的取数全在这一个文件里，没有同名目录）
│   ├── Liquidity/             流动性模块详档（README.md 接口契约/阈值表、Qoder.md 审计纪律）与 _legacy/ 归档
│   └── USStockCrashMonitor/   原 Streamlit 版归档（_legacy/，README.md 为旧版说明）
├── data/risk_history.csv      崩盘页每日评分累积（同日覆盖）
├── data/report_quota.json     两个持仓报告的当日点击计数（crypto/us 各记各的，跨天自动作废，限次见 [report]）
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

| 节 | 键 | 环境变量 | 当前值 / 说明 |
|---|---|---|---|
| `[proxy]` | `http` / `https` | `HTTP_PROXY` / `HTTPS_PROXY` | `http://127.0.0.1:3067`；留空 = 不走代理。**只在 Windows 生效**：`apply_config()` 在非 `nt` 系统直接跳过本段（同一份文件传到 FreeBSD/Linux 服务器上并不存在那个出口），Unix 要用代理必须显式给环境变量 |
| `[server]` | `port` | `PORT` | `8888`；监听地址固定 `127.0.0.1`，**故意不做成配置项**（只对本机版 `main.py` 有意义，公网版没有监听端口这回事）。页面与 `/api/*` 同源共用这一个端口，**没有第二个「前端端口」**：浏览器经 15888 访问是你自己的反向代理／端口映射（15888 → 127.0.0.1:8888）在转发，本项目不参与、也不因它放开绑定 |
| `[server]` | `public` | `PUBLIC` | 留空 = 本机版。`1` = 公网版（静态只放 html/css/js/svg/ico、持仓报告整段不出现、`report` 路由不注册）。公网版由 `passenger_wsgi.py` 在导入核心层前写死，服务器上不必改本文件 |
| `[log]` | `dir` / `level` | `LOG_DIR` / `LOG_LEVEL` | `logs`（相对项目根）/ `INFO`（DEBUG 含缓存命中明细，每日轮转留 14 天） |
| `[page]` | `show_fix` | `SHOW_FIX` | `1`；控制页面底部「修订记录」块，由服务端替换 HTML 标记 `{{SHOW_FIX}}` 实现，一次刷新即生效 |
| `[report]` | `python` / `crypto_script` / `us_script` / `daily_limit` / `us_daily_limit` | `REPORT_PY`（两个 kind 共用解释器）/ `REPORT_CRYPTO_SCRIPT` / `REPORT_US_SCRIPT` / `REPORT_DAILY_LIMIT` / `REPORT_US_DAILY_LIMIT` | 覆盖两个报告脚本的路径（留空 = 按 OS 用内置默认）与各自每天可点次数（默认加密 `3`、美股 `2`）。本机 `python` 已填 cryptoTrader 自己的 venv（`E:/UserTools/py311_envs/WEB3/Scripts/python.exe`，含 openpyxl/pandas/requests；系统 python 缺 openpyxl，用它跑加密报表只会得到「无数据」） |

新增配置项需同时登记 `api/core.py` 的 `CONFIG_ENV`、`config.ini` 注释与本表。配置文件不含任何凭据，可入库。

## 5. 接口契约（/api/*）

全部只读，除 `crash/record` 外不写盘。统一响应含 `ok` 字段；`force=1` 跳过缓存强拉上游（页头「刷新」按钮即走此路径）。通用探活：`GET /api/health` 返回 mode（local/public）/runtime/proxy/config/modules。

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
| `report?kind=crypto` | **本机版与公网版同一口径，不设访问凭据**（2026-09-22 用户定：报表正文发到他自己的 Telegram，页面成功时只弹一句「已发送」（3 秒自动消失），stdout 收在状态行的「查看报表」链接里点开才显示；公网版唯一约束就是下面的每日次数上限）。**不落缓存、不判级**：服务端直接运行外部 cryptoTrader 的持仓统计脚本，把 stdout 原样回传。解释器与脚本按 OS 选择（Windows `python` + `D:/Qorder_ws/cryptoTrader/tests/runningOrder.py`；Linux/FreeBSD `/home/myaibtc/vevns/web3/bin/python` + `/home/myaibtc/vevns/cryptoTrader/tests/runningOrder.py`），`config.ini [report]` 可覆盖（仍是固定值，不接受页面传入；其中 `python` 那行和 `[proxy]` 一样**只在 Windows 被读取**，服务器上换解释器用 `REPORT_PY` 环境变量）；超时 180s、同一时刻仅一个报表进程（并发直接 502「已有报表进程在跑」，且这次不计数）、**每天最多 `[report] daily_limit` 次（默认 3）**：计数落盘在 `data/report_quota.json`，按本地日期零点自动清零、服务重启不清零，点满后接口回 429「今天已发送 3 次了，明天再来」，首页按钮同步置灰。成功 = 右下角绿色弹框「已发送 · 报表已推送到 Telegram」3 秒自动消失（2026-09-23 用户定，不再往页面里铺一整块脚本输出）；失败 = 红色弹框不自动消失并给「看输出」，报表正文与报错都归到「持仓报告 · 脚本输出」那块按需展开。⚠️ 该脚本无参数即**默认把报表推送到 Telegram**（`--DD` 为仅钉钉），点一次就发一条。已知障碍：本机出口下 binance 返回 HTTP 451（本项目 BTC 现价同样把它剔除、改用 okx/kraken/gate/coinbase），而该脚本只查 binance，所以报表会在拉价阶段以退出码 1 失败，页面把这段报错原样展示。 |
| `report?kind=us` | 与 `kind=crypto` **完全同一套流程**（2026-09-23 接上，不再是 501 桩）：运行 `tests/runningStorcksOrder.py`（按人员分组统计 `cryptoTrader/data/us_stocks` 的美股 CSV，读单即可，比加密报表快得多），stdout 回页面。默认路径同样按 OS 选，`[report] us_script` 或 `REPORT_US_SCRIPT` 可覆盖；限次独立：`[report] us_daily_limit` 默认 **2 次/天**，超限同样 429。⚠️ 该脚本无参数运行也是**默认推 Telegram**，实测 3.0s / 1042 字符成功回过一次。子进程统一带 `PYTHONUTF8=1` + `PYTHONIOENCODING=utf-8`：2026-09-23 实测本机不带的话脚本按 GBK 吐中文、服务端按 UTF-8 解出来满屏乱码。 |

跨模块共用序列（DGS10、BAMLH0A0HYM2）刻意使用相同缓存键去重。**白名单只增不减**；`/api/*` 绝不能变成任意 URL 转发器。

## 6. 页面判级规则（速览）

- **流动性页**：13 项红黄绿阈值逐条列在 `api/Liquidity/README.md` 第 6 节，页面代码与其一致。
- **崩盘页**：六因子加权（risk_model v1.3：分位数 + 非线性 + 共振 + 红线托底），规则在页面「判级规则」区公开。
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
`public`/`public_python`/`public_html`/`www`，判据是「这层下面有 `api/app.py`」，`BOARD_ROOT` 可强制指定）、
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
任何凭据都不要出现在 `config.ini` 或上传包里（曾经的 `?key=` 令牌门已于 2026-09-22 撤除，别再往回加）。

上传与面板（2026-09-22 实测有效的布局）：

1. 打包排除 `.git/`、`.idea/`、`logs/`、`__pycache__/`、`requirements.txt`、`data/report_quota.json`、`deploy_app.sh`
   （正在跑的脚本被自己覆盖会让 bash 的增量读取错位）、
   `api/Liquidity/_legacy/`、`api/USStockCrashMonitor/`；产物 `D:\Qorder_ws\damb-public-20260923.zip`（或同名 `.tgz`，文件名里的日期 = 打包当天）。
   Windows 上打的包**必须字节级验行尾**（`start_app.sh` 要 LF／无 BOM），zip 不携带可执行位所以解完要 `chmod +x start_app.sh`。
2. 解到**站点根** `/usr/home/myaibtc/domains/myaibtc.serv00.net`（= `~/domains/...`，FreeBSD 上同处）：
   `tar -xf ~/damb-...zip`（FreeBSD 的 `tar` 就是 bsdtar，原生读 zip；兜底 `python -m zipfile -e <zip> <目标目录/>`）。
   第 1～3 步外加「重载 + 冒烟」已经写进根目录的 `deploy_app.sh`，站点根或 `~` 放着包时直接
   `bash deploy_app.sh` 即可：它按「`api/app.py` 在不在 + 包是否比 `.deployed` 标记新」决定是解压部署还是只重载
   （`--redeploy` 强制重解），解压前会把服务器上的 `config.ini` 备份成 `config.ini.bak.<时间戳>`。
   **这个脚本不在上传包里**，要单独传（脚本自己覆盖自己会让 bash 读到半截，历史上真出过这种事故）。
   注意它判断「服务在不在跑」只能用 `devil www list` 的 running/stopped —— Passenger 按需拉起，空闲时 `ps` 里一个进程都没有，别拿进程列表当判据。
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
   `rss_mb` = **本进程**峰值内存（MB；Unix 走 `resource.ru_maxrss`，其单位 Linux 是 KB、FreeBSD/macOS 是字节，代码分别换算；
   Windows 没有 `resource`，改问 `K32GetProcessMemoryInfo`/`psapi` 的 `PeakWorkingSetSize`，两条路都取不到才回 `null`）。
   主页「主机配额 · serv00」的内存那一格拿它现算，其余三格的用量仍是手工抄的面板快照——那一格**只说这一个进程**，不等于账户总额（serv00 的 512 MB 是账户级上限），更不是整机内存。
6. 冒烟五条（都**不会**执行报表脚本）：
   `curl -s https://myaibtc.serv00.net/api/health` 里应有 `"mode": "public"`，并且 `routes.allocation` 含 `report`、`stale` 为 `false`；
   `curl -o /dev/null -w '%{http_code}\n' https://myaibtc.serv00.net/config.ini` 应 `404`；
   `curl -s https://myaibtc.serv00.net/Index.html | grep -c 'id="rpt-crypto"'` 应 `1`，`rpt-us` 同理（两个按钮公网版都在）；
   `curl -s 'https://myaibtc.serv00.net/api/allocation/report'`（不带 kind）应回 400「kind 仅支持 crypto|us」——**只有这条探针是免费的**，`kind=crypto` / `kind=us` 都会真跑脚本、真发一条 TG。
   额度看一眼不花钱：`curl -s https://myaibtc.serv00.net/api/allocation/health` 里的 `report_quota`。
   **两个 kind 都别拿来冒烟**：都没有凭据门槛，curl 一下就是真跑脚本 = 真发一条 Telegram + 吃掉当天对应额度（`deploy_app.sh` 因此只打不带 kind 的 400 探针）。

已知代价：公网版没有启动预热（Passenger 每进程都预热 = 重复打上游），首个请求要现场串行取数（FRED 约 10s、行情约 40~60s）；机房 IP 被 FRED/Yahoo 拦（429/451）时页面会如实标「取数失败」而不是拿旧值冒充实时 —— 需要出口代理时在 `passenger_wsgi.py` 里把清空代理那两行填上地址，而不是改 `config.ini`。

若访问域名根路径得到光秃秃的 403（连诊断文本都没有）：说明 Passenger 压根没接管，是 nginx 按静态目录在处理（FreeBSD 大小写敏感，docroot 里放 `Index.html` 不算 `index.html`），回到第 2、3 条核对，再查面板的 Website type / Interpreter path / Directory。若站点根有 `passenger_wsgi.py` 却装配失败，页面会直接回一段纯文本诊断（实际 `__file__`、Passenger cwd、解释器、试过的候选目录、目录清单），照着它搬文件即可。

## 8. 故障排查

| 症状 | 处置 |
|---|---|
| 页面全标「○ 快照」 | 代理不通：查 `config.ini` `[proxy]`；`grep "上游失败" logs/board_server.log` 看具体域名 |
| `binance HTTP 451` / `bybit 403` | 区域封锁，属预期；BTC 用其余所中位数，剔除所已在页面标注 |
| Yahoo 429 | 已用浏览器 UA + referer 仍偶发；命中 TTL 缓存 600s，稍后重试即可 |
| FRED 请求挂起超时 | FRED 边缘节点会挂起「请求头过简」的客户端——`core.remote()` 已带全套常规头，改动时勿删 |
| 端口被占 | `netstat -ano \| findstr 8888`，改 `config.ini` `[server] port` |
| 公网版域名根路径 403（连诊断文本都没有） | 见 7.2：Passenger 没接管，nginx 按静态目录处理——站点根没解到包、或 docroot（`public_python/public/`）里留了 HTML 被抢先直出 |
| 公网版点「加密持仓报告」回 502 | 就是脚本自己失败了，`error` 里带的是它的 stderr 尾部（常见：binance 451 区域封锁、缺 openpyxl、解释器路径不对）。报告两侧都不设凭据，出现 401/503 说明跑的是还没撤掉令牌门的旧包 |
| 公网版点报告回 `未知接口 /api/allocation/report`（404） | 内存里是旧 Python：HTML 每请求现读、`api/*.py` 只在进程启动时 import，所以传了新包也必须 `touch tmp/restart.txt` 才换代码。`curl -s .../api/health` 看 `stale`（true＝盘上 .py 比进程新）与 `routes.allocation` 有没有 `report`；`stale=true` 就再摸一次 restart.txt，仍不变说明摸错了目录（`deploy_app.sh` 三个候选 `tmp/` 都会摸） |
| 双击 HTML 直接打开 | 无 `/api` 同源中转，页面按内置快照展示且 `{{SHOW_FIX}}` 不生效——属预期，请走 `http://127.0.0.1:8888/...` |
| 怀疑数值新旧 | 看 `logs/board_server.log`：`[http]` 行有耗时/字节；回退旧值会写 `[cache] … 沿用 Ns 前的旧值` |
| 页面白屏/不更新 | 浏览器控制台 + 页面顶部 `livestat`；内联脚本改动后务必 `node --check`（历史上多次抓到模板字符串/括号事故） |

## 9. 安全边界（硬约束，见 `Qoder.md` 第 7 节）

- 本机版服务只绑定 `127.0.0.1`；`/api/*` 仅接受白名单参数，不做任意 URL 转发。公网版（`PUBLIC=1`）由 Passenger 对外，本服务自身仍不开端口，额外收敛只有第 7.2 节那一条静态扩展名白名单；除此之外**没有鉴权、没有限流**，公开的是取数与判级逻辑，不含任何凭据。
- 两个持仓报告（`report?kind=crypto` / `?kind=us`）是本服务唯一执行外部程序的路由——共用一把串行锁，同一时刻只有一个报表进程：路径与解释器全部写死在代码里、按 OS 二选一，只能由 `config.ini`／环境变量覆盖，`kind` 只接受 `crypto|us`，不接收任何来自页面的命令、参数或路径。副作用与暴露面（2026-09-22 用户知情后选定，2026-09-23 同样口径接到美股）：两个脚本无参数运行都会把报表推送到 Telegram，点一次发一条；公网版与本机版一样不带凭据，能打开首页的人都能点，唯一闸门是各自的每日次数上限（加密 `[report] daily_limit` 默认 3、美股 `us_daily_limit` 默认 2，超限 429）与上面那把串行锁。计数落盘在 `data/report_quota.json`，形状是 `{date, kinds: {crypto: n, us: m}}`。
- 不写鉴权、不持久化凭据；代理地址只出现在 `config.ini` 或环境变量，日志与响应体里也不写凭据。
- 不 `git add/commit/push`（未经明示指令）；不使用 Qoder Sites `prepare_site`/`publish_site`。公网托管只走第 7.2 节的 serv00/Passenger 路径（2026-09-22 用户明示授权；此前本项目的部署约定是「只在本机」，此次变更按修订记录公开追加而非静默改写）。
- 数据纪律：绝不把滞后值标成实时；缺测值剔除并入「检索缺口」，不估值；纠错公开追加修订记录，不静默改写。

## 10. 文档索引

| 文档 | 内容 |
|---|---|
| 本 README | 项目全貌、启动、配置、接口、部署、排障 |
| `Qoder.md`（根） | agent 约定：宏观审计提示词、输出规范、硬性纪律、边界 |
| `api/Liquidity/README.md` | 流动性模块详档：接口契约、13 项判级阈值表、实测取数约束、待补锚点 |
| `api/Liquidity/Qoder.md` | 流动性模块原约定（拓扑变更注记在顶部） |
| `api/USStockCrashMonitor/README.md`、`*/_legacy/` | 原 Streamlit 版说明与归档代码（现行实现为 `api/crash.py`） |
