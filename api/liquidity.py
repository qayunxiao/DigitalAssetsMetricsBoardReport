# -*- coding: utf-8 -*-
"""全球宏观流动性（Liquidity 子页面）取数模块

路由（由 main.py 挂载）：
  /api/liquidity/health                     模块探活
  /api/liquidity/fred?series=KEY[&force=1]  FRED 官方 CSV（白名单序列）
  /api/liquidity/treasury[?force=1]         美国财政部每日收益率曲线（10Y）
  /api/liquidity/btc[?force=1]              ccxt 多所中位现价 + 120/200 日均线

响应契约与旧版 fetch_server.py 一致（ok/rows/latest/source/unit/cached_at），
仅路径加了 /api/liquidity 前缀。基础设施（代理/缓存/队列/日志）在 api/core.py。
"""
import csv
import io
import statistics
import time
from datetime import date, datetime, timezone

from core import (PROXY, cached, fred_series, gov_lock, log, mkt_lock, one_line,
                  remote, short_err)

try:
    import ccxt                      # 行情/日线取数用（pip install ccxt）
except ImportError:
    ccxt = None

# 白名单：只允许这些官方序列，避免本机变成任意 URL 的转发器
SERIES = {
    "walcl":  ("WALCL",      600,  "百万美元"),
    "tga":    ("WDTGAL",     600,  "百万美元"),
    "rrp":    ("RRPONTSYD",  300,  "十亿美元"),
    "iorb":   ("IORB",       3600, "%"),
    "sofr":   ("SOFR",       300,  "%"),
    "dgs10":  ("DGS10",      300,  "%"),
    "unrate": ("UNRATE",     3600, "%"),
    "ppi":    ("PPIACO",     3600, "指数"),
    "pce":    ("PCEPILFE",   3600, "指数"),
    "cpi":    ("CPILFESL",   3600, "指数"),
    "cpiall": ("CPIAUCSL",   3600, "指数"),
    "ppifd":  ("WPSFD49201", 3600, "指数"),
    "rsafs":  ("RSAFS",      3600, "百万美元"),
}

# 现价取中位数、日线取第一家有 ≥200 根 K 线的交易所；binance/bybit 在本机出口可能被地区封锁，
# 逐个 try 即可，成功者参与中位数（数量随网络状况浮动，页面会显示实际用了哪几家）。
BTC_EX = ["binance", "okx", "bybit", "kraken", "gate", "coinbase"]

TREASURY = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
            "daily-treasury-rates.csv/2026/all?type=daily_treasury_yield_curve"
            "&field_tdr_date_value=2026&_format=csv")

_EX = {}                              # ccxt 交易所实例（load_markets 结果随实例复用）


def _ms(t0):
    return int((time.perf_counter() - t0) * 1000)


def _force(q):
    return q.get("force") == ["1"]


def fred(key, force):
    sid, ttl, unit = SERIES[key]
    out = fred_series("fred:" + key, sid, ttl, force)
    out["unit"] = unit
    return out


