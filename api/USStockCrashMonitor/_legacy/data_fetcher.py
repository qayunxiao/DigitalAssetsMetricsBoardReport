# -*- coding: utf-8 -*-
"""
数据获取模块 (Data Fetcher)
============================
集中管理美股崩盘监测仪所需的所有外部数据源。
每个数据源均提供: 自动获取 -> 缓存 -> 失败降级 的完整链路。

数据源清单 (均已实机验证国内可达性):
  - 股价/均线      : yfinance (VOO/QQQ)            [直连]
  - 10Y美债收益率  : yfinance ^TNX                 [直连]
  - 2Y美债收益率   : CNBC API                      [直连] 备用 akshare
  - 美国GDP        : FRED API (需免费key)          [api域名可达] 备用 akshare增速
  - 美股总市值     : FRED API (需免费key)          [api域名可达]
  - Shiller PE     : multpl.com 抓取               [直连]
  - Fear&Greed指数 : CNN dataviz API               [直连]

设计: 所有函数返回 (value, source_desc) 或 (value, source_desc, extra)。
      失败返回 None 由上层决定是否回退到手动输入。
"""

import os
import re
import json
import time
import ssl
import urllib.request
import urllib.error
from datetime import datetime

import numpy as np
import pandas as pd
import random


def generate_mock_market(ticker="VOO"):
    """
    生成逼真的模拟行情, 用于网络完全断开时的演示模式。
    返回 (df, price, sma200, us10y)。
    """
    dates = pd.date_range(end=datetime.now(), periods=500, freq="B")
    base_price = 500 if ticker == "QQQ" else 450
    trend = np.linspace(0, 50, 500)
    noise = np.random.normal(0, 5, 500).cumsum()
    prices = base_price + trend + noise

    df = pd.DataFrame(index=dates)
    df["Open"] = prices + np.random.uniform(-2, 2, 500)
    df["High"] = df["Open"] + np.random.uniform(0, 5, 500)
    df["Low"] = df["Open"] - np.random.uniform(0, 5, 500)
    df["Close"] = prices
    df["SMA_200"] = df["Close"].rolling(window=200).mean()

    return (df, float(df["Close"].iloc[-1]),
            float(df["SMA_200"].iloc[-1]), 4.15 + random.uniform(-0.1, 0.1))

# ----------------------------------------------------------------------------
# 全局网络配置
# ----------------------------------------------------------------------------
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# 网络代理 (由 app.py 注入, 例如 http://127.0.0.1:7890)
_PROXY = None


def set_proxy(proxy_url):
    """设置全局代理, 供所有数据源使用。proxy_url 为 None 则直连。"""
    global _PROXY
    _PROXY = proxy_url if proxy_url else None


def _http_get(url, headers=None, timeout=15):
    """
    统一的 HTTP GET, 自动应用代理与 UA, 返回原始 bytes。失败抛异常。
    """
    h = {"User-Agent": _UA,
         "Accept": "application/json,text/html,application/xhtml+xml,*/*",
         "Accept-Language": "en-US,en;q=0.9"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)

    handlers = [urllib.request.HTTPSHandler(context=_SSL_CTX)]
    if _PROXY:
        handlers.append(urllib.request.ProxyHandler({"http": _PROXY, "https": _PROXY}))
    opener = urllib.request.build_opener(*handlers)

    with opener.open(req, timeout=timeout) as resp:
        return resp.read()


# ============================================================================
# 1. FRED (美联储圣路易斯分行) —— GDP / 美股总市值 / 备选国债收益率
#    注意: fred.stlouisfed.org (网页/CSV) 国内被墙,
#          但 api.stlouisfed.org (官方API) 可达, 需免费 API key。
#    申请: https://fred.stlouisfed.org/docs/api/api_key.html (免费, 秒批)
# ============================================================================
_FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"


def _fred_latest(series_id, api_key, limit=8):
    """
    取 FRED 某序列最近若干条观测, 返回最新非空 float 值。
    GDP 等低频序列最新点可能是 '.', 故取最近 limit 条找最新有效值。
    """
    url = (f"{_FRED_BASE}?series_id={series_id}&api_key={api_key}"
           f"&file_type=json&sort_order=desc&limit={limit}")
    raw = _http_get(url)
    data = json.loads(raw)
    for obs in data.get("observations", []):
        v = obs.get("value", ".")
        if v not in (".", "", None):
            return float(v), obs.get("date")
    raise ValueError(f"FRED {series_id} 无有效观测值")


