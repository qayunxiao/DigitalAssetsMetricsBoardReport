# Qoder.md · RealtimeCoreMetricsBoard 项目约定

本文件是给 Qoder（及任何在此目录工作的 agent）的项目说明。**「执行最新宏观审计」是本项目的核心任务**：输入见第 3 节，输出见第 4 节，二者都是硬约束，不是建议。

> **2026-09-22 拓扑变更**：本项目已并入数字资产指标看板，成为三个子模块之一。原独立入口 `main.py` / `fetch_server.py` / `config.ini` / `start_app.bat` 已归档到本目录 `_legacy/`，现行实现是**根目录 `main.py` + `api/core.py`（公共层）+ `api/liquidity.py`**，路由挂 `/api/liquidity/*`，日志为 `<项目根>/logs/board_server.log`。本文件其余纪律（审计规范、判级阈值、硬性纪律、边界）原样适用于整个看板项目。
>
> **2026-09-23 拓扑再变更**：看板的 Windows 工作副本现在**只有这一棵**——`D:\Qorder_ws\DigitalAssetsMetricsBoard`（早期叫法，下文凡出现处均按历史名称理解）已经不存在了，`D:\Qorder_ws\DigitalAssetsMetricsBoardReport` 是唯一事实源，远端 `https://github.com/qayunxiao/DigitalAssetsMetricsBoardReport.git`。别再去那个消失的路径找文件、也别从那儿拷东西回来。

---

## 1. 项目是什么

全球宏观流动性监控与交易决策系统的**本地实时面板**。11 项指标（WALCL、TGA、ON RRP、SOFR、IORB、US10Y、BTCUSD、核心 CPI、PPI 终端需求、失业率/萨姆规则、零售销售）全部由本地服务经代理向官方节点取数，风险判级由页面代码按公开阈值实时生成。

| 项 | 值 |
|---|---|
| 代码目录 | `D:\Qorder_ws\DigitalAssetsMetricsBoardReport`（唯一工作副本，见顶部拓扑说明） |
| 面板地址 | `http://127.0.0.1:8888/Index.html`（主页）；流动性子页 `/staic/Liquidity.html`。外部访问端口 15888 由用户自己的反代／端口映射转发到 8888，本服务只绑 127.0.0.1 |
| 启动 | 本机 Windows：双击根目录 `start_app.bat`（= `python main.py --open`），或 `python main.py`；Linux／FreeBSD（serv00）：`sh start_app.sh`（优先 `/home/myaibtc/vevns/web3/bin/python`，不沿用 Windows 代理）；公网镜像：Passenger 用面板指定解释器 import `passenger_wsgi.py`（见 README 第 7.2 节） |
| 入口 / 服务 / 页面 | 根 `main.py`（本机）或 `passenger_wsgi.py`（公网）→ `api/app.py`（模块注册表）→ `api/core.py`（配置/日志/**两层缓存：进程内 TTL + 磁盘日缓存**/`dispatch()`+`wsgi_app()`/静态）→ 四个取数模块（`btc` / `liquidity` / `crash` / `allocation`）+ 可选落库旁路 `db` → `staic/*.html`（公共层 `staic/common.css`、`staic/common.js` 五页共享，导航表是 `common.js` 的 `PAGES`） |
| 运行配置 | 根目录 `config.ini`（代理 / 端口 / 日志目录与级别 / 页面 `show_fix` / `[server] public` / `[mysql]` 落库）；优先级 环境变量 > `config.ini` > 代码默认，**`[mysql]` 例外**：环境变量 > `local.ini` > `config.ini`，由 `api/db.py` 自己解析 |
| 详细技术文档 | `README.md`（接口契约、判级阈值、实测取数约束、待补锚点；其中 `/api/fred` 等路径现加 `/liquidity` 前缀） |

技术栈：Python 3.11+ 标准库 HTTP 服务（核心链路零 pip 依赖）+ `ccxt`（仅行情，缺失时相关项自动标失败）+ `pymysql`（**仅落库旁路**，`api/db.py` 函数内 import，缺包时整段空转、页面不受影响）+ 单文件原生 HTML/JS（无框架、内联 SVG）。

## 2. 数据链路（改代码前先理解）

```
浏览器页面 ──/api/liquidity/*（同源，绕 CORS）──► api/app.py + api/core.py（本机 main.py 监听 127.0.0.1:8888／公网 passenger_wsgi.py 由 Passenger 调起）──代理（公网版不配代理）──► FRED / 美国财政部 / 交易所
```

FRED、纽约联储、H.4.1 **不返回 CORS 头**：代理能解决网络可达，解决不了 CORS，所以同源中转是必需的，不是可选优化。

| 看板项 | 端点 | 上游标识 | 频率 |
|---|---|---|---|
| ① WALCL | `/api/liquidity/fred?series=walcl` | WALCL | 周（周三） |
| ② TGA | `…series=tga` | WDTGAL | 周（周三水位） |
| ③ ON RRP | `…series=rrp` | RRPONTSYD | 日，次日发布 |
| ④ SOFR / IORB | `…series=sofr` / `iorb` | SOFR / IORB | 日 / 会期 |
| ⑤ US10Y | `/api/liquidity/fred?series=dgs10` 与 `/api/liquidity/treasury` | DGS10 / 财政部曲线 | 日 |
| ⑥ BTCUSD + MA120/MA200 | `/api/liquidity/btc` | ccxt 多所现价中位数 + 日线 | 实时 / 日 |
| ⑦ 核心 CPI / PPI 终需 / 失业率 / 零售 | `…series=cpi` / `ppifd` / `unrate` / `rsafs` | CPILFESL / WPSFD49201 / UNRATE / RSAFS | 月 |
| 补充：PCE / 整体 CPI / 全部商品 PPI | `…series=pce` / `cpiall` / `ppi` | PCEPILFE / CPIAUCSL / PPIACO | 月 |

