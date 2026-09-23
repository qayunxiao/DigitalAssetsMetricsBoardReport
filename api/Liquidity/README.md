# RealtimeCoreMetricsBoard · 全球宏观流动性实时监控面板

> **2026-09-22 起并入 `DigitalAssetsMetricsBoard`**：本目录的独立入口（`main.py`/`fetch_server.py`/`config.ini`/`start_app.bat`）已移至 `_legacy/`，仅作历史参考。现行实现在项目根目录：`main.py` → `api/core.py`（公共层）→ `api/liquidity.py`，路由加 `/api/liquidity/*` 前缀，面板地址 `http://127.0.0.1:8888/staic/Liquidity.html`，启动用根目录 `start_app.bat`。下文技术约束（判级阈值、实测取数坑、白名单）仍然有效，`/api/*` 路径读作 `/api/liquidity/*`。

刷新即取的宏观流动性看板：**美联储总资产、TGA、ON RRP、SOFR、IORB、US10Y、BTCUSD、核心 CPI、PPI、失业率（萨姆规则）、零售销售**共 11 项指标，全部由本地服务经代理向官方节点取数，风险判级由代码按公开阈值实时生成。

- 面板：`http://127.0.0.1:4319/macro-liquidity.html`
- **Windows 10 最快启动：双击 `start_app.bat`**（完整步骤、故障排查见第 2 节）
- 代码目录：`D:\Qorder_ws\RealtimeCoreMetricsBoard`
- 定位：**本地决策工具**，不是公网站点（数据链路依赖本机代理与 `127.0.0.1` 绑定）

---

## 1. 为什么需要本地服务

FRED、纽约联储、H.4.1 等官方节点**不返回 CORS 头**，浏览器无法直取；代理能解决网络可达却解决不了 CORS。因此必须由本项目的同源服务做中转：

```
浏览器页面  ──/api/*──►  fetch_server.py (127.0.0.1:4319)  ──HTTP/HTTPS 代理──►  FRED / 美国财政部 / 交易所
```

`/api/*` 与页面同源，绕开 CORS；页面在接口不可用时自动退回内置的 2026-09-21 一手取证快照，并在每张卡片上以「○ 快照」标注，不会把滞后值冒充实时值。

## 2. 在 Windows 10 上启动

### 2.0 一次性前置检查

本项目实测环境：Windows 10 19044 + Python 3.11.0（`C:\Program Files\Python311\python.exe`）+ ccxt 4.5.81。

```bat
python --version           :: 需 ≥ 3.11（若提示找不到命令，改用 py --version）
python -m pip show ccxt    :: 未安装则： python -m pip install ccxt
```

**代理必须在跑**：取数经 `127.0.0.1:3067`（HTTP/HTTPS）。检查它是否在监听：

```bat
netstat -ano | findstr :3067
```

没有输出＝代理客户端未启动，先去开它。代理不可达时接口会返回明确错误、页面退回「○ 快照」，**不会伪造数据**。

### 2.1 启动（三选一）

**方式 A · 双击批处理（推荐）** —— 在资源管理器里打开本目录，双击 `start_app.bat`。它就一句 `python main.py --open`：起服务，1 秒后自行打开面板（端口取自 `config.ini`，不在脚本里写死）。控制台窗口须保持开着，关掉即停服务。

**方式 B · 命令行** —— `Win+R` 输入 `cmd` 回车，然后：

```bat
cd /d D:\Qorder_ws\RealtimeCoreMetricsBoard
python main.py            :: 代理与端口直接取 config.ini
```

临时换一次出口代理或端口，用环境变量覆盖即可（优先级高于 `config.ini`）：

```bat
set HTTPS_PROXY=http://127.0.0.1:7890 && python main.py
```

**方式 C · PyCharm** —— 打开本目录，直接 Run `main.py`（默认值来自 `config.ini`，不需配运行环境变量；Run 配置里加 `--open` 就会自动开面板）。

启动成功时控制台输出：

```
宏观流动性服务已启动 http://127.0.0.1:4319/macro-liquidity.html  代理=http://127.0.0.1:3067
日志：D:\Qorder_ws\RealtimeCoreMetricsBoard\logs\fetch_server.log
配置：D:\Qorder_ws\RealtimeCoreMetricsBoard\config.ini
```

