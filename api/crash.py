# -*- coding: utf-8 -*-
"""美股崩盘风险监测（USStockCrashMonitor 子页面）取数模块

自原 Streamlit 版（api/USStockCrashMonitor/，已归档 _legacy/）移植为零依赖标准库实现。
原实现依赖 streamlit/yfinance/pandas/numpy/akshare；本版全部改为官方 JSON/CSV 端点：

  /api/crash/market?ticker=VOO|QQQ   ETF 日线收盘 + 200 日均线（Yahoo chart API）
  /api/crash/yields                  2Y/10Y 现值与 10Y-2Y 利差历史（CNBC 实时 → FRED 降级）
  /api/crash/credit                  高收益债 HY OAS 现值 + 5 年历史（FRED BAMLH0A0HYM2，免 key）
  /api/crash/shiller                 席勒市盈率最新值 + 历史（multpl.com）
  /api/crash/buffett                 巴菲特指标（gurufocus 抓取 → FRED 计算降级）
  /api/crash/fear                    CNN 恐慌与贪婪指数现值 + 1 年历史
  /api/crash/record?ticker&score     页面当日评分累积到 data/risk_history.csv（同日覆盖）
  /api/crash/history?ticker          风险评分历史（趋势图）
  /api/crash/health                  模块探活

六因子评分（risk_model v1.3：分位数 + 非线性 + 共振 + 红线托底）按本项目「判级由
页面代码按公开阈值实时生成」的约定移植到 staic/common.js，服务端只回原始因子。
"""
import csv
import json
import os
import re
from datetime import date, datetime, timezone

import db
from core import (ROOT, cached, downsample, fred_series, gov_lock, log, one_line, remote,
                  sma, yahoo_bars)

TICKERS = ("VOO", "QQQ")
HISTORY_FILE = os.path.join(ROOT, "data", "risk_history.csv")

# 巴菲特指标口径校准系数：FRED NCBEILQ027S(全口径公司权益)/GDP ≈ 255%（偏大），
# gurufocus 标准口径 ≈ 232.9%，FRED 换算时乘以该系数对齐业界口径。
BUFFETT_CAL_FACTOR = 232.9 / 255.0

CNBC_2Y = ("https://quote.cnbc.com/quote-html-webservice/restQuote/"
           "symbolType/symbol?symbols=US2Y&requestMethod=itv&noform=1"
           "&partnerId=2&fund=1&exthrs=1&output=json")
CNN_FG = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
MULTPL = "https://www.multpl.com/shiller-pe"
GURUFOCUS = "https://www.gurufocus.com/stock-market-valuations.php"


def _force(q):
    return q.get("force") == ["1"]


def _ticker(q):
    t = (q.get("ticker") or ["VOO"])[0].upper()
    return t if t in TICKERS else "VOO"


# ---------------------------------------------------------------- 行情（Yahoo）

def market(ticker, force):
    def run():
        with gov_lock:
            out = yahoo_bars(ticker, tag="crash-mkt")
        if not out.get("ok"):
            return out
        rows = out["rows"]
        out.update(ticker=ticker, sma200=sma(rows, 200), sma50=sma(rows, 50))
        return out

    return cached("mkt:" + ticker, 300, run, force)


# ---------------------------------------------------------------- 利率（CNBC → FRED）

def yields(force):
    def run():
        out = {"ok": True, "sources": {}}
        d2 = fred_series("crash:fred:dgs2", "DGS2", 300, False, days=400, tag="fred:crash")
        d10 = fred_series("crash:fred:dgs10", "DGS10", 300, False, days=400, tag="fred:crash")
        if not (d2.get("ok") and d10.get("ok")):
            return {"ok": False, "error": "FRED DGS2/DGS10 取数失败"}
        u2, u10 = d2["rows"], d10["rows"]
        out["us2y"] = u2[-1]
        out["us10y"] = u10[-1]
        out["sources"]["us2y"] = d2["source"]
        out["sources"]["us10y"] = d10["source"]
        # CNBC 实时报价可用时覆盖 2Y 现值（FRED 为次日发布）
        try:
            with gov_lock:
                j = remote(CNBC_2Y, as_json=True, tag="cnbc:us2y", browser_ua=True,
                           headers={"referer": "https://www.cnbc.com/"})
            q = j["FormattedQuoteResult"]["FormattedQuote"][0]
            last = float(str(q.get("last", "")).replace("%", "").strip())
            if 0 < last < 10:
                out["us2y"] = {"d": date.today().isoformat(), "v": last}
                out["sources"]["us2y"] = "CNBC 实时"
        except Exception as e:
            log.warning("[yields] CNBC 2Y 不可用，沿用 FRED DGS2：%s", one_line(e)[:80])
        m10 = {r["d"]: r["v"] for r in u10}
        spread = [{"d": r["d"], "v": round(m10[r["d"]] - r["v"], 3)}
                  for r in u2 if r["d"] in m10]
        out["spreadHistory"] = downsample(spread, 5)
        log.info("[yields] 2Y=%s 10Y=%s 利差 %s（历史 %d 点）",
                 out["us2y"]["v"], out["us10y"]["v"],
                 round(out["us10y"]["v"] - out["us2y"]["v"], 3), len(out["spreadHistory"]))
        return out

    return cached("crash:yields", 300, run, force)