**BTC 指标页（`staic/btc.html` → `/api/btc/*`）是另一条链路**，别和上面这张表混起来：它的上游是 `alternative.me`（恐慌贪婪）、`colintalkscrypto.com`（CBBI）、`looknode.com`（MVRV / CVDD / AHR999 / 2年MA乘数通道，NUPL 由 MVRV 推算；单值序列回 `v`，通道那条回 `v1`/`v2` 两条线、走 `looknode_band()`，实测 `v1 ≡ 5×v2`）、五家行情站的公开 REST 日 K 线（`binance→kraken→okx→coinbase→bybit`，**不用 ccxt**）、`production.lookintobitcoin.com`；AHR999 后面还挂着 coinsoto / soulbab / 可选 CoinGlass 三条兜底。2026-09-23 实测：AHR999 那三条全不通（握手即被断开 / 530 / 要 Key），当天傍晚改用 looknode 的 `/api/Ahr999` 出数（**这条路径大小写敏感**，小写那次的 404 曾被误记成「looknode 没有这个接口」）；Look Into Bitcoin 自 2024 起废弃（本机代理现在直接拒它的域名），`charts.bitbo.io` 的 `mvrv-z` 与 `sopr` 都回 401——所以后两项在页面上是**带原因的虚线缺口卡**，不是数值卡。上游状态会变，动这块代码前重新探一遍，别把本文件当实时状态表读。

## 3. 提示词输入（每次审计使用的模板）

角色设定：精通全球宏观经济学、影子银行体系与批发级流动性（Wholesale Liquidity）的顶级机构宏观策略师 + 首席风险控制官（CRO）。

```
执行最新宏观审计
```

触发后必须**主动、独立地**向官方节点检索**截止当日**的真实数据，不得复用上一次答案中的数值：

- **严禁使用历史记忆充当实时数据，严禁编造数据。**
- 每项必须标注：来源 + 频率 + 截至时间；**非交易日取最近一个交易日的收盘/公布值**。
- 强制锚点：①WALCL ②TGA ③ON RRP ④SOFR & IORB ⑤US10Y ⑥BTCUSD（**并检查相对 120 日、200 日均线的位置**）⑦宏观数据：最新 PPI、核心 CPI 或 PCE、当前失业率（**检查是否触发萨姆规则**）。
- 检索失败时：继续换官方节点，或明确写入「检索缺口」；**绝不允许静默降级为二手转述或估值**。

## 4. 输出规范（固定三段，顺序与标题不得更改）

**📊 核心指标看板** — 表格：指标 / 当前值 / 变化 / 判级（🔴🟡🟢）/ 来源与截至时间。判级必须与 `macro-liquidity.html` 中的阈值一致（README 第 6 节已逐条列出，可复核）。任一序列缺值时判 🟡，不做乐观推定。

**🔍 底层科学因果链条审计** — 讲清传导链，不写套话：净流动性 `WALCL − TGA − ON RRP`（TGA/RRP 取与 WALCL **同周三**的值）；RRP≈0 ⇒ 减震器消失 ⇒ TGA 回补 1:1 打击准备金；`SOFR − IORB` 利差为**滞后指标**（>+10bp 才报警）；通胀/就业侧口径要写明同比或环比。

**🛠️ 首席风控官操盘动作指引 (SOP Action)** — **黑纸白字的绝对理性建议**，从「加仓 / 持股不动 / 逢高减仓 / 防守清仓」中选一个，附**具体数值触发条件**与**再入场条件**。谢绝任何模糊套话、任何"视情况而定"。

末尾追加 **检索缺口**：逐条列出当日无法从一手来源核验的项，说明已尝试的节点与失败原因。

## 5. 硬性纪律（历史上出过事故，必须遵守）

1. **不要把滞后值冒充实时值。** 2026-09-21 曾用两天前的媒体转述价（$78,000）替代实时 BTC（约 $81,400），直接得出错误结论「反弹受阻」，纠正后结论反转。
2. **纠错要公开，不要静默改写。** 此前写死的「9 月 −1.5% / Q3 +32%」经 ccxt 实算为 +3.86% / +39.21%，已在页面第 ⑦ 节明示并保留原链接作为纠错依据。
3. **交叉核对自算数量。** 红/黄/绿计数必须由代码得出，不得手算：2026-09-21 审计中我手工报成 4/3/3，复核实为 5/3/3；当日面板终态为 5🔴 / 0🟡 / 6🟢。
4. **缺测值必须剔除。** FRED `UNRATE` 的 `2025-10` 记为 `0`（BLS 停摆），不剔除会让萨姆规则 12 个月低点变 0、差值虚高 4.13pp，**误判为已触发**。
5. 其余实测约束（同一上游内串行、FRED 与行情分两条队列、FRED 挂起"请求头过简"的客户端、ccxt 实例必须按进程缓存、binance 451 / bybit 403、不可用节点清单）见 README 第 7 节，改动取数代码前必读。
6. **判断某个值到底是实时的还是快照，看日志不要靠印象**：`<项目根>/logs/board_server.log`（原 `logs/fetch_server.log`）里每次刷新都有 `[http]` 行，每个上游请求有耗时/字节数，退回旧值会写 `[cache] … 沿用 Ns 前的旧值（页面标为快照）`。取数类问题先 grep 这里再下结论。