（第三行若显示 `（未找到，使用内置默认值）`，说明 `config.ini` 不在项目目录里或路径不对，此时代理与端口走代码内置默认。）

行情预热的结果只写日志不印控制台，冷启动后约 **39~53 秒**会在日志里出现一行（实测 2026-09-21）：

```
[warm] 行情预热成功 用时 38759ms  现价=81580.6 可达源=4
```

这段时间是逐家交易所首次 `load_markets()`（本进程内复用，之后同一请求只需 5 秒左右）。**预热期间面板已经可用**：FRED 与财政部走另一条队列，13 个序列约 11 秒内全部转成 `● 实时`，只有 BTC 卡片在等预热结果；期间点「↻ 刷新实时」不会重复打行情源，日志会写 `[cache] btc 复用并发请求的结果`。若未装 ccxt 会打印安装提示，BTC 卡片显示取数失败，其余 10 项正常。

### 2.2 确认面板真的在取实时数据

浏览器打开 <http://127.0.0.1:4319/macro-liquidity.html>，看两处：

- 顶部状态行应为 **`实时 13/13 源`**；
- 每张卡片角标应为 **`● 实时`**（显示 `○ 快照`＝该源没取到，展示的是内置 2026-09-21 快照）。

命令行核验（Win10 1803+ 自带 curl）：

```bat
curl http://127.0.0.1:4319/api/health
curl "http://127.0.0.1:4319/api/fred?series=walcl&force=1"
```

前者返回 `{"ok": true, "runtime": "python 3.11.0", "proxy": "http://127.0.0.1:3067", ...}`；后者 `ok:true` 且带 `rows`。手动穿透缓存重取：点页面「↻ 刷新实时」（等价于带 `force=1`）。

### 2.3 停止 / 换端口 / 自启

- **停止**：控制台按 `Ctrl+C`，或直接关窗口。
- **端口 4319 被占用**（`OSError: 只允许使用一次...`）：多半是上一次的服务还活着。找出并结束：

  ```bat
  netstat -ano | findstr :4319
  taskkill /PID <上面查到的PID> /F
  ```

  或换端口启动（页面同源，不需改代码，访问地址里的端口跟着变）：

  ```bat
  set PORT=5000 && python main.py      :: 或直接把 config.ini 的 [server] port 改成 5000
  ```

- **开机自启（可选）**：`Win+R` → `shell:startup` 回车，把 `start_app.bat` 的快捷方式放进去。前提是先让代理客户端也自启，否则自启的面板只会是快照。

### 2.4 常见故障

| 现象 | 原因与处理 |
|---|---|
| 双击 bat 后窗口一闪就没 | `python` 不在 PATH：改用 `py main.py`，或重装 Python 并勾选 *Add to PATH* |
| 全部卡片显示 `○ 快照` | 代理 3067 未启动，或控制台里 `代理=(未配置…)`；先过 2.0 的两项检查 |
| 只有 BTC 卡片报错 | 未装 ccxt；或出口 IP 被 `binance`(451)/`bybit`(403) 拦，中位数会由其余可达源构成，属正常 |
| FRED 序列间歇失败、返回 HTML | 上游限流。同上游已分队列串行；仍出现则拉长间隔或换出口 |
| 控制台中文乱码 | 用 `start_app.bat`（内含 `chcp 65001`），别用裸 `cmd` 的 GBK 页 |
| 页面数值不变 | 周频/月频数据只在官方发布后更新，**频率错配不会因刷新消失**（见第 5 节） |

### 2.5 配置（config.ini）与覆盖

运行参数集中在 **`config.ini`**（本目录，可入库：只有本机代理端口与日志设置，无凭据）。