# ---------------------------------------------------------------- 信用利差（FRED）

def credit(force):
    d = fred_series("crash:fred:hyoas", "BAMLH0A0HYM2", 3600, force, days=5 * 365,
                    tag="fred:crash")
    if d.get("ok") and d.get("rows"):
        d["history"] = [r["v"] for r in downsample(d["rows"], 4)]
        d["current"] = d["rows"][-1]["v"]
        del d["rows"]
        log.info("[credit] HY OAS 现值 %s%%，历史 %d 点（5 年分位用）",
                 d["current"], len(d["history"]))
    return d


# ---------------------------------------------------------------- 席勒 PE（multpl）

def shiller(force):
    def run():
        try:
            with gov_lock:
                html = remote(MULTPL, tag="multpl", expect_html=True, headers={
                    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        except Exception as e:
            return {"ok": False, "error": "multpl 抓取失败: " + one_line(e)[:120]}
        # 主方案：页面顶部 "Current Shiller PE Ratio is XX.XX"（原 Streamlit 版实测可用）
        m = re.search(r"Current Shiller PE Ratio[^0-9]*?(\d+\.?\d*)", html, re.I)
        v = None
        if m:
            v = float(m.group(1))
        else:
            cands = [float(c.replace(",", "")) for c in
                     re.findall(r"<t[dh][^>]*>\s*([\d,]+\.?\d*)\s*</t[dh]>", html)
                     if c.replace(",", "").replace(".", "").isdigit()]
            v = next((c for c in cands if 5.0 < c < 100.0), None)   # 合理区间过滤
        if v is None:
            log.error("[shiller] 解析失败，页面结构可能已变")
            return {"ok": False, "error": "multpl 解析失败"}
        log.info("[shiller] 最新值 %s", v)
        return {"ok": True, "latest": {"d": date.today().isoformat(), "v": v},
                "source": "multpl.com"}

    return cached("crash:shiller", 6 * 3600, run, force)


# ---------------------------------------------------------------- 巴菲特指标

def buffett(force):
    def run():
        # 一级：gurufocus 标准口径抓取（免 key）
        try:
            with gov_lock:
                html = remote(GURUFOCUS, tag="gurufocus", expect_html=True, headers={
                    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            m = re.search(r"[Tt]otal\s*[Mm]arket[^%]{0,150}?(\d{2,3}\.\d)\s*%", html) \
                or re.search(r"[Bb]uffett[^%]{0,150}?(\d{2,3}\.\d)\s*%", html)
            if m:
                v = float(m.group(1))
                if 50 < v < 400:
                    log.info("[buffett] gurufocus 抓取 = %s%%", v)
                    return {"ok": True, "value": v, "source": "gurufocus.com"}
            raise RuntimeError("gurufocus 页面结构变化，解析失败")
        except Exception as e1:
            log.warning("[buffett] gurufocus 失败（%s），改用 FRED 计算", one_line(e1)[:80])
        # 二级：FRED 全口径市值 / GDP × 校准系数
        try:
            mc = fred_series("crash:fred:mktcap", "NCBEILQ027S", 6 * 3600, False,
                             days=800, tag="fred:crash")
            gdp = fred_series("crash:fred:gdp", "GDP", 6 * 3600, False,
                              days=800, tag="fred:crash")
            if not (mc.get("ok") and mc.get("rows") and gdp.get("ok") and gdp.get("rows")):
                raise RuntimeError("FRED NCBEILQ027S/GDP 无数据")
            v = (mc["rows"][-1]["v"] / 1e6) / (gdp["rows"][-1]["v"] / 1000.0) * 100.0 * BUFFETT_CAL_FACTOR
            log.info("[buffett] FRED 计算 = %.1f%%（市值 %.1f 万亿$ / GDP %.2f 万亿$ × 校准 %.3f）",
                     v, mc["rows"][-1]["v"] / 1e6, gdp["rows"][-1]["v"] / 1000.0, BUFFETT_CAL_FACTOR)
            return {"ok": True, "value": round(v, 1),
                    "source": "FRED 计算（NCBEILQ027S/GDP，校准系数 0.913）",
                    "asOf": mc["rows"][-1]["d"]}
        except Exception as e2:
            return {"ok": False, "error": "gurufocus 失败(%s); FRED 失败(%s)"
                    % (one_line(e1)[:60], one_line(e2)[:60])}

    return cached("crash:buffett", 6 * 3600, run, force)


# ---------------------------------------------------------------- 恐慌贪婪（CNN）

def fear(force):
    def run():
        try:
            with gov_lock:
                j = remote(CNN_FG, as_json=True, tag="cnn:fear", browser_ua=True)
        except Exception as e:
            return {"ok": False, "error": "CNN 失败: " + one_line(e)[:120]}
        fg = j.get("fear_and_greed") or {}
        score = float(fg.get("score") or 0)
        if not 0 <= score <= 100:
            return {"ok": False, "error": "CNN 返回异常评分 %s" % score}
        hist = []
        for p in (j.get("fear_and_greed_historical") or {}).get("data") or []:
            try:
                hist.append({"d": datetime.fromtimestamp(p["x"] / 1000, timezone.utc).strftime("%Y-%m-%d"),
                             "v": round(p["y"], 1)})
            except (KeyError, TypeError, ValueError):
                continue
        log.info("[fear] 现价 %d（%s），历史 %d 点", score, fg.get("rating", "?"), len(hist))
        return {"ok": True, "score": int(round(score)), "rating": fg.get("rating", ""),
                "ts": str(fg.get("timestamp", "")), "history": downsample(hist, 2),
                "source": "CNN Fear & Greed"}

    return cached("crash:fear", 300, run, force)


# ---------------------------------------------------------------- 评分历史（本地 CSV）

def record(ticker, score):
    """当日评分累积到 data/risk_history.csv（同日同标的覆盖）——把快照升级为监测仪。"""
    today = date.today().isoformat()
    try:
        score = max(0.0, min(100.0, float(score)))
    except (TypeError, ValueError):
        return False
    rows = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, newline="", encoding="utf-8") as f:
                rows = [r for r in csv.reader(f) if len(r) >= 3 and r[0] != "date"]
        except OSError:
            rows = []
    rows = [r for r in rows if not (r[0] == today and r[1] == ticker)]
    rows.append([today, ticker, "%.1f" % score])
    rows.sort()
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "ticker", "score"])
        w.writerows(rows)
    log.info("[record] %s 当日评分 %.1f 已写入 risk_history.csv（共 %d 条）", ticker, score, len(rows))
    # CSV 是权威（换机迁移带它），库里那份只是同日覆盖的镜像；db.store_risk 内部吞异常，
    # 没启用落库时它是个空操作，不会因为连不上库把这次记录写成失败。
    db.store_risk(today, ticker, score)
    return True


def load_history(ticker):
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, newline="", encoding="utf-8") as f:
            return [{"d": r[0], "v": float(r[2])} for r in csv.reader(f)
                    if len(r) >= 3 and r[0] != "date" and r[1] == ticker]
    except (OSError, ValueError):
        return []