## 6. 代码约定

- 取数与服务优先用 **Python 标准库**；不为省代码引入重依赖。目前允许的第三方只有两个，且都是**可选 import**：`ccxt`（行情）与 `pymysql`（落库）。加第三个之前先想清楚：包不在的时候页面必须照样打得开。
- 移植/重写服务时**保持 `/api/*` 响应契约不变**，页面即可零改动；不要在仓库里留两份都能跑的实现（旧 Node 版已移出为 `D:\Qorder_ws\server.mjs.legacy-node`）。
- 页面必须**全动态**：新增指标走接口取数，不要在 HTML 里写死数值；静态文字（因果链标签、SOP 数字、综合评级标题）属于待清理项。
- 运行参数（代理、端口、日志目录/级别、页面开关、`[cache] day/dir` 磁盘日缓存、`[mysql]` 落库开关）一律写在根目录 `config.ini`，**不要**在 `main.py`、启动脚本或代码里再写一份默认值；`api/core.py` 的 `apply_config()` 语义是"环境变量已有值就不覆盖"，新增配置项要同时登记 `CONFIG_ENV`、`config.ini` 注释与 README 第 4 节（相对路径要进 `CONFIG_ABS` 才会拼上项目根）。**唯一的例外是 `[mysql]`**：它不进 `CONFIG_ENV`，由 `api/db.py` 自己按「环境 > `local.ini` > `config.ini`」解析，为的是 core 不许去 import 第三方包。监听地址 `127.0.0.1` 故意不做成可配置项。**第二处例外（2026-09-24，用户明示）：`--html-alert` 那三张卡的阈值与每天时刻在 `indicator.ini` 的 `[html_alert_top]` 与 `[html_alert_bottom]` 两段**（顶部往高判、底部往低判，同一次取数、各判各的、各记各的账），读它的是 `api/core.py` 的 `indicator_get()`——它**故意不进 `CONFIG_ENV`**，因为那份文件里同时躺着 `[TG]`/`[dingding]` 的凭据，整段搬进环境变量等于给配置通路开一条能读到密钥的口子；`indicator_get()` 只按「段 + 键」取值，别把它改成遍历全文件。它的三态语义也要保住：**键存在且留空 = 显式停用（返回空串），键/段不存在 = 回代码默认**，把这两态合并成一态就会让他「留空停一项」的写法悄悄变成「恢复默认值」。引用这几个数之前先重读那份文件（他会手改），别照抄 `ALERT_SPEC[...]["defaults"]`。`[proxy]` 段**故意只在 Windows 生效**（`apply_config()` 在非 `nt` 系统跳过）——不要把这条 OS 判断挪到 `config.ini` 里，也不要在启动脚本里再复制一份：Windows 用文件里的本机出口，Unix／FreeBSD 要代理只能显式给环境变量。
- 影响页面显示的开关走**服务端替换 HTML 标记**（`api/core.py` 的 `_static()`——静态分支，原 `do_GET` 已抽成 `dispatch()`——把 `{{SHOW_FIX}}` 换成 `config.ini` 的值），不加 `/api/*` 接口、不在前端拉配置：这样一次刷新就生效、也不会因双击打开文件而白屏（标记未替换时 CSS 不匹配，按默认展示）。目前只有 `[page] show_fix`（控制 ⑧ 数据来源下面的「修订记录」整块 `#revs`）；`show_fix=1` 时标题是 `<button aria-expanded>`，点击收缩 `#revbody`，状态存本机 `localStorage['rev-open']`，且由紧跟块后的内联脚本在首屏绘制前恢复（否则每次刷新会闪出整段历史）——不改写、不删除任何历史记录。（曾经还有一套 `<!-- BEGIN:REPORT_UI -->` 成对剥离机制，2026-09-22 随「持仓报告不再从公网摘掉」一起删净，别再往回加。）
- 判级阈值改动时，**同步更新 README 第 6 节表格**（页面与本文件都引用它）。
- **`api/Crypto/` 是只读口径副本，`D:\Qorder_ws\cryptoTrader` 是它的出处**：2026-09-23 用户把 cryptoTrader 的 `api_list/handle_*.py` 原样抄进本仓库（逐字节一致，已核对），为的是让口径跟着仓库走。两处都**不许改、不许 import**（那些文件 `import numpy/requests/bs4/utils.*`，本服务的零依赖前提会被当场破掉；阈值表 `utils/operationConfig.py` 也在仓库里且已跟踪，但它所有 getter 读的是出处项目的 `config/config.ini`——本仓库没有那个路径，所以它在这儿是**惰性副本**，要看阈值仍去原项目）。副本会随 `git ls-files` 上到公网机器，但 `PUBLIC` 的静态白名单不收 `.py`，浏览器拿不到。移植过来的每一条判级都要在 `api/btc.py` 的对应函数上留 `handle_XXX.py:行号` 注释，页面「口径与阈值」块再抄一份行号，三处对得上才算数。cryptoTrader 改了 `handle_*.py` 时，**重新整份抄、别手工挑改**，免得副本与出处悄悄分叉。
- **上游没给的口径一律不许自己发明**（2026-09-23 定，BTC 指标页为此而生）：AHR999 在 cryptoTrader 里一直是取现成数值，没有可核对的公式，所以本模块宁可让这张卡空着也不自己拼一条 `定投成本×哈希难度` 出来——拍脑袋算的东西会被当成抄底/逃顶信号；MVRV 同理，上游只配了底部那一档（`mvrv_max=[0.95,1.0]`），顶部就**不编一个倍数**。缺就写进「已知缺口（宁缺毋假）」，说明试了哪些节点、为什么不行。**AHR999 的替代源已经穷举过一轮，别重复探**（2026-09-23 实测，结论在 `api/btc.py:ahr999()` 的 docstring 与页面缺口块）：coinsoto/soulbab 域名已死，CoinGlass v4 端点存在且 `CG-API-KEY` 认 Key 但回 `Upgrade plan`，CryptoQuant 整体 403（免费档连 hash-rate 都不给），`capi.coinglass.com`/`open-api.coinglass.com` 对任意路径回空 `success`（**别把它当数据**），bitcoin-data / blockchain.info / btc123 均无 AHR999。**同日修订**：那次把 looknode 一并记成「无 AHR999」是错的——它的接口路径**大小写敏感**，`/api/Ahr999`（与页面 slug 同拼写，不是小写的 `/api/ahr999`）有 5700+ 个点的完整序列，现在就是首选源，「要出数只有两条正路」那句随之作废。不变量本身一条没动：**只取上游算好的现成数值，不自造公式、不拿均值顶替缺项**。
- **口径有两个来源，cryptoTrader 不是唯一的**（2026-09-23 加 `two_year_multiply` 时确立）：这一张卡在 `handle_*.py` 里根本没有对应文件，它的两条线（下沿 730MA、上沿 730MA×5）与判据（现价低于下沿=过度悲观、高于上沿=过度贪婪）全部照抄 looknode 该页「指标描述」原文，连它自己写的「BTC 体量变大后这组回测数值效果可能打折」那句也搬进卡片 note——**上游的免责声明不许悄悄替它抹掉**。这类卡的页面「口径与阈值」出处列写上游 URL 而不是 `handle_*.py:行号`，别为了凑格式编一个行号。另外记一笔 probe 教训：这条 slug 只有与页面完全同拼写的 `twoYearMultiply` 通，大小写变体（含全小写）实测五个都 404——和 AHR999 那次一样，**404 只能说明你敲的路径不对，不能说明上游没有这个接口**。
- **BTC 指标模块故意不用 `core.py` 的 `gov_lock` / `mkt_lock`**：各项分属 6 个互不相干的主机，共用一把队列会让整页排队等最慢的那个源。`api/btc.py` 自己按主机名各一把锁（同主机内串行、跨主机并行），外面再套 `ThreadPoolExecutor(max_workers=5)`。新增同主机接口时沿用 `_host_lock(url)`，别图省事挂回 `gov_lock`。缓存键统一带 `btc:` 前缀，与 liquidity 的 `btc`（ccxt 现价）互不干扰。
- **进 `innerHTML` 的上游文本一律先转义**（`staic/btc.html` 的 `esc()`）：`short_err` 只压掉换行和 URL，截断后的错误串仍可能带尖括号，直接拼进模板就是一处反射型 XSS 面。`setStatus`/`textContent` 那类走 DOM 文本的不用管。放大弹层里的每一个上游字段（标题、判定、`src`/`asof`、`extras`、`note`、错误原因）同样都过 `esc()`，别因为「这是自家算出来的数」就漏。
- **卡片放大是纯前端的事，不许为它多打一次上游**（2026-09-23）：`staic/btc.html` 的放大入口有三个——卡片右上角「⤢ 放大」按钮（单击，看得见的入口）、双击卡片任意位置、Tab 到卡片按 Enter；只有「重试」按钮上的双击被排除（它自己响应单击，别顺手弹层），明细区/判定徽章/迷你图/角标那些区域**全部算放大区**。弹层里的大图画的就是这一张卡在 `summary` 里已经拿到的点，**点开弹层不发请求、不扩窗口**。要更长历史只能改 `api/btc.py` 的抽样目标常量（迷你图与单线放大是 `HIST_POINTS`，通道卡那份三条线是 `BAND_POINTS`；都是**等间隔抽样目标**，实际条数在它附近浮动，别在页面里写死成「最多 120 点」这种断言——页脚只报本卡真实点数，`hist_points` 缺失时连这个数字也不印）。放大图的悬浮读数（十字线 + 气泡）**只绑在 `staic/btc.html` 的 `#z-chart` 容器上，没有下沉到 `lineChart`**：几何量由 `zPaint` 存进 `ZGEO`，换 svg 时元素被 `innerHTML` 清掉，所以监听一次即长期有效。要给别人也加悬浮，先想清楚崩盘页怎么在不触发 `crash/record` 的前提下回归。放大图按 2%~98% 分位截断纵轴只为可读性（MVRV 早期那个 45.92 会把线压平），截断必须在弹层里写明真实全域与落在尺度外的点数——**数据一条不删**，卡片刻度图仍按全域画。
- **色板只有 `common.css` 顶部那两块，页面里不许再写死颜色 hex**（2026-09-24 先锁亮色、当天又决定恢复切换；现在回到双主题）：`:root` 是深色（默认），`html[data-theme=light]` 是那套「冷灰蓝底 + 白卡 + 细网格 + 等宽数字」的亮色，金色只留给品牌与强调，数据线走青蓝（`--blue` / `--blue2` / `--c-hi` / `--c-md` / `--c-lo`）。**两块 token 名单必须逐一对齐**（只有 `--mono` 这类主题无关的允许只写在 `:root`，自定义属性会往下继承），少一个就是另一套主题下渲染成 `unset`；底纹（body 上那两抹 radial-gradient）刻意只挂在 `html[data-theme=light] body` 上，深色保持纯色底。CSS 里一律 `var(--x)`；但**内联 SVG 的 `fill`/`stroke` 属性不吃 `var()`**，所以拼 SVG 的脚本必须在生成时取真值——公共层有 `T('--x')`（`common.js`），页面脚本一律用它，别在模板串里塞 `#f2555a`。取色一旦走 `T()` 就**在生成时固化**，所以切换按钮（`common.js` 的 `initTheme`，状态存 `localStorage['board-theme']`，初值由各页 `<head>` 的内联片段写 `data-theme` 以免闪一下）派发 `themechange` 时，每页都得挂着重画：流动性 `renderAll()`、崩盘与资产配置 `paint`、`btc.html` 是 `paint()`（卡片刻度图 `spark` 也吃 `riskColor`→`T()`，所以整页重画，不再像上一版只在弹层开着时 `zPaint()`）、`Index.html` 是 `btcPaint()`（`BTCJ` 为空时不画，免得抢在首屏前显示成「取数失败」）。**新增任何用 `T()` 取色的图，都要把它接进这一串监听里**，否则切完主题旧图还带着上一主题的色。
- **`common.js` 的 `lineChart` 是共享层，崩盘页四张图也用它，改签名必须后向兼容**（2026-09-24 又动了一次，别照着上一版「lineChart 一行没改」的说法以为它没被碰过）：现在的可选参数是 `dom`（纵轴范围）、`lines=[{rows,color,label}]`（多条线共用一套轴，`v` 非有限值处**断线**，不连过去也不填 0）、`log`（对数纵轴 + 十倍网格线，不足一个数量级自动退回线性）；不传时行为与最初一致。它现在**回传这次真正用到的几何** `{Y, dom, log, w, h, pad}`，因为对数轴的 Y 映射没法在调用方按线性公式猜——**调用方要画十字线就必须用这份回传值**，自己再算一份必然错位。回归范围：全站只有崩盘页那四张图（`USStockCrashMonitor.html:356,360,362,416`，全是单线 + 线性 + 不传 `lines`）和本页用它，改完至少要看那四张没变形；资产配置页与流动性页是另一套画法，不受影响。
- **通道卡（`two_year_multiply`）放大图的三条线**（2026-09-24）：服务端在这一张卡上额外下发 `bands[]`（`{d, lo, hi, px}`），`lo`/`hi` 是 looknode 的两条线，`px` 是 `btc_closes()` 打 Yahoo `BTC-USD` `20y` 拿的日线收盘。三条纪律：① **对齐用「该日或之前最近一个交易日」前向填充**（`bisect`），不是精确等值匹配——Yahoo 的收盘序列会缺根（实测缺了 2026-09-23），精确匹配会让线上最后一点凭空断掉；② **上游没有的日期就是 `null`**（通道起点 2012-07 早于 Yahoo 起点 2014-09），不填 0、不外推，缺口必须在卡片明细与图脚里写明从哪天起、缺几个点；③ 颜色跟**语义**走而不是跟 `tone` 走（绿=支撑、红=压力、黄=现价，写死在 `btc.html`），且**现价线只是画出来好读，判级只看 looknode 那两条线**，别拿它去改 `verdict`。`btc:yahoo:BTC-USD` 不进 `DAY_KEYS`：那条序列的最后一根是今天没收盘的 bar。
- **`api/btc.py` 的 `INDICATORS` 表顺序 = 页面的卡片顺序**（2026-09-24 起，用户把主页标题与品牌位换成「我爱大饼」同日重排了卡片：第一行恐慌贪婪 + AHR999，第二行 2年MA乘数通道 + CBBI，第三行 EMA5/EMA10（新版）+ KDJ，其余七张排在后面）。`summary()` 用 `pool.map` 并行取数但**保序返回**，页面照 `items[]` 原样铺卡，所以前端不存第二份顺序、`staic/btc.html` 的 `RULES`（「口径与阈值」表）要跟着同序改。**新增一张卡就得当场决定排第几**，别只往表尾append了事。每行两张写在 `btc.html` 的 `#grid{grid-template-columns:repeat(2,minmax(0,1fr))}`（覆盖共享的 `.grid`，别改 `common.css`，那页流动性与崩盘页共用它）。**不做每轮随机换序**：页面 15 分钟自动刷一次，随机序会让卡片跳位置，比顺序不好看更糟——要换序就改这张表并提交。
- 白名单只增不减地维护在各模块取数文件（`api/liquidity.py` 的 `SERIES`、`api/crash.py`、`api/allocation.py`、`api/btc.py` 的 `_KEYS`）；新增官方序列要同时加缓存 TTL（日频 300s / 周频 600s / 月频 3600s）。跨模块共用的序列（DGS10、BAMLH0A0HYM2）刻意用相同缓存键去重。
- **磁盘日缓存（`core.cached()` 的第二层，README 7.4）的两条纪律**：① 「今天取过就不再打上游」只对 `DAY_KEYS` 里那批**日频键**开，判断用的是**取数那天的日历日**而不是数据自带的 asof（looknode 的 asof 通常是昨天，用它当判据等于天天穿透）；盘中还会变的键（FRED、K 线现价、收益率曲线、`alloc10:*`）只能享受②失败兜底，把它们塞进 `DAY_KEYS` 就是拿当天的新值换一个好看的命中率数字，不许。② **失败结果一律不落盘**——2026-09-23 那天 AHR999 三条上游全挂，失败结果要是落了盘就会被钉一整天，把傍晚补上的那条 looknode 路也一起挡掉。任何新增层都不许改变 `force=1` 的穿透语义（页头刷新/卡片重试全靠它），也不许让磁盘读写成为取数路径的异常来源（写盘失败只记 debug）。