| 段 / 键 | 对应环境变量 | 默认 | 说明 |
|---|---|---|---|
| `[proxy] http` | `HTTP_PROXY` | `http://127.0.0.1:3067` | 上游取数出口 |
| `[proxy] https` | `HTTPS_PROXY` | `http://127.0.0.1:3067` | 同上（FRED/财政部/交易所走 HTTPS） |
| `[server] port` | `PORT` | `4319` | 本地服务端口；监听地址固定 `127.0.0.1`，不提供配置项 |
| `[log] dir` | `LOG_DIR` | `logs` | 相对路径按项目目录解析；不可写则降级为仅控制台 |
| `[log] level` | `LOG_LEVEL` | `INFO` | `DEBUG` 看缓存命中明细，`WARNING` 只留失败痕迹 |
| `[page] show_fix` | `SHOW_FIX` | `1` | 页面底部「修订记录」是否展示：`1` 展示（标题可点击展开／收缩，折叠状态记在浏览器 `localStorage` 的 `rev-open`，清空该键或首次访问即展开）／`0` 隐藏。服务返回 HTML 时替换 `{{SHOW_FIX}}` 标记，故**只对 `http://127.0.0.1:4319/...` 生效**；直接双击 HTML 打开时标记未被替换，按展示处理。隐藏只是不渲染，历史版本仍留在文件里 |

**优先级：环境变量 > `config.ini` > 代码内置默认**。`fetch_server.apply_config()` 只在环境变量缺失时写入（与原 `main.py` 里 `os.environ.setdefault` 的语义一致），所以临时改一次用 `set`，长期改就编辑 `config.ini`。文件缺失或某项留空都不会报错，会退回内置默认；`/api/health` 会回显 `config` 路径、`config_loaded` 与 `show_fix`，启动日志里也有 `配置=…(已加载)`。

**依赖**：Python 3.11+，HTTP 服务与解析全用标准库；行情侧需要 `ccxt`（`python -m pip install ccxt`，实测 4.5.81）。

## 3. 文件

| 文件 | 说明 |
|---|---|
| `main.py` | 入口：调 `fetch_server.serve()`，自身不含任何默认值 |
| `fetch_server.py` | 取数服务：路由、FRED 白名单、缓存、串行队列、ccxt 行情、静态文件 |
| `macro-liquidity.html` | 面板（单文件，含内联 SVG 图表与判级规则，无前端框架） |
| `start_app.bat` | Windows 启动器：`chcp 65001` + `python main.py --open` |
| `config.ini` | 运行配置：代理、端口、日志目录与级别、页面显示开关（环境变量可覆盖，见第 2.5 节） |
| `Qoder.md` | 项目约定：宏观审计的提示词输入（触发词、7 项强制锚点、取数纪律）与输出规范（三段式 + 检索缺口），以及边界与待办 |
| `logs/fetch_server.log` | 接口与取数日志（每日轮转、留 14 天；不入库，见第 4.1 节） |

## 4. 接口

| 端点 | 参数 | 上游 | 缓存 |
|---|---|---|---|
| `GET /api/health` | — | 无外部依赖，返回运行时与当前代理 | 不缓存 |
| `GET /api/fred` | `series=<key>`，可选 `force=1` | `fred.stlouisfed.org/graph/fredgraph.csv` | 按序列：日频 300s／周频 600s／月频 3600s |
| `GET /api/treasury` | 可选 `force=1` | 美国财政部每日收益率曲线 CSV（取 `10 Yr`） | 300s |
| `GET /api/btc` | 可选 `force=1` | ccxt 多所现价 + 日线收盘 | 现价 45s；日线按日期缓存 6h |

`series` 白名单（只允许这些，服务不会变成任意 URL 转发器）：

`walcl` WALCL · `tga` WDTGAL · `rrp` RRPONTSYD · `sofr` SOFR · `iorb` IORB · `dgs10` DGS10 · `unrate` UNRATE · `cpi` CPILFESL · `cpiall` CPIAUCSL · `pce` PCEPILFE · `ppi` PPIACO · `ppifd` WPSFD49201 · `rsafs` RSAFS

响应统一含 `ok` / `rows[{d,v}]` / `latest` / `source` / `unit` / `cached_at`；失败时返回上一次成功值并带陈旧标记，或 `ok:false` + 具体错误。

### 4.1 接口日志（每次刷新都有痕迹）

所有请求与取数都写入 **`logs/fetch_server.log`**（UTF-8，每日午夜轮转，保留 14 天，形如 `fetch_server.log.2026-09-20`）。`logs/` 已在 `.gitignore` 内，不会入库。

四类行，按标签 grep：

