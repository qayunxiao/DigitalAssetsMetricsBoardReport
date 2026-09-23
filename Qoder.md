# Qoder.md · RealtimeCoreMetricsBoard 项目约定

本文件是给 Qoder（及任何在此目录工作的 agent）的项目说明。**「执行最新宏观审计」是本项目的核心任务**：输入见第 3 节，输出见第 4 节，二者都是硬约束，不是建议。

> **2026-09-22 拓扑变更**：本项目已并入 `D:\Qorder_ws\DigitalAssetsMetricsBoard`（数字资产指标看板），成为三个子模块之一。原独立入口 `main.py` / `fetch_server.py` / `config.ini` / `start_app.bat` 已归档到本目录 `_legacy/`，现行实现是**根目录 `main.py` + `api/core.py`（公共层）+ `api/liquidity.py`**，路由挂 `/api/liquidity/*`，日志为 `<项目根>/logs/board_server.log`。本文件其余纪律（审计规范、判级阈值、硬性纪律、边界）原样适用于整个看板项目。

---

## 1. 项目是什么

全球宏观流动性监控与交易决策系统的**本地实时面板**。11 项指标（WALCL、TGA、ON RRP、SOFR、IORB、US10Y、BTCUSD、核心 CPI、PPI 终端需求、失业率/萨姆规则、零售销售）全部由本地服务经代理向官方节点取数，风险判级由页面代码按公开阈值实时生成。

| 项 | 值 |
|---|---|
| 代码目录 | `D:\Qorder_ws\DigitalAssetsMetricsBoard` |
| 面板地址 | `http://127.0.0.1:8888/Index.html`（主页）；流动性子页 `/staic/Liquidity.html`。外部访问端口 15888 由用户自己的反代／端口映射转发到 8888，本服务只绑 127.0.0.1 |
| 启动 | 本机 Windows：双击根目录 `start_app.bat`（= `python main.py --open`），或 `python main.py`；Linux／FreeBSD（serv00）：`sh start_app.sh`（优先 `/home/myaibtc/vevns/web3/bin/python`，不沿用 Windows 代理）；公网镜像：Passenger 用面板指定解释器 import `passenger_wsgi.py`（见 README 第 7.2 节） |
| 入口 / 服务 / 页面 | 根 `main.py`（本机）或 `passenger_wsgi.py`（公网）→ `api/app.py`（模块注册表，公网在此剔除私有路由）→ `api/core.py`（配置/日志/缓存/`dispatch()`+`wsgi_app()`/静态）→ 三个取数模块 → `staic/*.html`（公共层 `staic/common.css`、`staic/common.js` 四页共享） |
| 运行配置 | 根目录 `config.ini`（代理 / 端口 / 日志目录与级别 / 页面 `show_fix` / `[server] public`）；优先级 环境变量 > `config.ini` > 代码默认 |
| 详细技术文档 | `README.md`（接口契约、判级阈值、实测取数约束、待补锚点；其中 `/api/fred` 等路径现加 `/liquidity` 前缀） |

技术栈：Python 3.11+ 标准库 HTTP 服务（零 pip 依赖）+ `ccxt`（仅行情）+ 单文件原生 HTML/JS（无框架、内联 SVG）。

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

- 取数与服务优先用 **Python 标准库**；不为省代码引入重依赖。
- 移植/重写服务时**保持 `/api/*` 响应契约不变**，页面即可零改动；不要在仓库里留两份都能跑的实现（旧 Node 版已移出为 `D:\Qorder_ws\server.mjs.legacy-node`）。
- 页面必须**全动态**：新增指标走接口取数，不要在 HTML 里写死数值；静态文字（因果链标签、SOP 数字、综合评级标题）属于待清理项。
- 运行参数（代理、端口、日志目录/级别、页面开关）一律写在根目录 `config.ini`，**不要**在 `main.py`、启动脚本或代码里再写一份默认值；`api/core.py` 的 `apply_config()` 语义是"环境变量已有值就不覆盖"，新增配置项要同时登记 `CONFIG_ENV`、`config.ini` 注释与 README 第 2.5 节。监听地址 `127.0.0.1` 故意不做成可配置项。`[proxy]` 段**故意只在 Windows 生效**（`apply_config()` 在非 `nt` 系统跳过）——不要把这条 OS 判断挪到 `config.ini` 里，也不要在启动脚本里再复制一份：Windows 用文件里的本机出口，Unix／FreeBSD 要代理只能显式给环境变量。
- 影响页面显示的开关走**服务端替换 HTML 标记**（`api/core.py` 的 `_static()`——静态分支，原 `do_GET` 已抽成 `dispatch()`——把 `{{SHOW_FIX}}` 换成 `config.ini` 的值），不加 `/api/*` 接口、不在前端拉配置：这样一次刷新就生效、也不会因双击打开文件而白屏（标记未替换时 CSS 不匹配，按默认展示）。目前只有 `[page] show_fix`（控制 ⑧ 数据来源下面的「修订记录」整块 `#revs`）；`show_fix=1` 时标题是 `<button aria-expanded>`，点击收缩 `#revbody`，状态存本机 `localStorage['rev-open']`，且由紧跟块后的内联脚本在首屏绘制前恢复（否则每次刷新会闪出整段历史）——不改写、不删除任何历史记录。（曾经还有一套 `<!-- BEGIN:REPORT_UI -->` 成对剥离机制，2026-09-22 随「持仓报告不再从公网摘掉」一起删净，别再往回加。）
- 判级阈值改动时，**同步更新 README 第 6 节表格**（页面与本文件都引用它）。
- 白名单只增不减地维护在各模块取数文件（`api/liquidity.py` 的 `SERIES`、`api/crash.py`、`api/allocation.py`）；新增官方序列要同时加缓存 TTL（日频 300s / 周频 600s / 月频 3600s）。跨模块共用的序列（DGS10、BAMLH0A0HYM2）刻意用相同缓存键去重。