## 7. 边界（未经明示不得执行）

- **默认不部署、不发布、不上线**：不调用 `prepare_site` / `publish_site`（Qoder Sites 那条路一直没走）。**例外**：2026-09-22 用户明示要把本项目部署到 serv00（`myaibtc.serv00.net`，python 站点类型 = Passenger WSGI），因此新增只读公网镜像 `passenger_wsgi.py`；除此之外不要自行发布或改站点面板设置。
- **不 `git add` / `commit` / `push`**（提交与推送由用户自己做；本树远端 `https://github.com/qayunxiao/DigitalAssetsMetricsBoardReport.git`）。
- 本机版服务**只能绑定 `127.0.0.1`**，`/api/*` 只接受白名单键，绝不能变成任意 URL 转发器；不写鉴权、不持久化、不写入任何凭据；代理地址只出现在 `config.ini`（本机出口端口，无凭据）或环境变量，不散落到代码与启动脚本里。
- **口令的优先级与去处**：`[mysql] PASSWD` 由 `api/db.py` 自己解析，顺序是 **环境变量 `MYSQL_PASSWD` > `local.ini` > `config.ini`**；其余第三方 Key（`COINGLASS_KEY`）**只走环境变量**，`CONFIG_ENV` 里故意没有它。2026-09-23 的实况：用户要把 `[mysql]` 留在 `config.ini` 里方便本机跑，所以那段口令此刻就在一个 git 跟踪文件里——**提交前把 `PASSWD =` 清空**是他的动作，我们别代他改口，也别在聊天／日志／`/api/db/health` 里回显它（健康接口连主机名与账号都不回）。同日还核对过：这段 `[mysql]` 当时**尚未**进过任何历史提交，所以那时不必轮换。**2026-09-24 复测已经不成立**：`git show origin/main:config.ini` 里能查到那行 `PASSWD`（来自 `63b9101`），口令此刻在公开远端上，「提交前清空」这句对历史无效了——轮换或清历史是他的动作。**2026-09-24 更正 + 改口**：上一版写的「`indicator.ini` 已 gitignore」是**错的**——它早在 `63b9101` 就被跟踪（`git ls-files -s indicator.ini` 有输出，`in HEAD: yes`），gitignore 只挡未跟踪文件，所以那批凭据（CoinGlass/CryptoQuant Key、钉钉 3 组 SECRET+TOKEN、TG 两个 BOT_TOKEN、TradingView 口令）**已经在公开的 `origin/main` 里**，而且 `deploy_app.sh` 按 `git ls-files` 铺文件时它不在跳过清单上，等于也上了 serv00 那台机器。同一日用户**明示**把 `[dingding]` 与 `[TG]` 两段以明文并进 `config.ini`（原话：确认要把明文密钥写进 config.ini 并提交到公开仓库，之后 BTC 指标要发 TG 需要这个功能），所以「不许进 config.ini」这条老规矩对这两段**不再成立**；剩下的不可退让部分记在下一条边界里。要真把 `indicator.ini` 挡住，得他自己跑 `git rm --cached indicator.ini` 再提交，并且轮换那批令牌（删文件收不回历史）。
- **推送出口 `api/notify.py`（2026-09-24 新建）的四条规矩**：明文密钥进 `config.ini` 是用户当日明示的例外，例外只到「值放在那个文件里」为止，下面四条一条不许松动。① **任何接口都不许回显 token**：`/api/*`、`/api/db/health`、`notify.health()` 一律只报「配齐了没」或缺什么，页面与日志里也不许出现完整令牌；`_api()` 打的是 `https://api.telegram.org/bot<token>/sendMessage`，URL 本身带令牌，所以**出错时只记 method 与返回体**，别把 URL 塞进 `log()`。② **默认路径不发信**。CLI 不带 `--send` 只做 `getMe` + 正文预览；`--text` 那条带 `--send` 还**必须**带 `--bot`（QA / ALVIN），缺就退出码 2 拒绝——2026-09-23 那三次误发就是因为「测试请求」撞上了一个已经变成真的桩，探针必须先证明自己没有副作用。（`--btc` / `--html-alert` 两条不带 `--bot` 时用 `[notify] tg_bot` 那一个机器人，不会同时落到两个群。）③ **不新增「点了就发」的 HTTP 路由**：现在全站真发信的只有命令行三条加那两个按钮——持仓报告（`/api/allocation/report`，README 第 5 节）、`python api/notify.py --btc --send`（极值播报）、`python api/notify.py --html-alert --send`（三张卡定时播报，口径见 README 4.1）。BTC 播报的口径 2026-09-24 已定并落地在 `api/notify.py`：只看 `BTC_WATCH` 四张卡（`two_year_multiply`/`fear`/`ahr999`/`cbbi`，即有明确极值档的那几张），触发条件就是卡片自己算好的 `tone ∈ {green, red}`（**播报层不重算阈值**，第二份口径必然与 `btc.py` 分叉），一次事件一条消息、没有命中就什么都不发，闸门是「同一 `(机器人, 业务日)` 一条」+「`[notify] daily_limit` 封顶」，且**只在真发成功后**才写 `data/notify_state.json`（预览不扣额度）。业务日用命中项最新的 `asof` 而不是跑脚本那天：上游整天不更新时，用当天当键会让同一条极值在群里刷成一串。要改这套口径 = 同时改 README 第 4 节那张表，别只改代码。
  另记 `--html-alert` 那条的三条纪律（2026-09-24，与极值播报是**互不消耗**的两条链路）：**闸门走在取数前面**（cron 每分钟拉起一次，没到点／当天已评过时连上游都不打，否则一天几百次 `btc.summary()` 会把上游打爆）；**一个日历日只评一次，没触发也要记「今天评过了」**，但这份记录**只在 `--send` 那条路上写**——预览与失败都不记，「看一眼配置就把当天该播的哑掉」和「一次 429 就把这天判死」都是不能接受的；**取不到数的项占 `ALERT_HITS` 的额**（写着 3 就是三项都要成立），宁缺不估，代价是某项长期挂掉会让这条播报长期沉默，所以缺口必须打印出来、要放宽只能改 ini 里的数，不许在判定里给缺数硬编分支。④ 令牌走 `CONFIG_ENV`（环境变量 > `config.ini`，空值跳过），**不在代码里硬编码兜底值**；正文超 4096 按 Telegram 上限截断，不设 `parse_mode`（裸 `_` 与 `<` 会 400）。出口仍是 `core.PROXY`，公网机器上 `[proxy]` 被 `win_only` 跳过，所以 serv00 直连。