| 标签 | 内容 | 级别 |
|---|---|---|
| `[http]` | 每次页面请求：方法、路径（含 `force=1`）、状态码、响应字节、总耗时。缓存命中通常 0–3ms | INFO |
| `[cache]` | 每个键的穿透原因（首次/过期/强制穿透）、耗时、TTL；**失败并退回旧值**（页面因此显示「○ 快照」）为 WARNING | INFO/WARNING |
| `[fred]` `[treasury]` | 上游 `URL 耗时 字符数`，以及解析出的行数与最新观测（`WALCL 解析 68 行 最新 2026-09-16=6746548.0`） | INFO |
| `[btc]` | 逐家交易所报价（含失败原因与耗时）、中位数与跨所价差、日线来源与根数、MA120/MA200 与均线位置、本月/本季涨幅 | INFO/WARNING |

实测一次全量刷新（15:27–15:28，日志原文节选）：

```
[btc] 现价 okx = 81654.50  3066ms
[btc] 现价 binance 失败 1434ms: HTTP 451
[btc] 现价 bybit 失败 965ms: HTTP 403
[btc] 中位数现价 81652.25 ← 4/6 家 okx=81654 kraken=81650 gate=81656 coinbase=81589（跨所价差 67.71）；剔除 binance(HTTP 451) bybit(HTTP 403)
[btc] 日线取自 okx：259 根（2026-01-05 → 2026-09-20）343ms
[btc] MA120=68314.04 MA200=70540.53 均线位置 站上双均线 | 日线 259 根(源 okx) | 本月 3.91% / 本季 39.27% | 总耗时 59773ms
[fred] WALCL 解析 68 行  最新 2026-09-16=6746548.0  区间起点 2025-06-04
[cache] btc  复用并发请求的结果（排队 48075ms，未重复打上游）
[http] GET /api/btc?force=1 -> 200 798B 4288ms
```

上例最后那条 `总耗时 59773ms` 是**冷启动**那一趟：六个交易所首次 `load_markets()` 全算在里面，且页面首屏的 `force=1` 与后台预热撞在一起——日志里紧跟着的 `[cache] btc 复用并发请求的结果（排队 48075ms，未重复打上游）` 说明排队者没有再打第二次上游。预热完成后同一请求实测 5.4 秒（首轮）→ 0~4 秒（45 秒 TTL 内）。FRED/财政部与行情分属两条队列，互不阻塞（见第 7 节第 1 条）。

查看与调级：

```powershell
# 实时跟踪（PowerShell）
Get-Content D:\Qorder_ws\RealtimeCoreMetricsBoard\logs\fetch_server.log -Wait -Tail 50
```

```bat
:: 只看 BTC 相关
findstr "[btc]" D:\Qorder_ws\RealtimeCoreMetricsBoard\logs\fetch_server.log
:: 只看失败与告警
set LOG_LEVEL=WARNING && python main.py
:: 换日志目录（例如指到别处或临时关闭时指到 NUL 所在盘的小目录）
set LOG_DIR=D:\temp\macrologs && python main.py
```

页面每 60 秒自动同步会稳定产生约 15 行 `[http]`（约 2 万行/天，几十 MB 级，靠轮转兜住）。只想留失败痕迹就用 `LOG_LEVEL=WARNING`。

> 缓存命中、预热结果等细节日志在 `DEBUG` 级（`[cache] fred:walcl 命中 age=12s/300s`），排障时把 `LOG_LEVEL=DEBUG` 打开。
> **同一时间只跑一个实例**：两个进程追加同一文件会在午夜轮转时互相挤掉日志行（端口 4319 被占用通常就是旧进程还在）。

## 5. 页面计算的内容（不是接口直读）

净流动性 `WALCL − TGA − ON RRP`（TGA/RRP 与 WALCL 的**同周三**对齐，非交易日取最近观测）、单周变化与区间分位、`SOFR − IORB` 利差、CPI/PPI/PCE 同比与环比、萨姆规则差值、BTC 相对 MA120/MA200 偏离与本月/本季度涨跌（基准取上一个自然月、自然季度最后一个收盘价）、评级构成与筛选计数。

**刷新节奏**：页面每 60 秒自动同步；「↻ 刷新实时」按钮带 `force=1` 穿透缓存重取。注意**频率错配不会因刷新而消失**——周频/月频数据只有官方发布新值后才会变。

## 6. 判级阈值（公开，可复核）