def get_fred_gdp(api_key):
    """
    美国名义 GDP (FRED 序列 GDP, 单位: 十亿美元, 季度, 已年化)。
    返回 (gdp_trillion, '2025-Q2 (FRED)')
    """
    val, date = _fred_latest("GDP", api_key)
    return val / 1000.0, f"{date} (FRED)"      # 十亿 -> 万亿


def get_fred_hy_spread(api_key, hist_years=5):
    """
    高收益债信用利差 (FRED 序列 BAMLH0A0HYM2, 单位: %, 日频)。
    返回 (current_value, history_list, source)。
    history_list 为最近 hist_years 年的历史利差, 用于分位数计算。
    这是与股市自身指标正交的"聪明钱"信用信号, 崩盘前常领先1-2个月扩大。
    """
    limit = hist_years * 260 + 20     # 每年约260个交易日
    url = (f"{_FRED_BASE}?series_id=BAMLH0A0HYM2&api_key={api_key}"
           f"&file_type=json&sort_order=desc&limit={limit}")
    raw = _http_get(url)
    data = json.loads(raw)
    vals = []
    for obs in data.get("observations", []):
        v = obs.get("value", ".")
        if v not in (".", "", None):
            vals.append(float(v))
    if not vals:
        raise ValueError("FRED 高收益债利差无数据")
    current = vals[0]                  # desc序, 第一个是最新
    date = data["observations"][0].get("date", "")
    return current, vals, f"{date} (FRED)"


def get_fred_market_cap(api_key):
    """
    FRED 美国公司权益市值 (序列 NCBEILQ027S, 单位: 百万美元, 季度)。
    注: FRED 旧序列 WILL5000PR 已下架, NCBEILQ027S 为现行权威替代。
    返回 (marketcap_trillion, date)。该口径含非上市权益, 数值偏大,
    计算巴菲特指标时需乘校准系数 BUFFETT_CAL_FACTOR。
    """
    val, date = _fred_latest("NCBEILQ027S", api_key)
    return val / 1e6, f"{date} (FRED)"   # 百万 -> 万亿


def get_fred_dgs(api_key):
    """
    FRED 国债收益率 DGS2 / DGS10 (日度, %)。
    返回 (dgs2, dgs10, date)。用作 CNBC/yfinance 的备用。
    """
    v2, d2 = _fred_latest("DGS2", api_key)
    v10, d10 = _fred_latest("DGS10", api_key)
    return v2, v10, f"{d10} (FRED)"


# ============================================================================
# 2. CNBC —— 2年期美债收益率 (国内直连, 无需key, 实时)
# ============================================================================
def get_cnbc_us2y():
    """
    CNBC 实时 2年期美债收益率 (%)。国内直连稳定。
    返回 (yield_2y_float, 'CNBC 实时')
    """
    url = ("https://quote.cnbc.com/quote-html-webservice/restQuote/"
           "symbolType/symbol?symbols=US2Y&requestMethod=itv&noform=1"
           "&partnerId=2&fund=1&exthrs=1&output=json")
    raw = _http_get(url)
    data = json.loads(raw)
    q = data["FormattedQuoteResult"]["FormattedQuote"][0]
    last = str(q.get("last", "")).replace("%", "").strip()
    return float(last), "CNBC 实时"


# ============================================================================
# 3. AkShare —— 国内财经数据库 (美债收益率备用, GDP增速备用)
#    bond_zh_us_rate 一次性给出 2Y/10Y/10Y-2Y利差, 国内直连最佳。
# ============================================================================
def get_akshare_treasury():
    """
    AkShare 中美债券收益率: 返回 (us_2y, us_10y, spread, date)。
    作为 CNBC/yfinance 失效时的备用。
    """
    import akshare as ak
    df = ak.bond_zh_us_rate(start_date="20240101")
    df = df.dropna(subset=["美国国债收益率2年", "美国国债收益率10年"])
    if df.empty:
        raise ValueError("akshare 国债数据为空")
    last = df.iloc[-1]
    us_2y = float(last["美国国债收益率2年"])
    us_10y = float(last["美国国债收益率10年"])
    date = str(last["日期"])
    return us_2y, us_10y, us_10y - us_2y, f"{date} (akshare)"


