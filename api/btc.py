# -*- coding: utf-8 -*-
"""BTC 指标监控（staic/btc.html）取数模块：全部日线指标一次汇总。

路由（由 app.py 挂载）：
  /api/btc/health                    模块自述（不打上游，首屏探测用）
  /api/btc/summary[?force=1]         各项一次返回，每项自带 ok / value / verdict / hist / error
  /api/btc/one?k=<key>[&force=1]     单项重取（失败卡片上的「重试」走这条，不连累其余各项）

口径来源：`api/Crypto/handle_*.py`（2026-09-23 由用户从 `D:/Qorder_ws/cryptoTrader/api_list/` 抄进仓库的
只读副本，逐字节一致）与那份项目的 `utils/operationConfig.py` 阈值表（没抄进来，仍在原处）。
**两处都只读**：不改它的文件、不从它 import，这里重写为零依赖版。每处阈值都在注释里标了出处行号。

上游一律公开只读 GET、不带密钥。唯一的例外是 AHR999 的 CoinGlass 备用源：只有本机环境里存在
`COINGLASS_KEY` 时才会去试它（仓库、config.ini、上传包里都不放密钥）。
每台主机一把本模块自己的串行锁：`core.gov_lock` 是给 FRED/Yahoo 那批主机用的，`mkt_lock` 给 ccxt
行情源，和这几台都没关系，共用一把会让流动性页 40~60s 的预热把这张页卡住。
"""
import os
import threading
from bisect import bisect_right
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urlparse

import db
from core import cached, gov_lock, log, remote, short_err, yahoo_bars

HIST_POINTS = 120            # 每张卡的迷你历史点数（再多响应体就虚胖了）
BAND_POINTS = 400            # 放大图专用：通道要同时画三条线，120 点画日线价格会抖成锯齿，给它 4 倍密度
PRICE_RANGE = "20y"          # Yahoo BTC-USD 的日线全域（实测 20y/15y 都到 2014-09-17 为止，max 反而退化成月线）
LIVE_AGE = 900               # 页面据此标 ● 实时 / ○ 快照（秒）
KLINE_MIN_BARS = 200         # 少于这个根数算不出 MA200，宁可不显示也不给半截均线
KEY_ENV = {"coinglass": "COINGLASS_KEY"}     # 可选密钥源：环境变量给了才用

_locks = {}
_locks_guard = threading.Lock()


def _host_lock(url):
    host = urlparse(url).netloc
    with _locks_guard:
        lk = _locks.get(host)
        if lk is None:
            lk = _locks[host] = threading.Lock()
    return lk


def _j(url, tag, referer=None, ms=20000, extra=None):
    """同主机串行的 JSON GET。这些源都认浏览器签名（cryptoTrader 的 handler 一律发 Chrome UA）。
    remote() 在 browser_ua 下会塞一个 CNN 的 referer，这里显式给的那条覆盖它。"""
    hdr = {"referer": referer} if referer else {}
    hdr.update(extra or {})
    with _host_lock(url):
        return remote(url, as_json=True, ms=ms, tag=tag, browser_ua=True, headers=hdr or None)


def _d(ts):
    """秒或毫秒时间戳 → UTC 日期串。上游三种单位都有（looknode 毫秒、okx 毫秒字符串、kraken 秒）。"""
    t = float(ts)
    if t > 1e12:
        t /= 1000.0
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None          # 挡 NaN


def _mean(vals, n):
    v = [x for x in vals[-n:] if x is not None]
    return round(sum(v) / len(v), 2) if v else None


def _pct_rank(vals, cur, n=365):
    """当前值在近 n 个点里的分位（0~100）——是本模块自己从上游序列算的，不是估的。"""
    a = [x for x in vals[-n:] if x is not None]
    if not a or cur is None:
        return None
    return round(100.0 * sum(1 for x in a if x <= cur) / len(a), 1)


def _zpop(vals):
    """z = (末值 − 均值) / 总体标准差（除以 n，不是 n−1），与 handle_SOPR_Z-Score.py:76-87 一致。"""
    a = [x for x in vals if x is not None]
    if len(a) < 2:
        return None
    m = sum(a) / len(a)
    var = sum((x - m) ** 2 for x in a) / len(a)
    if var <= 0:
        return 0.0
    return (a[-1] - m) / (var ** 0.5)