| 指标 | 🔴 高危 | 🟡 中性 | 🟢 安全 |
|---|---|---|---|
| WALCL | —（不设红档） | 周降幅 > 5B | 周降幅 ≤ 5B |
| TGA | 周增 > 80B | 周增 30–80B | 周增 ≤ 30B |
| ON RRP | < 20B（缓冲垫耗尽） | 20–200B | ≥ 200B |
| SOFR | 利差 > +10bp（管道挤兑） | 利差 > 0 | 利差 ≤ 0 |
| IORB | 会期上调（加息方向） | 持平 | 会期下调 |
| US10Y | ≥ 5.00% | 4.80–5.00% | < 4.80% |
| BTCUSD | 跌破 MA200 | 破 MA200 未破 MA120／均线不可核验 | 站上 MA120 与 MA200 |
| 核心 CPI | 同比 > 3% | 2.5–3% | ≤ 2.5% |
| PPI 终端需求 | 同比 > 3% | 2–3% | ≤ 2% |
| 失业率 | 萨姆规则触发 | 差值 ≥ 0.3pp／序列不足 | 差值 < 0.3pp |
| 零售销售 | 环比 < 0 | 0–0.6% | ≥ 0.6% |

任一序列缺值时判为 🟡，不做乐观推定。综合评级 = 按上表统计红/黄/绿数量后给出。

## 7. 已实测的取数约束（改动前请先读）

1. **FRED 会限流并发**：并发请求返回 HTML 而非 CSV，所以同一数据源内部一律排队串行——但**分两条队列**：`gov_lock`（FRED + 美国财政部，13 个序列串行约 11 秒）与 `mkt_lock`（ccxt 行情源，逐家排队）。早期版本共用一把全局锁，实测导致冷启动时 13 个 FRED 序列整体排在 ccxt 预热（40~60 秒）之后、页面首屏退回快照，故拆开；两条队列并发跑不同主机不受影响。
2. **FRED 按请求头画像挂起连接**：只带 `User-Agent`+`Accept` 的简洁请求在 Python 侧读超时（curl/Node 正常），必须补齐 `Accept-Language` / `Accept-Encoding` / `Cache-Control`。
3. **ccxt 交易所实例必须按进程缓存**：否则每次刷新都要 `load_markets()`（实测首请求 27 秒，预热后 1.9 秒）。服务启动时会后台预热。
4. **本机代理出口下 `binance` 返回 451（地区封锁）、`bybit` 返回 403**，中位数实际由 `okx / kraken / gate / coinbase` 构成；卡片显示的可达源数量随网络浮动，属真实值。
5. **官方序列的缺测值必须剔除**：FRED `UNRATE` 的 `2025-10` 记为 `0`（BLS 停摆未发布）。若不剔除，萨姆规则 12 个月低点被拉成 0，差值虚高至 4.13pp，**直接误判为已触发**。现按 `v > 0` 过滤并在卡片注明剔除了哪个月。
6. **不可用的节点**：纽约联储 SOFR/RRP JSON API 返回 404/400（SOFR 改取 FRED）；财政部 Fiscal Data API 各路径 404（日频 TGA 无法接口化，只能用周频 `WDTGAL`）；FRED `TSLTXY`、`FWDILL` 返回 JS 挑战页 HTML。
7. **口径**：`WTREGEN`（TGA 周均）与 `WDTGAL`（周三水位）不同，净流动性用后者；`PPIFD` 在 FRED 已 404，PPI 终端需求用 `WPSFD49201`。

## 8. 安全边界

服务仅绑定 `127.0.0.1`，不监听公网；`/api/fred` 只接受上表白名单键，不代理任意 URL；无鉴权、无持久化、不写入任何凭据；代理地址与端口写在 `config.ini`（只有本机出口端口号，无凭据，可入库），也可用环境变量临时覆盖。

## 9. 待补锚点（已验证可取，尚未接入）

`WRESBAL` 银行准备金余额（净流动性的真正分母）、`DFEDTARL`/`DFEDTARU` 联邦基金目标区间（当前页面仍是写死文字）、`EFFR`、`DFII10` 10Y TIPS 实际利率、`BAMLH0A0HYM2` 高收益债 OAS、`DTWEXBGS` 美元指数（FRED 侧滞后约 8 天），以及 BTC 衍生品资金费率/期货基差（现货价不足以判断需求端变化）。
