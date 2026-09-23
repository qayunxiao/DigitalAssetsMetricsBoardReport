# 哪些指标入库、哪些完全走接口

一句话地图：**只有 BTC 指标页那 12 项是真正落库的数据**，其余页面要么只留执行痕迹，要么每次现打上游。
本文按"落到哪儿"分四层列全，并给出核对方法。行号截至 2026-09-23。

前提（改之前先记住）：`api/db.py` 是**旁路**，不是主路。没装 pymysql、库不通、表没建，都只让
`/api/db/health` 少一项、日志多一行 warning，页面照常有数（所有 `store_*` 吞异常，外层还包一层 `try`）。
表结构只有 `sql/board_schema.sql` 一处定义，改表只改它并升 `board_meta.schema_version`。

---

## A. 进 MySQL：BTC 指标页 12 项，全进

`api/btc.py:747` 的 `STORE_DAILY = set(_KEYS)` 是 12 个 key 的**全集**，没有一项被排除。
写入点 `api/btc.py:793` → `db.store_btc()`（`api/db.py:255`），一轮 summary 写三张表：

| 落库位置 | 写什么 | 受哪个开关管 |
|---|---|---|
| `board_run_log` | 每轮一行：`ok_count/total_count`、`elapsed_ms`、**现价 `spot`**、`kline_src`、`failed_keys`；`lastrowid` 反指给读数当 `run_id` | `[mysql] STORE_BTC` |
| `board_indicator_daily` | 12 行日读数：`value`、`tone`、`verdict`、`src`、`hist_points`、`extras_json`、`error` | 同上 |
| `board_series_daily` | 每张卡 `hist[]` 的迷你历史（≤120 点），`series_key` = `btc:fear` … `btc:sopr` | `[mysql] STORE_SERIES` |

`_stamp()`（`api/btc.py:750`）给每卡盖标识，页面「入库」小标读的就是它：

* `daily+hist` —— 这张卡本轮给了数**且**给了历史点 → 读数 + 序列都写；
* `daily` —— 这张卡**取数失败**（`hist` 为空）。失败行照写：`value=NULL` + `error` 有值。
  这是刻意的，否则"哪天哪个源断了"在库里没有痕迹；
* 序列只在 `store` 含 `hist` 且 `hist` 非空时写（`api/db.py:287` 的子串判断）。

| 指标 key | 名称 | 上游 | 历史序列入库 |
|---|---|---|---|
| `fear` | 恐慌贪婪指数 | alternative.me | ✓ `btc:fng` 取数、`btc:fear` 序列 |
| `ahr999` | AHR999 定投指数 | coinsoto `getAhr999Table` | ✓ |
| `cbbi` | CBBI 牛熊信心指数 | 多源拼装 + 本地自算 | ✓ |
| `cvdd` | CVDD 累计价值币天销毁 | Looknode | ✓（判定还要现价的，靠 `btc:klines`） |
| `ema` / `ema_new` | EMA5/EMA10 交叉（两种播种口径） | **日线自算**（`btc:klines`） | ✓ 存 EMA5 折线，不是 OHLC |
| `kdj` | KDJ(9,3,3) 日线 | 日线自算 | ✓ 存 J 线 |
| `macd` | MACD(12,26,9) 日线 | 日线自算 | ✓ 存 MACD 线 |
| `litb` | Look Into Bitcoin 盈利币占比 | litb.com（该源已废弃，常 502） | ✓ 有数才进，断了就是 `daily` |
| `mvrv` | MVRV 市值/实现市值 | Looknode | ✓ |
| `nupl` | NUPL 净未实现盈亏比 | 由 MVRV 推算（免费档） | ✓ |
| `sopr` | SOPR Z-Score | 由 MVRV 推算，三个 Z 分量只剩 `nupl_z`（Bitbo 实测 401） | ✓ |

`mvrv` / `nupl` / `sopr` 共用同一次 Looknode 取数（`mvrv_rows()`，`api/btc.py:235`），所以库里是三行独立
`series_key`、上游只有一次请求。

## B. 入库，但只存分数与执行痕迹