- **落库是旁路，不是主路**（`api/db.py` + `sql/board_schema.sql`，README 7.3）：没装 `pymysql`、库不通、表没建，都只让 `/api/db/health` 少一项、日志多一行 warning，**页面链路一律照常**——所有 `store_*` 吞异常，取数末尾那一行调用外面还包了一层 `try`。三条不可回退的口径：① 每个写入按业务日 UPSERT（页面 15 分钟自动刷一次，不幂等就等于把历史曲线写成重复行的垃圾堆）；② 表结构是长表，新增指标不改 DDL；③ **持仓报告的 stdout 一个字符都不进库**，共享库里只存元数据。卡片上的 `store` 字段（页面「⌗ 入库」标）是这套东西的唯一可视口径，`btc._stamp` 与 `db.store_btc` 两处判断必须对得上。
- `utils/`（cryptoTrader 的 `utils/` 只读副本，含 `operationMysql.py`）与 `api/Crypto/` 同一规矩：**不 import、不改**。那份 2019 年的封装在本仓库里跑不起来，三条实测理由记在 README 7.3 末段（`getMysqlConfig()` 那个方法不存在、它读的 `config/config.ini` 没有、`import` 期就要 pymysql 且写完即关连接）；要落库走 `api/db.py`，别照抄它。
- 公网版（`PUBLIC=1`）的硬约束，改代码时不能破：静态只放 `STATIC_ALLOW` 里的前端后缀，路径穿越 400；不走本机代理（`[proxy]` 与 `[report] python` 这类 Windows 绝对路径在非 nt 系统由 `apply_config` 直接跳过）；**任何密钥都不许进 `config.ini` 或上传包，也不许出现在聊天里**（**2026-09-24 用户明示放宽到 `config.ini`**：`[dingding]` `[TG]` 两段以明文入库并随上传包上到公网机器，理由见上一条；放宽**仅限那两段的读取**，「不出现在聊天／日志／接口回显里」照旧有效，新凭据仍要先问）。持仓报告在 2026-09-22 一天内改了两次口径，最终结论是：**公网版本机版同一口径，按钮都显示、点了就执行，不设访问凭据**（用户原话：报告本来就发到他的 Telegram），唯一约束是 `[report] daily_limit`（加密，默认 3 次/天）与 `us_daily_limit`（美股，默认 2 次/天）两个独立计数与报表串行锁；`kind=us` 从 2026-09-23 起与 `kind=crypto` 同一套流程（跑 `tests/runningStorcksOrder.py`），不再是 501 桩。同日还定了**成功后的前端呈现**：右下角弹框一句「已发送 · 报表已推送到 Telegram」3 秒自动消失，不再往页面里铺一整块「持仓报告 · 脚本输出」；同日（2026-09-23）更进一步：连按需展开的那块也删净了——状态行的「查看报表」链接、失败弹框的「看输出」与 `#rpt-panel` 弹层全部移除，页面上任何时候都不出现后端脚本的 stdout，只看 Telegram 上的报表正文（接口照旧回传 stdout，前端不渲染；失败只剩 `error` 摘要一行）。曾经的 `PRIVATE_ROUTES` 整条摘除、`REPORT_UI` 标记剥离、以及随后的 `?key=` 令牌门**都已删净，别再往回加**。除此之外公网版没有鉴权与限流，别往这条链路上加任何敏感动作。
- 公网托管要保持实时就得服务端同源中转（Passenger WSGI 已经同源）；纯静态上传会静默退回内置快照。机房 IP 被官方源拦（429/451）时页面如实标注失败，不许拿旧值冒充实时。