def _hist(rows, n=HIST_POINTS):
    """[{d,v}] → 迷你图的定长点列：等间隔抽样、末行必留（同 core.downsample 的做法）。"""
    if not rows:
        return []
    step = max(1, len(rows) // n)
    out = [rows[i] for i in range(0, len(rows), step)]
    if out[-1] is not rows[-1]:
        out.append(rows[-1])
    return [{"d": r["d"], "v": round(r["v"], 4)} for r in out if r.get("v") is not None]


def _band_hist(rows, px, n=BAND_POINTS):
    """通道卡的稠密点列：`[{d, lo, hi}]` + 日期→收盘 → `[{d, lo, hi, px}]`。
    抽样与 _hist 同一套（等间隔、末行必留），但**三条线共用同一批 x**，否则前端没法对齐。

    价格按「该日或之前最近一个交易日」取（前向填充），不是精确等值匹配：Yahoo 的收盘序列会缺根
    （实测就缺了 2026-09-23 那根），等值匹配会在图的最右端留一个洞，而那里正是用户看的地方。
    通道起点（2012-07）早于价格起点（2014-09），这一段没有价格可填，`px=None`，前端照画两条线、
    缺口在图注里写明，不拿 0 或外推值冒充。"""
    if not rows:
        return []
    step = max(1, len(rows) // n)
    out = [rows[i] for i in range(0, len(rows), step)]
    if out[-1] is not rows[-1]:
        out.append(rows[-1])
    days = sorted(px)
    bands = []
    for r in out:
        i = bisect_right(days, r["d"]) - 1        # 最近一个不晚于该日的交易日
        bands.append({"d": r["d"], "lo": round(r["lo"], 2), "hi": round(r["hi"], 2),
                      "px": px[days[i]] if i >= 0 else None})
    return bands


def _mk(key, name, unit, dp=None, value=None, text=None, tone="gray", verdict="",
        asof=None, src=None, hist=None, extras=None, note=None, error=None, bands=None):
    """一张卡的全部字段。tone: red=顶部/过热，green=底部/多头，gray=中性，bad=取数失败。
    `bands` 只有画通道的卡会给（[{d, lo, hi, px}]，放大图三条线），其余卡不带这个键。"""
    d = {"key": key, "name": name, "unit": unit, "ok": error is None,
         "value": value, "text": text, "dp": dp, "tone": "bad" if error else tone,
         "verdict": error or verdict, "asof": asof, "src": src,
         "hist": hist or [], "extras": extras or []}
    if bands:
        d["bands"] = bands
    if note:
        d["note"] = note
    if error:
        d["error"] = error
    return d


# ---------------------------------------------------------------- 上游取数（每台主机一份缓存）

KLINES = [
    # (源名, URL, 解析函数, referer)；顺序 = 先试与 cryptoTrader 同源的 binance，再试实测可达的三家，
    # 最后 bybit（本机出口 403，但服务器侧可能通）。第一个给够 KLINE_MIN_BARS 根收盘的源胜出。
    ("binance", "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1d&limit=500", None, None),
    ("kraken", "https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=1440", None, None),
    ("okx", "https://www.okx.com/api/v5/market/candles?instId=BTC-USDT&bar=1D&limit=300", None, None),
    ("coinbase", "https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=86400", None, None),
    ("bybit", "https://api.bybit.com/v5/market/kline?category=spot&symbol=BTCUSDT&interval=D&limit=500", None, None),
]


def _bars_binance(j):
    return [{"d": _d(r[0]), "o": _num(r[1]), "h": _num(r[2]), "l": _num(r[3]), "c": _num(r[4])}
            for r in j if _num(r[4]) is not None]


def _bars_kraken(j):
    res = (j or {}).get("result") or {}
    key = [k for k in res if k not in ("last", "error")]
    rows = res.get(key[0]) if key else []
    return [{"d": _d(r[0]), "o": _num(r[1]), "h": _num(r[2]), "l": _num(r[3]), "c": _num(r[4])}
            for r in rows if _num(r[4]) is not None]


def _bars_okx(j):
    if str((j or {}).get("code")) != "0":
        raise RuntimeError("okx code=%s %s" % (j.get("code"), str(j.get("msg"))[:40]))
    rows = [r for r in (j.get("data") or []) if _num(r[4]) is not None]
    rows.reverse()                       # okx 是最新在前
    return [{"d": _d(r[0]), "o": _num(r[1]), "h": _num(r[2]), "l": _num(r[3]), "c": _num(r[4])}
            for r in rows if str(r[8] if len(r) > 8 else "1") != "0"]   # confirm=0 是未收盘的当根


def _bars_coinbase(j):
    rows = [r for r in (j or []) if _num(r[4]) is not None]
    rows.reverse()                       # 同样最新在前；列序是 [t, low, high, open, close, vol]
    return [{"d": _d(r[0]), "o": _num(r[3]), "h": _num(r[2]), "l": _num(r[1]), "c": _num(r[4])}
            for r in rows]


def _bars_bybit(j):
    rows = ((j or {}).get("result") or {}).get("list") or []
    rows = [r for r in rows if _num(r[4]) is not None]
    rows.reverse()
    return [{"d": _d(r[0]), "o": _num(r[1]), "h": _num(r[2]), "l": _num(r[3]), "c": _num(r[4])}
            for r in rows]


_PARSER = {"binance": _bars_binance, "kraken": _bars_kraken, "okx": _bars_okx,
           "coinbase": _bars_coinbase, "bybit": _bars_bybit}


def klines(force=False):
    """日线 OHLC（升序、只含已收盘根）+ 最后一根的收盘当作现价。
    EMA / EMA_new / KDJ / MACD 四项共用这一份，MA200 也用它，所以一次 summary 只打一家。"""
    def run():
        errs = []
        for name, url, _, referer in KLINES:
            try:
                bars = _PARSER[name](_j(url, "btc:bar:" + name, referer))
            except Exception as e:
                errs.append("%s: %s" % (name, short_err(e)))
                continue
            if not bars:
                errs.append("%s: 空序列" % name)
                continue
            spot = bars[-1]["c"]
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if bars[-1]["d"] == today:            # 当天那根还没走完，不参与均线/交叉
                bars = bars[:-1]
            if len(bars) < KLINE_MIN_BARS:
                errs.append("%s: 仅 %d 根（需 ≥%d）" % (name, len(bars), KLINE_MIN_BARS))
                continue
            log.info("[btc] 日线取自 %s：%d 根（%s → %s）现价 %s，剔除 %s",
                     name, len(bars), bars[0]["d"], bars[-1]["d"], spot, "; ".join(errs) or "无")
            return {"ok": True, "bars": bars, "from": name, "spot": spot,
                    "dropped": "今天（%s UTC）未收盘那根已剔除" % today if spot != bars[-1]["c"] else "无",
                    "errs": errs}
        log.error("[btc] 全部 K 线源不可达：%s", "; ".join(errs))
        return {"ok": False, "error": "K 线源全部不可达: " + ("; ".join(errs) or "无响应")}

    return cached("btc:klines", 900, run, force)


def btc_closes(force=False):
    """长历史日线收盘（Yahoo `BTC-USD`，实测 4390 根、2014-09-17 起）——只服务 2年MA 通道图的第三条线。
    为什么不用本页那份 klines：它最多 500 根（约 1.4 年），而通道横轴是 2012 年至今 5182 天，
    拿它画价格只剩右边一小截，看着就像"我们的图和上游差很多"。与资产配置页的 `alloc10:BTC-USD`
    是同一家同一符号，但**故意不共用缓存键**：那边 10y、这边 20y，形状不同，混用会静默少两年。
    不进日缓存白名单：最后那根是今天的未收盘bar，日内会变，冻结一整天等于给个假收盘。"""
    def run():
        with gov_lock:
            return yahoo_bars("BTC-USD", tag="btc", days_range=PRICE_RANGE)

    return cached("btc:yahoo:BTC-USD", 6 * 3600, run, force)


def looknode(url, key, force=False):
    """Looknode 免费序列（MVRV、CVDD）：{"code":100,"data":[{"t":ms,"v":num}]} → 升序 [{d,v}]。"""
    def run():
        try:
            j = _j(url, "btc:" + key, referer="https://www.looknode.com/charts")
        except Exception as e:
            return {"ok": False, "error": "Looknode %s: %s" % (key, short_err(e))}
        if not isinstance(j, dict) or j.get("code") != 100:
            return {"ok": False, "error": "Looknode %s 返回 code=%s" % (key, (j or {}).get("code"))}
        rows = []
        for p in j.get("data") or []:
            t, v = p.get("t"), _num(p.get("v"))
            if t is None or v is None:
                continue
            rows.append({"d": _d(t), "v": v})
        rows.sort(key=lambda r: r["d"])           # 上游本就升序，排一次防它改顺序
        if not rows:
            return {"ok": False, "error": "Looknode %s 解析出 0 个点" % key}
        log.info("[btc] looknode:%s %d 个点（%s → %s = %s）", key, len(rows),
                 rows[0]["d"], rows[-1]["d"], rows[-1]["v"])
        return {"ok": True, "rows": rows, "src": "Looknode"}

    return cached("btc:looknode:" + key, 3600, run, force)


def looknode_band(url, key, force=False):
    """Looknode 的双线通道（2年MA乘数 = 730MA 与 730MA×5）：`{"code":100,"data":[{"t":秒,"v1":上沿,"v2":下沿}]}`
    → 升序 `[{d, lo, hi}]`。上游 v1 恒等 5×v2（5182 个点全域如此），这里照原样收下、不重算乘数。
    与 looknode() 分开是因为字段名不同（v1/v2 而非 v），拿它去喂单值解析会得到 0 个点。"""
    def run():
        try:
            j = _j(url, "btc:" + key, referer="https://www.looknode.com/charts")
        except Exception as e:
            return {"ok": False, "error": "Looknode %s: %s" % (key, short_err(e))}
        if not isinstance(j, dict) or j.get("code") != 100:
            return {"ok": False, "error": "Looknode %s 返回 code=%s" % (key, (j or {}).get("code"))}
        rows = []
        for p in j.get("data") or []:
            t, hi, lo = p.get("t"), _num(p.get("v1")), _num(p.get("v2"))
            if t is None or lo is None or hi is None:
                continue
            rows.append({"d": _d(t), "lo": lo, "hi": hi})
        rows.sort(key=lambda r: r["d"])
        if not rows:
            return {"ok": False, "error": "Looknode %s 解析出 0 个点" % key}
        log.info("[btc] looknode:%s %d 个点（%s → %s 下沿=%s 上沿=%s）", key, len(rows),
                 rows[0]["d"], rows[-1]["d"], rows[-1]["lo"], rows[-1]["hi"])
        return {"ok": True, "rows": rows, "src": "Looknode"}

    return cached("btc:looknode:" + key, 3600, run, force)


MVRV_URL = "https://www.looknode.com/api/mCapRealizedRatio"
CVDD_URL = "https://www.looknode.com/api/CVDD"
AHR999_URL = "https://www.looknode.com/api/Ahr999"     # 路径大小写敏感：小写 ahr999 回 404
TWM_URL = "https://www.looknode.com/api/twoYearMultiply"    # 这条恰好是全小写开头，与页面 slug 同拼写


def mvrv_rows(force=False):
    return looknode(MVRV_URL, "mvrv", force)


def fng(force=False):
    """恐慌贪婪指数（alternative.me，免费）。上游是最新在前，倒过来用。"""
    def run():
        try:
            j = _j("https://api.alternative.me/fng/?limit=400", "btc:fng")
        except Exception as e:
            return {"ok": False, "error": "alternative.me: " + short_err(e)}
        rows = []
        for p in reversed((j or {}).get("data") or []):
            v, ts = _num(p.get("value")), p.get("timestamp")
            if v is None or not ts:
                continue
            rows.append({"d": _d(ts), "v": v, "cls": p.get("value_classification") or ""})
        if not rows:
            return {"ok": False, "error": "alternative.me 解析出 0 天"}
        return {"ok": True, "rows": rows}

    return cached("btc:fng", 900, run, force)


def cbbi(force=False):
    """CBBI（Colin Talks Crypto 牛熊信心指数）。latest.json = 各子指标的 {时间戳: 值} 字典，
    Confidence 就是合成分、原始刻度 0~1（handle_CBBI.py:61-93），×100 后才是页面上那个 0~100。"""
    def run():
        errs = []
        for url in ("https://colintalkscrypto.com/cbbi/data/latest.json",
                    "https://colintalkscrypto.com/api/cbbi"):
            try:
                j = _j(url, "btc:cbbi", referer="https://colintalkscrypto.com/cbbi/", ms=25000)
            except Exception as e:
                errs.append(short_err(e))
                continue
            conf = (j or {}).get("Confidence")
            if isinstance(conf, dict) and conf:
                pts = sorted(((int(t), _num(v)) for t, v in conf.items()), key=lambda x: x[0])
                rows = [{"d": _d(t), "v": v * 100.0} for t, v in pts if v is not None]
                parts = []
                for k, val in (j or {}).items():
                    if not isinstance(val, dict) or not val:
                        continue
                    last = sorted(val.items(), key=lambda x: int(x[0]))[-1]
                    v = _num(last[1])
                    if v is not None:
                        parts.append({"k": k, "d": _d(last[0]), "v": round(v * 100.0, 1)})
                rows_sorted = sorted(rows, key=lambda r: r["d"])
                log.info("[btc] CBBI 最新 %s = %.2f（%d 个历史点、%d 条子指标）",
                         rows_sorted[-1]["d"], rows_sorted[-1]["v"], len(rows_sorted), len(parts))
                return {"ok": True, "rows": rows_sorted, "parts": parts, "src": "colintalkscrypto latest.json"}
            v = _num((j or {}).get("current")) or _num((j or {}).get("value"))
            if v is not None:
                return {"ok": True, "rows": [{"d": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                                             "v": v * 100.0 if v <= 1 else v}],
                        "parts": [], "src": "colintalkscrypto api"}
            errs.append("无 Confidence 字段")
        return {"ok": False, "error": "CBBI: " + ("; ".join(errs) or "无响应")}

    return cached("btc:cbbi", 3600, run, force)


def _cg_msg(j):
    """CoinGlass 那条链失败时也回 HTTP 200，真正的原因在 body 的 code/msg 里（例如 code=401 / msg='Upgrade plan'）。
    不把它透出来的话，页面只会说「响应里没有 ahr999」，把一个「套餐不含」读成「我们没解析对」。"""
    d = j if isinstance(j, dict) else {}
    code, msg = str(d.get("code") or ""), str(d.get("msg") or "")
    if code in ("", "0"):
        return ""
    out = msg or code
    if "plan" in out.lower() or "upgrade" in out.lower():
        out += "（Key 被认了，但当前套餐不含这个指标）"
    return out


def ahr999(force=False):
    """AHR999 定投指数。**本模块不自己造 AHR999 公式**——`api/Crypto/handle_AHR999.py` 里也没有可核对的
    口径（它只是一句 `requests.get` 取现成表格，从没算过），拍脑袋算出来的数字会被当成抄底/逃顶信号，
    宁可让这张卡空着并写明每条上游的实际死法。
    来源顺序沿用 handle_AHR999.py:33 与 handle_fuckbtc.py:484-530 的链条。
    2026-09-23 重测（同一天另试了 api.coinsoto、coinsoto.com/api、looknode/api/ahr999、
    capi 与 fapi 与 open-api 三代 coinglass 主机、btc123 历史站、bitcoin-data、blockchain.info/charts，全不通）：
      coinsoto  走代理 TLS 握手即 EOF、代理直拒该域名（Errno 2）、直连超时——三条路都过不去；
      soulbab   530 = Cloudflare 1016「源站 DNS 解析不到」，域名已经不存在；
      CoinGlass v4 上确有 /api/index/ahr999、`CG-API-KEY` 也对，但回 401 Upgrade plan（要付费套餐）。
    同日修订：那句「looknode 没有 /api/ahr999」是错的——这条路径大小写敏感，页面 slug 是大写 A 的
    `Ahr999`，`/api/Ahr999` 就是那张图的原始序列（5700+ 个点，当天更新），已与 MVRV/CVDD 走同一条
    `looknode()` 通路并排在首选；coinsoto / soulbab / CoinGlass 三条按原顺序留着兜底。"""
    def run():
        errs = []
        d = looknode(AHR999_URL, "ahr999", force)
        if d.get("ok"):
            rows = d["rows"]
            return {"ok": True, "value": rows[-1]["v"], "avg200": None,      # avg 是价格 200 日均线，本序列给不了
                    "prev": rows[-2]["v"] if len(rows) > 1 else None,
                    "rows": rows, "src": "Looknode Ahr999"}
        errs.append("looknode: " + str(d.get("error")))
        try:
            j = _j("https://coinsoto.com/indicatorapi/getAhr999Table", "btc:ahr", referer="https://coinsoto.com/")
            d = (j or {}).get("data") or []
            if d:
                row, prev = d[0], (d[1] if len(d) > 1 else {})
                v, avg = _num(row.get("ahr999")), _num(row.get("avg"))
                if v is not None:
                    hist = [{"d": r.get("date") or r.get("d") or "", "v": _num(r.get("ahr999"))}
                            for r in reversed(d) if _num(r.get("ahr999")) is not None]
                    return {"ok": True, "value": v, "avg200": avg, "prev": _num(prev.get("ahr999")),
                            "rows": hist, "src": "coinsoto getAhr999Table"}
            errs.append("coinsoto: 无 data/ahr999 字段")
        except Exception as e:
            errs.append("coinsoto: " + short_err(e))
        try:
            j = _j("https://dncapi.soulbab.com/api/v2/index/arh999?code=bitcoin&webp=1", "btc:ahr2")
            v = _num((j or {}).get("ahr999")) or _num(((j or {}).get("data") or [{}])[0].get("ahr999"))
            if v is not None:
                return {"ok": True, "value": v, "avg200": None, "prev": None, "rows": [], "src": "soulbab dncapi"}
            errs.append("soulbab: 无 ahr999 字段")
        except Exception as e:
            errs.append("soulbab: " + short_err(e))
        key = (os.environ.get(KEY_ENV["coinglass"]) or "").strip()
        if key:                         # 只有环境里给了 Key 才试，仓库与上传包都不带凭据
            try:
                j = _j("https://open-api-v4.coinglass.com/api/index/ahr999", "btc:ahr3",
                       extra={"CG-API-KEY": key})
                m = _cg_msg(j)
                if m:                     # 失败也回 200，原因只在 body 里——先查它，别当成「字段缺失」
                    errs.append("coinglass: " + m)
                    return {"ok": False, "error": "AHR999 上游全部不通：" + "; ".join(errs)}
                data = (j or {}).get("data")
                v = _num(data)
                if v is None and isinstance(data, list) and data:
                    v = _num(data[-1].get("ahr999") if isinstance(data[-1], dict) else data[-1])
                if v is None and isinstance(data, dict):
                    v = _num(data.get("ahr999"))
                if v is not None:
                    return {"ok": True, "value": v, "avg200": None, "prev": None,
                            "rows": [], "src": "CoinGlass"}
                errs.append("coinglass: 响应里没有 ahr999")
            except Exception as e:
                errs.append("coinglass: " + short_err(e))
        return {"ok": False, "error": "AHR999 上游全部不通：" + "; ".join(errs)}

    return cached("btc:ahr999", 3600, run, force)


def litb(force=False):
    """Look Into Bitcoin 原始接口（supply-in-profit / nupl / cvdd）。
    handle_LookIntoBitcoin.py:6-9 已注明该主机 502 废弃、替代是 BM Pro 付费订阅（docs/api_url:141-145）。
    这里保留它的调用，是为了让这一格自己说「源已废弃」，而不是被悄悄删掉。"""
    def run():
        try:
            j = _j("https://production.lookintobitcoin.com/api/supply-in-profit", "btc:litb",
                   referer="https://www.lookintobitcoin.com/")
            d = (j or {}).get("data") or []
            rows = [{"d": _d(r[0]), "v": _num(r[1])} for r in d
                    if len(r) >= 2 and _num(r[0]) and _num(r[1]) is not None]
            if not rows:
                return {"ok": False, "error": "Look Into Bitcoin 响应里没有数据点"}
            return {"ok": True, "value": rows[-1]["v"], "asof": rows[-1]["d"],
                    "rows": rows, "src": "production.lookintobitcoin.com"}
        except Exception as e:
            return {"ok": False, "error": "Look Into Bitcoin: " + short_err(e) +
                      "（该源自 2024 年起 502 废弃，替代方案 BM Pro 需付费订阅）"}

    return cached("btc:litb", 3600, run, force)


# ---------------------------------------------------------------- 指标算法（与 cryptoTrader 同口径）

def _ema(vals, period, prefill="echo"):
    """k=2/(period+1)；第 period−1 根用前 period 根的 SMA 播种；之前的位置：
    prefill='echo' → 填当根收盘（handle_EMA.py:74-87、handle_MACD.py:73-90 的写法）
    prefill='none' → 填 None（handle_EMA_new.py:50-68 的写法）—— 两个 EMA 卡片的差别就只有这一处。"""
    out, prev = [], None
    for i, v in enumerate(vals):
        if i < period - 1:
            out.append(v if prefill == "echo" else None)
            continue
        if i == period - 1:
            prev = sum(vals[:period]) / period
        else:
            k = 2.0 / (period + 1)
            prev = v * k + prev * (1 - k)
        out.append(prev)
    return out


def _cross(fast, slow, fn, sn):
    """最后一根相对前一根判金叉/死叉（handle_EMA.py:106 的口径：prev_fast<=prev_slow 且 curr_fast>curr_slow）。
    fn/sn 只影响措辞：EMA 卡是 EMA5/EMA10，KDJ 卡是 K/D，MACD 卡是 MACD 线/信号线，别一律叫「快线」。"""
    if len(fast) < 2 or len(slow) < 2 or fast[-1] is None or slow[-1] is None \
            or fast[-2] is None or slow[-2] is None:
        return "数据不足", "gray"
    pf, ps, cf, cs = fast[-2], slow[-2], fast[-1], slow[-1]
    if pf <= ps and cf > cs:
        return "金叉（本根 %s 上穿 %s）" % (fn, sn), "green"
    if pf >= ps and cf < cs:
        return "死叉（本根 %s 下穿 %s）" % (fn, sn), "red"
    if cf == cs:                            # 完全重合时别硬套多/空头，那是横盘序列的常态
        return "无交叉 · %s 与 %s 重合" % (fn, sn), "gray"
    return ("无交叉 · %s 在 %s 上方（多头）" % (fn, sn) if cf > cs
            else "无交叉 · %s 在 %s 下方（空头）" % (fn, sn)), \
        ("green" if cf > cs else "red")


def _macd(closes, fast=12, slow=26, sig=9):
    """信号线只对 macd[slow−1:] 做 EMA9（SMA 播种），再在前面补 None —— handle_MACD.py:111-117 就这么写的。"""
    ef, es = _ema(closes, fast), _ema(closes, slow)
    line = [a - b for a, b in zip(ef, es)]
    sig_tail = _ema(line[slow - 1:], sig, prefill="none")
    signal = [None] * (slow - 1) + sig_tail
    hist = [(m - g) if (m is not None and g is not None) else None for m, g in zip(line, signal)]
    return line, signal, hist


def _kdj(bars, n=9, m1=3, m2=3):
    """KDJ(9,3,3)。K = 最近 m1 根 RSV 的**算术均值**、D = 最近 m2 根 K 的算术均值（不是常见的 1/3 平滑），
    high_n<=low_n 时 RSV 记 50 —— 全部照 handle_KDJ.py:112-142。J = 3K−2D。"""
    hi = [b["h"] for b in bars]
    lo = [b["l"] for b in bars]
    cl = [b["c"] for b in bars]
    m = len(bars)
    rsv = [None] * m
    for i in range(n - 1, m):
        h, l = max(hi[i - n + 1:i + 1]), min(lo[i - n + 1:i + 1])
        rsv[i] = 50.0 if h <= l else (cl[i] - l) / (h - l) * 100.0
    k = [None] * m
    dd = [None] * m
    jv = [None] * m
    for i in range(m):
        w = rsv[max(0, i - m1 + 1):i + 1]
        if len(w) == m1 and all(x is not None for x in w):
            k[i] = sum(w) / m1
        w2 = k[max(0, i - m2 + 1):i + 1]
        if k[i] is not None and len(w2) == m2 and all(x is not None for x in w2):
            dd[i] = sum(w2) / m2
        if k[i] is not None and dd[i] is not None:
            jv[i] = 3 * k[i] - 2 * dd[i]
    return k, dd, jv, rsv


# ---------------------------------------------------------------- 指标卡片

def it_fear(force=False):
    d = fng(force)
    if not d.get("ok"):
        return _mk("fear", "恐慌贪婪指数", "", error=d.get("error"))
    rows = d["rows"]
    vals = [r["v"] for r in rows]
    v = vals[-1]
    # 分档：handle_fear.py:104（0-24 极度恐慌 / 25-29 恐惧 / 50-74 贪婪 / 75-100 极度贪婪）
    # 30~49 那段上游只写 "Fear/Neutral"，这里按通用读法叫「中性偏恐」。
    if v <= 24:
        verdict, tone = "极度恐慌（≤24，历史抄底窗口）", "green"
    elif v < 50:
        verdict, tone = "恐慌区", "gray"
    elif v <= 74:
        verdict, tone = "贪婪区", "gray"
    else:
        verdict, tone = "极度贪婪（≥75，历史减仓窗口）", "red"
    return _mk("fear", "恐慌贪婪指数", "0~100", dp=0, value=v, tone=tone, verdict=verdict,
               asof=rows[-1]["d"], src="alternative.me", hist=_hist(rows),
               extras=[{"k": "上游英文分类", "v": rows[-1].get("cls") or "—"},
                       {"k": "昨日", "v": vals[-2] if len(vals) > 1 else None},
                       {"k": "近 7 / 30 天均值", "v": "%s / %s" % (_mean(vals, 7), _mean(vals, 30))},
                       {"k": "近 180 / 365 天均值", "v": "%s / %s" % (_mean(vals, 180), _mean(vals, 365))},
                       {"k": "近 365 天分位", "v": _pct_rank(vals, v)}])


def it_ahr999(force=False):
    d = ahr999(force)
    if not d.get("ok"):
        return _mk("ahr999", "AHR999 定投指数", "倍", error=d.get("error"),
                   note="本模块不自行推算 AHR999：项目里没有可核对的公式口径。")
    v = d["value"]
    # 阈值：[bottom_alert] AHR999_BUY_ZONE_MAX 默认 0.45（operationConfig.py:213）；
    #        [top_alert] ahr999_danger_min = [2,3]（operationConfig.py:328）
    if v < 0.45:
        verdict, tone = "抄底区（<0.45）", "green"
    elif v >= 2:
        verdict, tone = "顶部危险（≥2）", "red"
    else:
        verdict, tone = "中性区间（0.45~2）", "gray"
    return _mk("ahr999", "AHR999 定投指数", "倍", dp=3, value=v, tone=tone, verdict=verdict,
               asof=d["rows"][-1]["d"] if d["rows"] else None, src=d["src"],
               hist=[{"d": r["d"], "v": r["v"]} for r in d["rows"][-HIST_POINTS:]],
               extras=[{"k": "200 日定投成本", "v": d.get("avg200")},
                       {"k": "昨值", "v": d.get("prev")}])


def it_cbbi(force=False):
    d = cbbi(force)
    if not d.get("ok"):
        return _mk("cbbi", "CBBI 牛熊信心指数", "0~100", error=d.get("error"))
    rows = d["rows"]
    vals = [r["v"] for r in rows]
    v = vals[-1]
    # 阈值：底部 cbbi_max=[20,35]、顶部 cbbi_min=[80,85]（operationConfig.py:214,327）
    if v <= 35:
        verdict, tone = "底部区（≤35，≤20 是最硬的那档）", "green"
    elif v >= 80:
        verdict, tone = "顶部区（≥80）", "red"
    else:
        verdict, tone = "中性（35~80）", "gray"
    extras = [{"k": "近 365 天分位", "v": _pct_rank(vals, v)},
              {"k": "取整（页面口径同报表）", "v": int(-(-v // 1))}]
    for p in d.get("parts") or []:
        if p["k"] != "Confidence":
            extras.append({"k": "子指标 " + p["k"], "v": p["v"]})
    return _mk("cbbi", "CBBI 牛熊信心指数", "0~100", dp=1, value=v, tone=tone, verdict=verdict,
               asof=rows[-1]["d"], src=d["src"], hist=_hist(rows), extras=extras,
               note="合成分由上游服务端算（9 个子指标等权），本模块只做 0~1 → 0~100 的换算，不重算。")


def it_cvdd(force=False):
    d = looknode(CVDD_URL, "cvdd", force)
    if not d.get("ok"):
        return _mk("cvdd", "CVDD 累计价值币天销毁", "美元", error=d.get("error"))
    rows = [r for r in d["rows"] if r["v"] > 0] or d["rows"]     # 早期未定义点全是 0，剔掉再画
    v = rows[-1]["v"]
    k = klines(force)
    spot = k.get("spot") if k.get("ok") else None
    mult = 1.05                                # [bottom_alert] CVDD_PRICE_MULT 默认 1.05（operationConfig.py:218）
    if spot is None:
        verdict, tone = "缺现价，无法与 CVDD 比对（K 线源也不可达）", "gray"
    elif spot <= v * mult:
        verdict, tone = "现价 ≤ CVDD×%.2f（历史底部支撑区）" % mult, "green"
    else:
        verdict, tone = "现价在 CVDD 之上 %.0f%%，无底部信号" % ((spot / v - 1) * 100), "gray"
    return _mk("cvdd", "CVDD 累计价值币天销毁", "美元", dp=0, value=v, tone=tone, verdict=verdict,
               asof=rows[-1]["d"], src="Looknode", hist=_hist(rows),
               extras=[{"k": "现价（同一 K 线源收盘）", "v": spot},
                       {"k": "CVDD×%.2f 支撑线" % mult, "v": round(v * mult, 0)},
                       {"k": "现价 / CVDD", "v": round(spot / v, 3) if spot else None},
                       {"k": "近 365 天分位", "v": _pct_rank([r["v"] for r in rows], v)}])


def _ema_item(key, name, force, prefill, note):
    k = klines(force)
    if not k.get("ok"):
        return _mk(key, name, "美元", error=k.get("error"))
    closes = [b["c"] for b in k["bars"]]
    ef, es = _ema(closes, 5, prefill), _ema(closes, 10, prefill)
    verdict, tone = _cross(ef, es, "EMA5", "EMA10")
    rows = [{"d": b["d"], "v": ef[i]} for i, b in enumerate(k["bars"]) if ef[i] is not None]
    return _mk(key, name, "美元", dp=0, value=ef[-1], tone=tone, verdict=verdict,
               asof=k["bars"][-1]["d"], src="日线：" + k["from"],
               hist=_hist(rows),
               extras=[{"k": "EMA5 / EMA10", "v": "%s / %s" % (round(ef[-1], 1), round(es[-1], 1))},
                       {"k": "前一根", "v": "%s / %s" % (round(ef[-2], 1), round(es[-2], 1))},
                       {"k": "EMA5 − EMA10", "v": round(ef[-1] - es[-1], 1)},
                       {"k": "已收盘根数", "v": len(closes)}],
               note=note)


def it_ema(force=False):
    return _ema_item("ema", "EMA5/EMA10 交叉", force, "echo",
                     "播种前填当根收盘（handle_EMA.py:74-87）。用已收盘的日线，当天未收盘那根不参与。")


def it_ema_new(force=False):
    return _ema_item("ema_new", "EMA5/EMA10（新版口径）", force, "none",
                     "与上一格唯一区别：播种前留 None（handle_EMA_new.py:50-68），所以交叉只看最后两根、"
                     "且没有 handle_EMA.py 的「只用已收盘根」开关。数值一致，播种期表现不同。")


def it_kdj(force=False):
    k = klines(force)
    if not k.get("ok"):
        return _mk("kdj", "KDJ(9,3,3) 日线", "", error=k.get("error"))
    kk, dd, jj, rsv = _kdj(k["bars"])
    if kk[-1] is None:
        return _mk("kdj", "KDJ(9,3,3) 日线", "", error="K 线不足 %d 根，算不出 KDJ" % 17)
    verdict, tone = _cross(kk, dd, "K", "D")
    v = jj[-1]
    # 超买/超卖 80/20 是通用读法；cryptoTrader 的 handler 里没有阈值，页面据此标注。
    band = "" if 20 < kk[-1] < 80 else ("（K 超卖 <20）" if kk[-1] <= 20 else "（K 超买 >80）")
    rows = [{"d": b["d"], "v": round(jj[i], 2)} for i, b in enumerate(k["bars"]) if jj[i] is not None]
    return _mk("kdj", "KDJ(9,3,3) 日线", "", dp=2, value=v, tone=tone, verdict=verdict + band,
               asof=k["bars"][-1]["d"], src="日线：" + k["from"], hist=_hist(rows),
               extras=[{"k": "K / D / J", "v": "%s / %s / %s" % (round(kk[-1], 2), round(dd[-1], 2), round(jj[-1], 2))},
                       {"k": "RSV", "v": round(rsv[-1], 2) if rsv[-1] is not None else None},
                       {"k": "已收盘根数", "v": len(k["bars"])}],
               note="K=近 3 根 RSV 算术均值、D=近 3 根 K 算术均值（handle_KDJ.py:120-134），"
                    "不是常见的 1/3 递推平滑；超买超卖阈值上游未定义，80/20 只是通用读法。J 折线为迷你图。")


def it_litb(force=False):
    d = litb(force)
    if not d.get("ok"):
        return _mk("litb", "Look Into Bitcoin 盈利币占比", "%", error=d.get("error"))
    v = d["value"]
    # 分段注释来自 handle_fuckbtc.py:1170 与 [bottom_alert] supply_in_profit_max=[50,55]
    if v < 50:
        verdict, tone = "盈利币占比 <50%（历史大底层）", "green"
    elif v <= 65:
        verdict, tone = "55~65% 区间：熊市中期", "gray"
    else:
        verdict, tone = "盈利币占比 >65%", "gray"
    return _mk("litb", "Look Into Bitcoin 盈利币占比", "%", dp=2, value=v, tone=tone, verdict=verdict,
               asof=d["asof"], src=d["src"], hist=_hist(d["rows"]),
               extras=[{"k": "上游历史点数", "v": len(d["rows"])},
                       {"k": "近 365 天分位", "v": _pct_rank([r["v"] for r in d["rows"]], v)}],
               note="该源已废弃（502），这一格通不通全看它有没有临时恢复；替代口径见 CBBI 的子指标。")


def it_macd(force=False):
    k = klines(force)
    if not k.get("ok"):
        return _mk("macd", "MACD(12,26,9) 日线", "美元", error=k.get("error"))
    closes = [b["c"] for b in k["bars"]]
    line, sig, hist = _macd(closes)
    verdict, tone = _cross(line, sig, "MACD 线", "信号线")
    if line[-1] is None or sig[-1] is None:
        return _mk("macd", "MACD(12,26,9) 日线", "美元", error="K 线不足，MACD 未播种完成")
    rows = [{"d": b["d"], "v": round(line[i], 2)} for i, b in enumerate(k["bars"]) if line[i] is not None]
    return _mk("macd", "MACD(12,26,9) 日线", "美元", dp=0, value=line[-1], tone=tone, verdict=verdict,
               asof=k["bars"][-1]["d"], src="日线：" + k["from"], hist=_hist(rows),
               extras=[{"k": "信号线 EMA9", "v": round(sig[-1], 2)},
                       {"k": "柱状 (MACD−信号)", "v": round(hist[-1], 2)},
                       {"k": "前一根 MACD / 信号", "v": "%s / %s" % (round(line[-2], 2), round(sig[-2], 2))},
                       {"k": "已收盘根数", "v": len(closes)}],
               note="迷你图是 MACD 线本身（不是柱）。信号线只对 macd[25:] 做 EMA9 再补 None（handle_MACD.py:111-117）。")


def _mvrv_vals(d):
    rows = d["rows"]
    return rows, [r["v"] for r in rows]


def it_mvrv(force=False):
    d = mvrv_rows(force)
    if not d.get("ok"):
        return _mk("mvrv", "MVRV 市值/实现市值", "倍", error=d.get("error"))
    rows, vals = _mvrv_vals(d)
    v = vals[-1]
    # 阈值：[bottom_alert] mvrv_max=[0.95,1.0]（operationConfig.py:215）。顶部那档上游没给口径 → 不编。
    if v <= 1.0:
        verdict, tone = "≤1.0：全网浮亏，历史底部区", "green"
    else:
        verdict, tone = "高于 1.0（顶部阈值本模块不设，避免臆造）", "gray"
    return _mk("mvrv", "MVRV 市值/实现市值", "倍", dp=3, value=v, tone=tone, verdict=verdict,
               asof=rows[-1]["d"], src="Looknode", hist=_hist(rows),
               extras=[{"k": "近 365 天分位", "v": _pct_rank(vals, v)},
                       {"k": "近 365 天 最小 / 最大", "v": "%s / %s" % (round(min(vals[-365:]), 3), round(max(vals[-365:]), 3))},
                       {"k": "历史点数", "v": len(rows)}])


def it_nupl(force=False):
    d = mvrv_rows(force)
    if not d.get("ok"):
        return _mk("nupl", "NUPL 净未实现盈亏比", "", error=d.get("error"))
    rows, vals = _mvrv_vals(d)
    nupl = [round(1.0 - 1.0 / v, 4) if v and v > 0 else None for v in vals]   # handle_NUPL.py:287
    series = [{"d": r["d"], "v": n} for r, n in zip(rows, nupl) if n is not None]
    v = series[-1]["v"]
    # 六色档：handle_NUPL.py:17-24（行业标准那段）
    if v > 0.75:
        band, tone = "极度贪婪（>0.75，狂欢/牛市顶部区）", "red"
    elif v > 0.5:
        band, tone = "乐观（0.5~0.75，牛市中期/持有）", "gray"
    elif v > 0.25:
        band, tone = "中性（0.25~0.5，观望）", "gray"
    elif v > 0:
        band, tone = "焦虑（0~0.25，回调/熊市初期）", "gray"
    elif v > -0.25:
        band, tone = "绝望（−0.25~0，熊市中期、接近底部）", "green"
    else:
        band, tone = "极度绝望（<−0.25，历史大底）", "green"
    return _mk("nupl", "NUPL 净未实现盈亏比", "", dp=3, value=v, tone=tone, verdict=band,
               asof=series[-1]["d"], src="Looknode（由 MVRV 推算，免费档）", hist=_hist(series),
               extras=[{"k": "公式", "v": "NUPL = 1 − 1/MVRV"},
                       {"k": "近 365 天分位", "v": _pct_rank([r["v"] for r in series], v)},
                       {"k": "对应 MVRV", "v": round(vals[-1], 4)}],
               note="这是 handle_NUPL.py 的首选免费路径（第 0 档：Looknode MVRV 推算）。"
                    "BM Pro / CryptoQuant / CoinGlass 那些付费源本模块不接（不放密钥）。")


def it_sopr(force=False):
    d = mvrv_rows(force)
    if not d.get("ok"):
        return _mk("sopr", "SOPR Z-Score 链上Z值", "", error=d.get("error"))
    rows, vals = _mvrv_vals(d)
    win = 365                                   # Z_SCORE_WINDOW_DAYS（handle_SOPR_Z-Score.py:55）
    nupl = [1.0 - 1.0 / v for v in vals[-win:] if v and v > 0]
    nz = _zpop(nupl)
    comp = {"nupl_z": nz, "mvrv_z": None, "sopr_z": None}   # 后两个要 Bitbo，实测 401（2026-09-23）
    used = [k for k, x in comp.items() if x is not None]
    if not used:
        return _mk("sopr", "SOPR Z-Score 链上Z值", "", error="三个 Z 分量一个都取不到")
    v = sum(comp[k] for k in used) / len(used)              # 可用分量的算术均值（:360-367）
    # 阈值：z < −0.44 底部区域、z > 0.73 顶部区域（handle_SOPR_Z-Score.py:57-58,284-290）
    if v < -0.44:
        verdict, tone = "底部区域（<−0.44）", "green"
    elif v > 0.73:
        verdict, tone = "顶部区域（>0.73）", "red"
    else:
        verdict, tone = "中性区间（−0.44~0.73）", "gray"
    series = [{"d": r["d"], "v": round(1.0 - 1.0 / r["v"], 4)}
              for r in rows[-win:] if r["v"] and r["v"] > 0]
    return _mk("sopr", "SOPR Z-Score 链上Z值", "", dp=2, value=v, tone=tone, verdict=verdict,
               asof=rows[-1]["d"], src="Looknode（只剩 nupl_z 一个分量）", hist=_hist(series),
               extras=[{"k": "nupl_z", "v": round(nz, 4) if nz is not None else None},
                       {"k": "mvrv_z", "v": "不可得：charts.bitbo.io/api/v1/mvrv-z 401"},
                       {"k": "sopr_z", "v": "不可得：charts.bitbo.io/api/v1/sopr 401"},
                       {"k": "窗口 / 分量", "v": "近 %d 天 · %s" % (win, "、".join(used))}],
               note="上游口径就是「对可用分量取均值」，所以现在这格 = nupl_z 单分量（365 天窗口、总体标准差）。"
                    "它和名字里的 SOPR 已经脱钩，看板上按分量构成如实标注，不改名也不补数。")


def it_two_year_multiply(force=False):
    """2年MA乘数通道（下沿 730MA / 上沿 730MA×5）。头条给上游原值（730MA，美元），本页不重算均线、不重算乘数；
    判据照抄该站上「指标描述」原文：现价 < 730MA = 过度悲观区，现价 > 730MA×5 = 过度贪婪区。
    现价借本页同一 K 线源的收盘，与 it_cvdd 同构；两边的 asof 可以差一天，extras 里各自标明来源。
    放大图另有 `bands`（下沿/上沿/收盘三条线，BAND_POINTS 点、对数轴），对齐上游那张图的画法。"""
    d = looknode_band(TWM_URL, "two_year_multiply", force)
    if not d.get("ok"):
        return _mk("two_year_multiply", "2年MA乘数通道", "美元", error=d.get("error"))
    rows = d["rows"]
    lo, hi = rows[-1]["lo"], rows[-1]["hi"]
    k = klines(force)
    spot = k.get("spot") if k.get("ok") else None
    if spot is None:
        verdict, tone = "缺现价，无法与通道比对（K 线源也不可达）", "gray"
    elif spot < lo:
        verdict, tone = "现价 < 730MA（上游口径：过度悲观区）", "green"
    elif spot > hi:
        verdict, tone = "现价 > 730MA×5（上游口径：过度贪婪区）", "red"
    else:
        verdict, tone = "现价在通道内（730MA ~ 730MA×5）", "gray"
    # 放大图的三条线：下沿/上沿来自通道接口，收盘来自 Yahoo（另一家，起点 2014-09，比通道晚两年多）。
    # 价格源挂了不判这张卡失败——头条与判据都不依赖它，只是图上少一条线，所以缺口写进 extras 而不是 error。
    c = btc_closes(force)
    px = {r["d"]: r["v"] for r in c.get("rows") or []}
    bands = _band_hist(rows, px)
    got = [d for d in sorted(px) if rows and d >= rows[0]["d"]]
    price_note = ("%s → %s，%d 天" % (got[0], got[-1], len(got))) if got else "取数失败：" + str(c.get("error") or "无响应")[:60]
    return _mk("two_year_multiply", "2年MA乘数通道", "美元", dp=0, value=lo, tone=tone, verdict=verdict,
               asof=rows[-1]["d"], src="Looknode",
               hist=_hist([{"d": r["d"], "v": r["lo"]} for r in rows]),      # 迷你图画的是下沿自身
               bands=bands,
               extras=[{"k": "通道上沿（730MA×5）", "v": round(hi, 0)},
                       {"k": "现价（同一 K 线源收盘）", "v": spot},
                       {"k": "现价 / 730MA", "v": round(spot / lo, 3) if spot else None},
                       {"k": "近 365 天分位（下沿自身）", "v": _pct_rank([r["lo"] for r in rows], lo)},
                       {"k": "序列起点 / 点数", "v": "%s · %d" % (rows[0]["d"], len(rows))},
                       {"k": "价格线覆盖（Yahoo BTC-USD，按最近交易日对齐）", "v": price_note}],
               note="「730 天」与「×5」是上游按历史回测挑的一组数值，它页面原文自己留了话：BTC 体量变大、牛熊振幅收窄后这组数值"
                    "的效果可能打折，需要重新挑。本页只照抄它的两条线与它的判据，没有另设阈值。")


# 这一张表**就是页面的显示顺序**（`summary()` 用 `pool.map` 并行取数但保序返回，页面照 `items[]` 原样铺卡，
# 所以改这里就等于改卡片顺序，前端不用另存一份）。前三行按读图重要性排：
#   ① 恐慌贪婪 + AHR999 ② 2年MA乘数通道 + CBBI ③ EMA5/EMA10（新版）+ KDJ。
# 剩下七张是**固定顺序**（沿用原来的相对次序），没做每轮随机：页面 15 分钟自动刷一次，
# 随机换序会让卡片每次刷新跳位置，「刚看的那张卡去哪了」比顺序不好看更糟。真要换序就改这张表。
INDICATORS = [
    ("fear", it_fear), ("ahr999", it_ahr999),
    ("two_year_multiply", it_two_year_multiply), ("cbbi", it_cbbi),
    ("ema_new", it_ema_new), ("kdj", it_kdj),
    ("cvdd", it_cvdd), ("ema", it_ema), ("litb", it_litb), ("macd", it_macd),
    ("mvrv", it_mvrv), ("nupl", it_nupl), ("sopr", it_sopr),
]
_KEYS = [k for k, _ in INDICATORS]

# 入库标识（api/db.py 落库时照这个走，页面每张卡的「入库」小标也读它）：全部项**一律**入日读数，包括取数失败的那张——失败行 value=NULL + error 有值，
# 否则「哪天哪个源断了」这种事后最想查的东西在库里没有痕迹（表结构见 sql/board_schema.sql）。
# 历史序列（hist[]）只要那张卡本轮给了点就一并入 board_series_daily，键带 btc: 前缀。
STORE_DAILY = set(_KEYS)


def _stamp(card):
    """给一张卡盖入库标识：`store` = "daily+hist" / "daily" / ""（空 = 不入库）。"""
    key = card.get("key")
    if key not in STORE_DAILY:
        card["store"] = ""
    else:
        card["store"] = "daily+hist" if card.get("hist") else "daily"
    return card


def one(key, force=False):
    for k, fn in INDICATORS:
        if k == key:
            try:
                return _stamp(fn(force))
            except Exception as e:                       # 一个指标崩了不该带崩整页
                log.exception("[btc] 指标 %s 计算异常", key)
                return _stamp(_mk(key, key, "", error="计算异常：" + str(e)[:120]))
    return None


def summary(force=False):
    """各项并行取数（每台主机自己串行，跨主机并行），整体约 8~12 秒，之后走各自的缓存。
    末尾的 `db.store_btc` 是**旁路**：没启用/连不上都只写一行日志，取数结果照原样返回。"""
    t0 = datetime.now(timezone.utc)
    with ThreadPoolExecutor(max_workers=5) as pool:
        items = list(pool.map(lambda kv: one(kv[0], force), INDICATORS))
    k = klines(force)
    good = [i for i in items if i.get("ok")]
    ms = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
    out = {"ok": bool(good), "items": items,
           "count": {"total": len(items), "ok": len(good), "failed": len(items) - len(good)},
           "order": _KEYS, "live_age": LIVE_AGE, "hist_points": HIST_POINTS,
           "elapsed_ms": ms,
           "spot": k.get("spot") if k.get("ok") else None,
           "kline_from": k.get("from") if k.get("ok") else None,
           "asof": k["bars"][-1]["d"] if k.get("ok") else None,
           "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
           "failed": [{"key": i["key"], "error": i.get("error")} for i in items if not i.get("ok")]}
    log.info("[btc] summary：%d/%d 项有数，现价 %s，日线源 %s，用时 %dms；缺位 %s",
             len(good), len(items), out.get("spot"), out.get("kline_from"), ms,
             "、".join(x["key"] for x in out["failed"]) or "无")
    try:
        db.store_btc(out)
    except Exception as e:                               # 落库层不该把页面带崩（它的异常本该自己吞，双保险）
        log.warning("[btc] 入库旁路异常（忽略）：%s: %s", type(e).__name__, str(e)[:120])
    return out


# ---------------------------------------------------------------- 路由

def _force(q):
    return q.get("force") == ["1"]


def r_health(q):
    return 200, {"ok": True, "module": "btc", "indicators": _KEYS,
                 "sources": ["binance/kraken/okx/coinbase/bybit 日线", "alternative.me",
                             "colintalkscrypto.com", "looknode.com", "coinsoto/soulbab/coinglass",
                             "production.lookintobitcoin.com"],
                 "live_age": LIVE_AGE, "hist_points": HIST_POINTS}


def r_summary(q):
    d = summary(_force(q))
    return (200 if d.get("ok") else 502), d


def r_one(q):
    key = (q.get("k") or [""])[0]
    if key not in _KEYS:
        return 400, {"ok": False, "error": "未知指标，允许: " + ",".join(_KEYS)}
    d = one(key, _force(q))
    return (200 if d.get("ok") else 502), d


ROUTES = {"health": r_health, "summary": r_summary, "one": r_one}


def warm():
    """本机版启动时打一轮，首屏就不空等；公网版（warm=False）交给首个请求。"""
    d = summary(True)
    log.info("[warm] btc：%d/%d 项有数（缺位：%s）", d["count"]["ok"], d["count"]["total"],
             "、".join(x["key"] for x in d["failed"]) or "无")