def get_akshare_gdp_growth():
    """
    AkShare 美国GDP环比增速 (最新公布值, %)。
    注意: 这是增速而非绝对值, 仅在无FRED key时用于展示参考。
    返回 (latest_value, date_str)
    """
    import akshare as ak
    df = ak.macro_usa_gdp_monthly()
    df = df.dropna(subset=["今值"])
    if df.empty:
        raise ValueError("akshare GDP数据为空")
    last = df.iloc[-1]
    return float(last["今值"]), f"{last['日期']} (akshare GDP环比%)"


# ============================================================================
# 4. Multpl —— 席勒市盈率 Shiller PE (CAPE)
# ============================================================================
def get_shiller_pe():
    """
    从 multpl.com 抓取最新 Shiller PE。
    页面顶部有 "Current Shiller PE Ratio: XX.XX" 字样。
    返回 (pe_float, 'multpl.com')
    """
    raw = _http_get("https://www.multpl.com/shiller-pe")
    html = raw.decode("utf-8", errors="ignore")

    # 主方案: 匹配 "Current Shiller PE Ratio is <b>XX.XX</b>" 之类的结构
    m = re.search(r"Current Shiller PE Ratio[^0-9]*?(\d+\.?\d*)", html, re.I)
    if m:
        return float(m.group(1)), "multpl.com"

    # 备用: 抓取表格第一行最新数据 (日期, 数值)
    m2 = re.findall(r"<td[^>]*>\s*([\d,]+\.?\d*)\s*</td>", html)
    if m2:
        for cand in m2:
            v = float(cand.replace(",", ""))
            if 5.0 < v < 100.0:        # Shiller PE 合理区间过滤
                return v, "multpl.com (表格)"
    raise ValueError("multpl Shiller PE 解析失败")


# ============================================================================
# 4.5 GuruFocus —— 巴菲特指标 (Buffett Indicator, 总市值/GDP)
#     业界标准口径, 免key直连, 已实机验证可解析。
#     口径: 上市公司总市值 / GDP (基于Wilshire5000全市场)。
# ============================================================================
def get_buffett_indicator():
    """
    从 gurufocus.com 抓取最新巴菲特指标 (%)。
    页面含 "Total Market Cap ... XX.X% ... GDP" 结构。
    返回 (buffett_pct, total_market_cap_trillion_or_None, source)。

    注: gurufocus 给出两个口径:
        - 232.9% 类: 基于当前GDP (TMC/GDP)
        - 192.9% 类: 基于预测GDP (修正版)
    本函数取第一个 (TMC/GDP 当前值), 与历史 2000/2008/2021 阈值口径一致。
    """
    url = "https://www.gurufocus.com/stock-market-valuations.php"
    raw = _http_get(url, timeout=20)
    html = raw.decode("utf-8", errors="ignore")

    # 匹配 "Total Market ... XX.X% ..." 结构
    m = re.search(r"[Tt]otal\s*[Mm]arket[^%]{0,150}?(\d{2,3}\.\d)\s*%", html)
    if not m:
        m = re.search(r"[Bb]uffett[^%]{0,150}?(\d{2,3}\.\d)\s*%", html)
    if not m:
        # 兜底: 收集所有 100-260 区间的百分比, 取第一个
        cands = [float(c) for c in re.findall(r">(\d{3}\.\d)\s*%<", html)
                 if 100.0 < float(c) < 260.0]
        if cands:
            return cands[0], None, "gurufocus.com (解析)"
        raise ValueError("gurufocus 巴菲特指标解析失败")

    buffett_pct = float(m.group(1))
    return buffett_pct, None, "gurufocus.com"


# 巴菲特指标口径校准系数:
# FRED NCBEILQ027S(全口径公司权益)/GDP ≈ 255% (偏大),
# gurufocus 标准口径 ≈ 232.9%, 故 FRED 换算时乘以该系数对齐业界口径。
BUFFETT_CAL_FACTOR = 232.9 / 255.0   # ≈ 0.913


# ============================================================================
# 5. CNN —— 恐慌与贪婪指数 Fear & Greed Index
# ============================================================================
def get_fear_greed():
    """
    CNN Fear & Greed Index (0-100)。
    非官方 dataviz 端点, 需完整浏览器 UA 否则返回 418。
    返回 (score_int, rating_str, timestamp_str)
    """
    url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
    raw = _http_get(url, headers={"Referer": "https://www.cnn.com/"})
    data = json.loads(raw)
    fg = data["fear_and_greed"]
    score = int(round(float(fg["score"])))
    rating = fg.get("rating", "")
    ts = fg.get("timestamp", "")
    return score, rating, str(ts)