| 来源 | 表 | 存什么 / 故意不存什么 |
|---|---|---|
| `api/crash.py:246` → `db.store_risk()`（`api/db.py:299`） | `board_risk_score_daily` | 只有 `date + ticker + score`。调用点**没传 `factors`** → `factors_json` 恒为 NULL，因子明细不入库。`data/risk_history.csv` 才是权威（换机迁移带它），库里是同日覆盖的镜像 |
| `api/allocation.py:254` → `db.store_report()`（`api/db.py:316`） | `board_report_run` | 元数据：`kind`、成/败、退出码、`duration_ms`、**stdout 字符数**、当天已用额度、报错摘要。**stdout 正文永不落库** —— 里面是持仓明细与金额，这套库和账号是共享环境 |

## C. 完全不入库，每次现打上游

| 范围 | 接口里的键 |
|---|---|
| **流动性页整页** `/api/liquidity/*` | WALCL、TGA、ETF 流、`bars:<今天>`、`treasury`、`btc` 现价 —— `api/liquidity.py` 从头到尾没 `import db`，一行都不写 |
| 崩盘页的**输入序列** | `crash:fred:dgs2` / `dgs10` / `hyoas` / `mktcap` / `gdp`、`crash:yields`、`crash:fear`、`mkt:<ticker>`（Shiller、巴菲特在 D 层有日缓存，但同样不入库） |
| 资产配置页 | `alloc:fred:dgs3` / `dgs10`、`alloc10:<sym>` 各资产价 |
| BTC 现价与日线本体 | 只有 `run_log.spot` 那一个标量进库，K 线 OHLC 不存 |
| 报告额度 | `data/report_quota.json` 文件态（跨重启不清零），不入库 |

**已知缺口，别照着 schema 注释去查**：`sql/board_schema.sql` 里举了 `price:daily`、`fred:WALCL` 两个
`series_key` 命名空间例子，但**代码里没有任何写手**——那是给以后留的位置。所以现在查库拿不到币价日线，
也拿不到流动性序列。要补就在 `store_btc` 里顺着 `out["spot"]` / `klines()` 加一段，别新表。

## D. 不入库、但同一天不再打上游（磁盘日缓存）

`core.DAY_KEYS`（`api/core.py:258`）白名单之外的一律不缓存到盘；命中就从 `data/daycache/<键>.json` 读，
`force=1` 永远穿透（页头「刷新」与卡片「重试」都带它）。

| 命中日缓存 | 服务的指标 |
|---|---|
| `btc:looknode:mvrv` | mvrv + nupl + sopr（一次取数喂三张卡） |
| `btc:looknode:cvdd` | cvdd |
| `btc:cbbi` / `btc:litb` / `btc:ahr999` / `btc:fng` | cbbi / litb / ahr999 / fear |
| `crash:shiller` / `crash:buffett` | 崩盘页 Shiller CAPE、巴菲特指标 |

**不在名单上**（TTL 过就重新打）：`btc:klines`（900s，日内会变，故意不日缓存）、`alloc*`、`crash:fred:*`、
流动性页全部。开关是 `[cache] day` / `[cache] dir` → 环境变量 `CACHE_DAY` / `CACHE_DIR`。
失败结果永不写盘；这套是"少打上游"，与 A/B 的"留历史"是两条独立的路。

---

## 核对方法

```bash
curl -s http://127.0.0.1:8888/api/db/health      # enabled/reason/switches/tables/version_ok（不回口令账号主机）
python api/db.py --status                        # 同一套信息，命令行版（只读，不建表）
```

`tables` 的读法：`null` = 这张表不存在，数字 = 行数。库里到底该有几行，用 `sql/board_schema.sql` 建表后：
每跑一轮 `/api/btc/summary` → `board_run_log` +1 行、`board_indicator_daily` 同日 12 行 UPSERT、
`board_series_daily` 只在历史点数变化时重写（`_fingerprint`，`api/db.py:290`）。

## 当前实际状态（2026-09-23）

写入路径已接通并离线自证过（桩连接 + 真实生产 payload 重放，23 条语句），但**两边库里都还是 0 行**：

* 本机：`[mysql] HOST=127.0.0.1`、认证已通，表还没建 —— 待跑 `python .\api\db.py --init`；
* 服务器：`--init` 已成功（表在），但 Passenger 内存里仍是旧 `btc.py`（`/api/health` 的 `stale=true`），
  要 `touch tmp/restart.txt` 才换代码。

两步做完，第一笔该是 `board_run_log` 1 行 + `board_indicator_daily` 12 行 + `board_series_daily` 约 120×11 行
（`litb` 那源大概率仍 502，那一格会是 `value=NULL` 的失败行）。