## 8. 已知待办（已提出、尚未获授权执行）

- 接入已验证可取的锚点：`EFFR`、`DFII10`（10Y 实际利率）、`BAMLH0A0HYM2`（高收益债 OAS）、`DTWEXBGS`（美元指数）已由 `api/allocation.py` 的 `/api/allocation/macro` 接入并在资产配置页展示；`WRESBAL`（银行准备金，净流动性的真正分母，用于替换推算公式）、`DFEDTARL`/`DFEDTARU`（目标区间，目前仍是写死文字）尚未接入流动性页看板。
- BTC 衍生品资金费率 / 期货基差（ccxt derivatives）——现货价不足以支撑「需求端失血」类判断。
- BTC 指标页的缺口（2026-09-23 建页时如实标注）：**AHR999 当天已补上**，走 looknode `/api/Ahr999`（见上面那条「别重复探」里的同日修订），不再是缺口；仍未解决的还有 SOPR Z-Score（需要第二个可用分量才名副其实，现在只有 `nupl_z`，`charts.bitbo.io` 那两个接口 401）与 CBBI 的 9 个子指标（只有最新值没有历史，画不出子指标趋势）。这几项**都不许用估算值填平**。
- 清理页面剩余写死文字，含综合评级标题（约第 212 行）改由代码得出。