# ============================================================================
# 6. yfinance —— 股价 / 200日均线 / 10Y美债收益率
# ============================================================================
def get_market_data_yf(ticker="VOO"):
    """
    获取 ETF 历史行情 + 200日均线 + 10Y美债收益率(^TNX)。
    返回 (df, current_price, sma_200, us_10y_yield)。失败抛异常由上层降级。
    """
    import yfinance as yf
    if _PROXY:
        import os
        os.environ["http_proxy"] = _PROXY
        os.environ["https_proxy"] = _PROXY

    end = datetime.now()
    start = end - pd.Timedelta(days=730)

    stock = yf.Ticker(ticker)
    df = stock.history(start=start, end=end)
    if df.empty:
        raise ValueError(f"{ticker} 行情为空")

    current_price = float(df["Close"].iloc[-1])
    df["SMA_200"] = df["Close"].rolling(window=200).mean()
    sma_200 = float(df["SMA_200"].iloc[-1])

    # 10Y 美债收益率
    us_10y = None
    try:
        tnx = yf.Ticker("^TNX").history(period="5d")
        if not tnx.empty:
            us_10y = float(tnx["Close"].iloc[-1])
    except Exception:
        us_10y = None

    return df, current_price, sma_200, us_10y


# ============================================================================
# 聚合: 一键获取全部自动数据 (带降级)
# ============================================================================
def fetch_all(ticker="VOO", fred_api_key=None, proxy=None):
    """
    一键获取所有可自动化的数据, 返回一个 dict。
    每项含 value / source / ok 标志, 失败项 value 为 None 供上层回退手动输入。

    参数:
      ticker       : "VOO" 或 "QQQ"
      fred_api_key : FRED API key (可选, 提供则 GDP/总市值走FRED最准)
      proxy        : 代理地址 (可选)
    """
    if proxy:
        set_proxy(proxy)

    result = {}

    # --- 行情 + 10Y (失败降级为模拟数据) ---
    try:
        df, price, sma200, y10 = get_market_data_yf(ticker)
        result["market"] = {"ok": True, "df": df, "price": price,
                            "sma200": sma200, "is_mock": False, "source": "yfinance"}
        if y10 is not None:
            result["us10y"] = {"ok": True, "value": y10, "source": "yfinance ^TNX"}
        else:
            result["us10y"] = {"ok": False, "value": None, "error": "yfinance 10Y为空"}
    except Exception as e:
        mdf, mprice, msma, m10y = generate_mock_market(ticker)
        result["market"] = {"ok": False, "df": mdf, "price": mprice, "sma200": msma,
                            "is_mock": True, "error": str(e), "source": "模拟数据"}
        result["us10y"] = {"ok": False, "value": m10y, "error": str(e), "source": "模拟数据"}

    # --- 2Y 收益率: CNBC -> akshare -> FRED 逐级降级 ---
    us2y = None
    try:
        v, src = get_cnbc_us2y()
        us2y = {"ok": True, "value": v, "source": src}
    except Exception as e1:
        try:
            v2, v10, spread, src = get_akshare_treasury()
            us2y = {"ok": True, "value": v2, "source": src}
            # akshare 同时可补 10Y (若 yfinance 失败)
            if not result["us10y"]["ok"]:
                result["us10y"] = {"ok": True, "value": v10, "source": src}
        except Exception as e2:
            if fred_api_key:
                try:
                    d2, d10, src = get_fred_dgs(fred_api_key)
                    us2y = {"ok": True, "value": d2, "source": src}
                    if not result["us10y"]["ok"]:
                        result["us10y"] = {"ok": True, "value": d10, "source": src}
                except Exception as e3:
                    us2y = {"ok": False, "value": None, "error": str(e3)}
            else:
                us2y = {"ok": False, "value": None,
                        "error": f"CNBC失败({e1}); akshare失败({e2})"}
    result["us2y"] = us2y

    # --- GDP (巴菲特指标分母, FRED 需key) ---
    gdp_val = None
    if fred_api_key:
        try:
            v, src = get_fred_gdp(fred_api_key)
            gdp_val = v
            result["gdp"] = {"ok": True, "value": v, "source": src}
        except Exception as e:
            result["gdp"] = {"ok": False, "value": None, "error": str(e)}
    else:
        result["gdp"] = {"ok": False, "value": None,
                         "error": "未提供FRED key (可免费申请)"}

    # --- 巴菲特指标 (总市值/GDP) ---
    # 三级降级: gurufocus抓取(标准口径,免key) -> FRED计算(需key) -> 手动
    buffett = None
    try:
        bpct, _, src = get_buffett_indicator()
        buffett = {"ok": True, "value": bpct, "source": src}
    except Exception as e1:
        if fred_api_key:
            try:
                mc, mc_src = get_fred_market_cap(fred_api_key)
                if gdp_val:
                    bpct = (mc / gdp_val) * 100.0 * BUFFETT_CAL_FACTOR
                    buffett = {"ok": True, "value": bpct,
                               "source": f"FRED计算 ({mc_src})"}
                else:
                    raise ValueError("无GDP无法计算")
            except Exception as e2:
                buffett = {"ok": False, "value": None,
                           "error": f"gurufocus失败({e1}); FRED失败({e2})"}
        else:
            buffett = {"ok": False, "value": None,
                       "error": f"gurufocus失败({e1})"}
    result["buffett"] = buffett

    # --- 高收益债信用利差 (崩盘预警的"聪明钱"信号, 需FRED key) ---
    if fred_api_key:
        try:
            cur, hist, src = get_fred_hy_spread(fred_api_key)
            result["credit"] = {"ok": True, "value": cur, "history": hist, "source": src}
        except Exception as e:
            result["credit"] = {"ok": False, "value": None, "history": None, "error": str(e)}
    else:
        result["credit"] = {"ok": False, "value": None, "history": None,
                            "error": "未提供FRED key"}

    # --- Shiller PE ---
    try:
        v, src = get_shiller_pe()
        result["shiller"] = {"ok": True, "value": v, "source": src}
    except Exception as e:
        result["shiller"] = {"ok": False, "value": None, "error": str(e)}

    # --- Fear & Greed ---
    try:
        score, rating, ts = get_fear_greed()
        result["fear_greed"] = {"ok": True, "value": score,
                                "rating": rating, "source": f"CNN ({rating})"}
    except Exception as e:
        result["fear_greed"] = {"ok": False, "value": None, "error": str(e)}

    return result