# ---------------------------------------------------------------- 路由

def r_health(q):
    return 200, {"ok": True, "module": "crash", "tickers": list(TICKERS)}


def r_market(q):
    d = market(_ticker(q), _force(q))
    return (200 if d.get("ok") else 502), d


def r_yields(q):
    d = yields(_force(q))
    return (200 if d.get("ok") else 502), d


def r_credit(q):
    d = credit(_force(q))
    return (200 if d.get("ok") else 502), d


def r_shiller(q):
    d = shiller(_force(q))
    return (200 if d.get("ok") else 502), d


def r_buffett(q):
    d = buffett(_force(q))
    return (200 if d.get("ok") else 502), d


def r_fear(q):
    d = fear(_force(q))
    return (200 if d.get("ok") else 502), d


def r_record(q):
    t = (q.get("ticker") or [""])[0].upper()
    if t not in TICKERS:
        return 400, {"ok": False, "error": "ticker 仅允许 " + "/".join(TICKERS)}
    ok = record(t, (q.get("score") or [""])[0])
    return (200 if ok else 400), {"ok": ok}


def r_history(q):
    return 200, {"ok": True, "rows": load_history(_ticker(q))}


ROUTES = {"health": r_health, "market": r_market, "yields": r_yields,
          "credit": r_credit, "shiller": r_shiller, "buffett": r_buffett,
          "fear": r_fear, "record": r_record, "history": r_history}