## 9. Liquidity.html 原始提示词 BY Hello清风 @ 七巨头群友
-  Role
   你是一位精通全球宏观经济学、影子银行体系与批发级流动性（Wholesale Liquidity）的顶级机构宏观策略师与首席风险控制官（CRO）。你的核心任务是利用你的【实时网络搜索/联网工具】，自动化检索最新的官方宏观经济数据，运行“全球宏观流动性监控与交易决策系统”。

    # Instructions for Live Data Retrieval (实时检索规范)
    每当我发出触发指令（如“执行最新宏观审计”）时，你必须【主动且相互独立地】检索以下官方节点或权威财经数据库，获取截止到今天（当前最新）的真实数据。严禁使用历史记忆，严禁编造数据。如果遇到非交易日，请取最近一个交易日的闭盘/公布数据。
    
    ### 数据源与检索锚点：
    1. 【美联储总资产 (WALCL)】：检索圣路易斯联储 FRED 数据库最新值。
       2. 【TGA 余额 (WTGANN)】：检索美国财政部（U.S. Treasury General Account）或 FRED 最新值。
       3. 【ON RRP 余额 (RRPONTSYD)】：检索纽约联储（New York Fed）或 FRED 最新隔夜逆回购释放余额。
       4. 【SOFR 利率 & IORB 利率】：检索纽约联储（New York Fed）公布的最新隔夜担保融资利率，以及美联储最新准备金利率（Interest on Reserve Balances）。
       5. 【US10Y】：检索全球金融市场（如 CNBC, Bloomberg）最新的 10年期美国国债收益率。
       6. 【BTCUSD】：检索当前最新的比特币现货价格，并检查其相对于 120日和200日均线（MA）的位置。
       7. 【宏观数据】：检索本月或最近一周公布的最新 PPI（生产者价格指数环比/同比）、核心 CPI 或 PCE 数据、以及当前失业率（检查是否触发萨姆规则）。
    
    # Workflow & Output Layout (输出格式要求)
    检索完成后，你必须严格按照以下三步结构输出审计报告：
    
    ## 1. 📊 今日实时宏观流动性核心指标看板
    以表格形式完整列出上述指标：【指标名称】 | 【实时最新数据】 | 【边际变化趋势/近期阻力位】 | 【风险状态评级（🔴高危/🟡中性/🟢安全）】。
    
    ## 2. 🔍 底层科学因果链条审计
    - 【净流动性测算】：计算最新：[美联储总资产] - [TGA余额] - [ON RRP余额]。并判断其与股市高位是否出现“量价背离”。
      - 【管道压力测试】：计算 [SOFR - IORB] 的真实利差，分析影子银行和回购市场是否缺钱。
      - 【末端金丝雀分析】：根据 BTC 动量、美债收益率及通胀数据，评估高风险资产的资金流出压力。
    
    ## 3. 🛠️ 首席风控官操盘动作指引 (SOP Action)
    给出系统综合风险评级，并给出黑纸白字的绝对理性操作建议（加仓/持股不动/逢高减仓/防守清仓），谢绝任何模糊的套话。
    
    ---
    请在收到本系统指令后，执行一次全网搜索，以当前最新数据为我输出第一期【实时宏观流动性审计报告】。
     