# ============================================================================
# 风险评分历史记录 (本地 CSV 累积, 用于绘制风险趋势图)
# ============================================================================
_HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "risk_history.csv")


def record_risk_score(ticker, score):
    """
    把当日某标的的风险评分追加到本地 CSV (同日覆盖, 跨日累积)。
    每次运行记录一条, 长期累积形成风险趋势。
    """
    import csv
    today = datetime.now().strftime("%Y-%m-%d")
    rows = []
    if os.path.exists(_HISTORY_FILE):
        with open(_HISTORY_FILE, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
    header = ["date", "ticker", "score"]
    # 移除今日同标的旧记录 (同日重复运行只保留最新)
    data = [r for r in rows[1:] if not (len(r) >= 2 and r[0] == today and r[1] == ticker)] \
        if len(rows) > 1 else []
    data.append([today, ticker, f"{score:.1f}"])
    with open(_HISTORY_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(data)


def load_risk_history(ticker):
    """
    读取某标的的风险评分历史, 返回 DataFrame(date, score) 按日期升序。
    无记录时返回空 DataFrame。
    """
    if not os.path.exists(_HISTORY_FILE):
        return pd.DataFrame(columns=["date", "score"])
    df = pd.read_csv(_HISTORY_FILE)
    df = df[df["ticker"] == ticker][["date", "score"]].copy()
    df["date"] = pd.to_datetime(df["date"])
    df["score"] = pd.to_numeric(df["score"], errors="coerce")
    return df.dropna().sort_values("date").reset_index(drop=True)


# ============================================================================
# 命令行自测
# ============================================================================
if __name__ == "__main__":
    import sys
    key = sys.argv[1] if len(sys.argv) > 1 else None
    print("=" * 60)
    print("数据源连通性自测 (FRED key:", "已提供" if key else "未提供", ")")
    print("=" * 60)
    r = fetch_all(ticker="VOO", fred_api_key=key)
    for k, v in r.items():
        if v.get("ok"):
            if k == "market":
                print(f"[OK] {k:10s} price={v['price']:.2f} sma200={v['sma200']:.2f} ({v['source']})")
            else:
                print(f"[OK] {k:10s} = {v.get('value')}  ({v.get('source')})")
        else:
            print(f"[--] {k:10s} 失败: {v.get('error', '')[:60]}")