## 7. 边界（未经明示不得执行）

- **默认不部署、不发布、不上线**：不调用 `prepare_site` / `publish_site`（Qoder Sites 那条路一直没走）。**例外**：2026-09-22 用户明示要把本项目部署到 serv00（`myaibtc.serv00.net`，python 站点类型 = Passenger WSGI），因此新增只读公网镜像 `passenger_wsgi.py`；除此之外不要自行发布或改站点面板设置。
- **不 `git add` / `commit` / `push`**（远端 `github.com/qayunxiao/RealtimeCoreMetricsBoard`，目前 0 提交）。
- 本机版服务**只能绑定 `127.0.0.1`**，`/api/*` 只接受白名单键，绝不能变成任意 URL 转发器；不写鉴权、不持久化、不写入任何凭据；代理地址只出现在 `config.ini`（本机出口端口，无凭据）或环境变量，不散落到代码与启动脚本里。
- 公网版（`PUBLIC=1`）的硬约束，改代码时不能破：静态只放 `STATIC_ALLOW` 里的前端后缀，路径穿越 400；不走本机代理（`[proxy]` 与 `[report] python` 这类 Windows 绝对路径在非 nt 系统由 `apply_config` 直接跳过）；**任何密钥都不许进 `config.ini` 或上传包，也不许出现在聊天里**。持仓报告在 2026-09-22 一天内改了两次口径，最终结论是：**公网版本机版同一口径，按钮都显示、点了就执行，不设访问凭据**（用户原话：报告本来就发到他的 Telegram），唯一约束是 `[report] daily_limit`（加密，默认 3 次/天）与 `us_daily_limit`（美股，默认 2 次/天）两个独立计数与报表串行锁；`kind=us` 从 2026-09-23 起与 `kind=crypto` 同一套流程（跑 `tests/runningStorcksOrder.py`），不再是 501 桩。同日还定了**成功后的前端呈现**：右下角弹框一句「已发送 · 报表已推送到 Telegram」3 秒自动消失，不再往页面里铺一整块「持仓报告 · 脚本输出」（那块只留按需展开：状态行的「查看报表」链接、失败弹框的「看输出」）。曾经的 `PRIVATE_ROUTES` 整条摘除、`REPORT_UI` 标记剥离、以及随后的 `?key=` 令牌门**都已删净，别再往回加**。除此之外公网版没有鉴权与限流，别往这条链路上加任何敏感动作。
- 公网托管要保持实时就得服务端同源中转（Passenger WSGI 已经同源）；纯静态上传会静默退回内置快照。机房 IP 被官方源拦（429/451）时页面如实标注失败，不许拿旧值冒充实时。

## 8. 已知待办（已提出、尚未获授权执行）

- 接入已验证可取的锚点：`EFFR`、`DFII10`（10Y 实际利率）、`BAMLH0A0HYM2`（高收益债 OAS）、`DTWEXBGS`（美元指数）已由 `api/allocation.py` 的 `/api/allocation/macro` 接入并在资产配置页展示；`WRESBAL`（银行准备金，净流动性的真正分母，用于替换推算公式）、`DFEDTARL`/`DFEDTARU`（目标区间，目前仍是写死文字）尚未接入流动性页看板。
- BTC 衍生品资金费率 / 期货基差（ccxt derivatives）——现货价不足以支撑「需求端失血」类判断。
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
     