def _period_perf(closed, spot):
    """本期以来涨跌幅：以「上一个自然月／季度最后一个收盘价」为基准，基准日期一并回传。"""
    out = {}
    if not closed:
        return out
    ly, lm = closed[-1][0].year, closed[-1][0].month
    lq = (lm - 1) // 3 + 1
    for tag, same in (("m", lambda d: (d.year, d.month) == (ly, lm)),
                      ("q", lambda d: (d.year, (d.month - 1) // 3 + 1) == (ly, lq))):
        for d, c in reversed(closed):
            if not same(d):
                out["perf_" + tag] = round((spot / c - 1) * 100, 2)
                out["perf_" + tag + "_d"] = d.isoformat()
                break
    return out


def _mkex(eid):
    """交易所实例按进程缓存：load_markets() 只在首次调用时发生，否则每次取数都要多花数秒。"""
    ex = _EX.get(eid)
    if ex is None:
        opts = {"timeout": 12000, "enableRateLimit": True,
                "options": {"fetchMarkets": ["spot"]}}
        if PROXY:
            opts["proxies"] = {"http": PROXY, "https": PROXY}
        t0 = time.perf_counter()
        ex = getattr(ccxt, eid)(opts)
        _EX[eid] = ex
        log.info("[btc] 新建 %s 实例（首次调用会 load_markets）%dms", eid, _ms(t0))
    return ex


def btc_bars():
    """日线收盘：一天之内只会真正取一次（缓存键含日期），失败时才重试。"""
    def run():
        bars, frm, errs = [], None, []
        with mkt_lock:
            for eid in BTC_EX:
                t0 = time.perf_counter()
                try:
                    o = _mkex(eid).fetch_ohlcv("BTC/USDT", "1d", limit=260)
                    cb = [(datetime.fromtimestamp(b[0] / 1000, timezone.utc).date(), float(b[4]))
                          for b in o][:-1]          # 去掉当天未收盘的半个点
                    if len(cb) >= 200:
                        bars, frm = [(d.isoformat(), c) for d, c in cb], eid
                        log.info("[btc] 日线取自 %s：%d 根（%s → %s）%dms",
                                 eid, len(cb), cb[0][0], cb[-1][0], _ms(t0))
                        break
                    errs.append("%s: 日线仅 %d 根" % (eid, len(cb)))
                    log.warning("[btc] 日线 %s 根数不足 %d（需 ≥200）%dms", eid, len(cb), _ms(t0))
                except Exception as e:
                    errs.append("%s: %s" % (eid, short_err(e)))
                    log.warning("[btc] 日线 %s 失败 %dms: %s", eid, _ms(t0), short_err(e))
        if not bars:
            log.error("[btc] 全部行情源拿不到 ≥200 根日线，MA120/MA200 与月度涨幅将无法计算")
        return {"ok": bool(bars), "bars": bars, "from": frm, "errs": errs}

    return cached("bars:" + date.today().isoformat(), 6 * 3600, run, False)


def btc(force):
    def run():
        if ccxt is None:
            log.error("[btc] 未安装 ccxt，行情接口不可用（python -m pip install ccxt）")
            return {"ok": False, "error": "未安装 ccxt（python -m pip install ccxt）"}
        t0 = time.perf_counter()
        quotes = []
        with mkt_lock:                       # 并发会被行情源 CDN 拦掉，逐家排队
            for eid in BTC_EX:
                e0 = time.perf_counter()
                try:
                    t = _mkex(eid).fetch_ticker("BTC/USDT")
                    p = float(t.get("last") or t.get("close") or 0)
                    if not p > 1000:
                        raise RuntimeError("非法报价 %s" % p)
                    quotes.append({"n": eid, "p": p})
                    log.info("[btc] 现价 %s = %.2f  %dms", eid, p, _ms(e0))
                except Exception as e:
                    quotes.append({"n": eid, "err": short_err(e)})
                    log.warning("[btc] 现价 %s 失败 %dms: %s", eid, _ms(e0), short_err(e))
        good = [q for q in quotes if q.get("p")]
        if not good:
            log.error("[btc] 全部 %d 家行情源不可达（%dms），沿用旧缓存或页面退回快照",
                      len(quotes), _ms(t0))
            return {"ok": False, "error": "全部 ccxt 行情源不可达: " +
                    " ".join("%s(%s)" % (q["n"], q.get("err")) for q in quotes)}
        spot = statistics.median([q["p"] for q in good])
        spread = max(q["p"] for q in good) - min(q["p"] for q in good)
        log.info("[btc] 中位数现价 %.2f ← %d/%d 家 %s（跨所价差 %.2f）；剔除 %s",
                 spot, len(good), len(quotes), " ".join(
                     "%s=%.0f" % (q["n"], q["p"]) for q in good), spread,
                 " ".join("%s(%s)" % (q["n"], q.get("err")) for q in quotes if not q.get("p")) or "无")

        h = btc_bars()
        closed = [(date.fromisoformat(d), c) for d, c in h.get("bars", [])]
        closes = [c for _, c in closed]

        def avg(k):
            return round(sum(closes[-k:]) / k, 2) if len(closes) >= k else None

        perf = _period_perf(closed, spot)
        out = {"ok": True, "spot": round(spot, 2), "ma120": avg(120), "ma200": avg(200),
               "closes": [round(x) for x in closes[-60:]], "n": len(good),
               "used": [q["n"] for q in good],
               "dropped": ["%s(%s)" % (q["n"], q.get("err")) for q in quotes if not q.get("p")],
               "histFrom": h.get("from"), "histErr": "; ".join(h.get("errs") or []),
               "bars": len(closed), **perf}

        def pos():                        # 与页面判级同一套口径，便于对照日志与卡片
            if not (out["ma120"] and out["ma200"]):
                return "均线不可核验"
            if spot > out["ma120"] and spot > out["ma200"]:
                return "站上双均线"
            return "破 MA200" if spot < out["ma200"] else "破 MA120 未破 MA200"

        log.info("[btc] MA120=%s MA200=%s 均线位置 %s | 日线 %d 根(源 %s) | 本月 %s%% / 本季 %s%% | 总耗时 %dms",
                 out["ma120"], out["ma200"], pos(), len(closed), h.get("from") or "—",
                 perf.get("perf_m", "—"), perf.get("perf_q", "—"), _ms(t0))
        return out

    return cached("btc", 45, run, force)


def treasury(force):
    def run():
        with gov_lock:
            text = remote(TREASURY, tag="treasury")
        rdr = list(csv.reader(io.StringIO(text)))
        if not rdr:
            log.error("[treasury] 空响应")
            return {"ok": False, "error": "空响应"}
        head = [c.strip() for c in rdr[0]]
        if "10 Yr" not in head:
            log.error("[treasury] CSV 无 10 Yr 列，实际表头: %s", " | ".join(head)[:160])
            return {"ok": False, "error": "CSV 无 10 Yr 列"}
        i = head.index("10 Yr")
        rows = []
        for c in rdr[1:]:
            if len(c) <= i or not c[0].strip():
                continue
            try:
                rows.append({"d": c[0].strip(), "y10": float(c[i])})
            except ValueError:
                pass
        # 上游为倒序（最新在前）
        log.info("[treasury] 解析 %d 行  最新 %s = %s%%", len(rows),
                 rows[0]["d"] if rows else "—", rows[0]["y10"] if rows else "—")
        return {"ok": True, "rows": rows[:12], "latest": rows[0] if rows else None}

    return cached("treasury", 300, run, force)


# ---------------------------------------------------------------- 路由

def r_health(q):
    return 200, {"ok": True, "module": "liquidity", "ccxt": ccxt is not None,
                 "series": len(SERIES)}


def r_fred(q):
    k = (q.get("series") or [""])[0]
    if k not in SERIES:
        log.warning("[liquidity] 拒绝白名单外的序列 series=%r", k[:40])
        return 400, {"ok": False, "error": "未知序列，允许: " + ",".join(SERIES)}
    d = fred(k, _force(q))
    return (200 if d.get("ok") else 502), d


def r_btc(q):
    d = btc(_force(q))
    return (200 if d.get("ok") else 502), d


def r_treasury(q):
    d = treasury(_force(q))
    return (200 if d.get("ok") else 502), d


ROUTES = {"health": r_health, "fred": r_fred, "btc": r_btc, "treasury": r_treasury}


def warm():
    """首个 ccxt 请求要为每家交易所 load_markets（实测约 27 秒），启动时预热，页面首屏才不空等。"""
    if ccxt is None:
        log.warning("[warm] liquidity：未安装 ccxt，BTC 卡片将退回快照（python -m pip install ccxt）")
        return
    t0 = time.perf_counter()
    r = btc(True)
    log.info("[warm] liquidity 行情预热%s 用时 %dms  现价=%s 可达源=%d",
             "成功" if r.get("ok") else "失败", _ms(t0),
             r.get("spot") if r.get("ok") else one_line(r.get("error") or ""), r.get("n") or 0)
