# -*- coding: utf-8 -*-
"""宏观流动性监控 —— 数据取数服务（Python 标准库，零依赖）

监听 127.0.0.1:4319，对页面提供与官方节点同源的桥接接口：
  /api/health                     探活 + 显示当前代理
  /api/fred?series=KEY[&force=1]  FRED 官方 CSV（13 个白名单序列）
  /api/treasury[?force=1]         美国财政部每日收益率曲线（10Y）
  /api/btc[?force=1]              5 家交易所中位数现价 + 120/200 日均线
其余路径按静态文件返回（同目录下的 macro-liquidity.html 等）。

代理：读 config.ini（[proxy]），同名环境变量优先覆盖。

日志：每次接口请求、每一笔上游取数、每一家交易所报价都写入 <项目>/logs/fetch_server.log
（每日轮转，保留 14 天）。目录与级别见 config.ini 的 [log]，或 LOG_DIR / LOG_LEVEL 环境变量。
"""
import configparser
import csv
import io
import json
import logging
import os
import re
import socket
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import TimedRotatingFileHandler
from urllib.parse import urlparse, parse_qs, unquote

try:
    import ccxt                      # 行情/日线取数用（pip install ccxt）
except ImportError:
    ccxt = None

ROOT = os.path.dirname(os.path.abspath(__file__))   # 静态文件按脚本所在目录解析，IDE 从别处启动也能用

CONFIG = os.environ.get("CONFIG") or os.path.join(ROOT, "config.ini")
# config.ini 的键 → 环境变量。语义与原 main.py 的 setdefault 完全一致：环境已有值就不覆盖，
# 所以「临时改一次」用 set XXX=... 即可，不必动文件；两个入口都走这里，配置只留一处。
CONFIG_ENV = {("proxy", "http"): "HTTP_PROXY", ("proxy", "https"): "HTTPS_PROXY",
              ("server", "port"): "PORT", ("log", "dir"): "LOG_DIR", ("log", "level"): "LOG_LEVEL",
              ("page", "show_fix"): "SHOW_FIX"}
# 只有这几项可以是相对路径，按项目目录解析；其余（如代理地址）原样交给上游
CONFIG_ABS = {"LOG_DIR"}


def apply_config():
    """读 config.ini 填充未设置的环境变量；文件缺失或某项为空则跳过，交由各常量自己的兜底。"""
    cfg = configparser.ConfigParser()
    read = cfg.read(CONFIG, encoding="utf-8")
    for (sect, opt), env in CONFIG_ENV.items():
        if env in os.environ:
            continue
        val = cfg.get(sect, opt, fallback="").strip()
        if not val:
            continue
        if env in CONFIG_ABS and not os.path.isabs(val):
            val = os.path.join(ROOT, val)
        os.environ[env] = val
    return bool(read)


HAS_CONFIG = apply_config()

try:
    PORT = int(os.environ.get("PORT") or 4319)
except ValueError:
    PORT = 4319
    print("config.ini 的 [server] port 不是数字，已退回 4319")
PROXY = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or ""
# 页面「修订记录」开关（config.ini [page] show_fix）；只在返回 HTML 时替换标记，双击直接打开文件不经服务、按默认展示
SHOW_FIX = "0" if (os.environ.get("SHOW_FIX") or "1").strip().lower() in ("0", "false", "no") else "1"

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

MIME = {".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript",
        ".svg": "image/svg+xml", ".json": "application/json", ".ico": "image/x-icon"}
# 非 Mozilla 签名的标识：财政部 / 4 家行情源 / FRED 均接受（实测）
UA = "python-macro-dashboard/1.0 (local liquidity monitor)"

cache = {}
cache_lock = threading.Lock()
_inflight = {}                             # key -> Lock：同键并发只放一个去上游，其余等结果复用
_ver = {}                                  # key -> 成功写入次数；判「排队期间是否有人取完了」
                                           # 不用时间戳比大小：Windows 下 time.time() 粒度约 15.6ms，
                                           # 同刻度内会误判成「刚取过」而让 force=1 跳过重取。
_EX = {}                                   # ccxt 交易所实例（load_markets 结果随实例复用）
# 上游分两条队列：FRED 对并发请求会限流并返回 HTML，行情源并发会被 CDN 拦掉，各自内部必须串行；
# 但两者是不同主机，此前共用一把锁导致冷启动时 13 个 FRED 序列整体排在 ccxt 预热（实测 40~60 秒）
# 之后，页面首屏因此退回快照。分开排队后互不阻塞。
gov_lock = threading.Lock()                # FRED + 美国财政部
mkt_lock = threading.Lock()                # ccxt 行情源


def now_ms():
    return time.time()


def _one(e):
    """异常信息压成单行：交易所的错误体常是多行 JSON，只取首行足够定位。"""
    return str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__


def _short(e):
    """给页面和日志看的短因由：ccxt 的错误首行是「交易所名 GET 整条 URL」，先看状态码，
    再把 URL 剔掉只留错误性质，否则一条日志被 URL 占满。"""
    s = _one(e)
    code = getattr(e, "last_http_status", None)
    if not code:
        m = re.search(r"\b([45]\d{2})\b", s)
        code = m.group(1) if m else None
    if code:
        return "HTTP %s" % code
    s = re.sub(r"https?://\S+", "", s)
    s = re.sub(r"^\s*\w+\s+(?:GET|POST)\s+", "", s).strip()
    return (s or type(e).__name__)[:40]


# ---------------------------------------------------------------- 日志
LOG_DIR = os.environ.get("LOG_DIR") or os.path.join(ROOT, "logs")
LOG_NAME = "fetch_server.log"
log = logging.getLogger("macro")
_log_ready = False


def setup_logging():
    """把日志装到 <项目>/logs/fetch_server.log；轮转为每日一切，保留 14 天。

    只在 serve() 里调用一次；未安装时 log.* 也不会报错（Python 无 handler 时向上冒泡到
    root logger，最后被 discard），所以模块被 import 做单测时同样安全。
    日志目录不可写只降级为控制台输出，绝不能拖垮取数。
    """
    global _log_ready
    if _log_ready:
        return log
    level = (os.environ.get("LOG_LEVEL") or "INFO").upper()
    log.setLevel(getattr(logging, level, logging.INFO))
    log.propagate = False
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)-5s %(message)s", "%Y-%m-%d %H:%M:%S")
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        fh = TimedRotatingFileHandler(os.path.join(LOG_DIR, LOG_NAME),
                                      when="midnight", backupCount=14, encoding="utf-8")
        fh.setFormatter(fmt)
        log.addHandler(fh)
        log.info("===== 日志启动 pid=%d level=%s 目录=%s =====", os.getpid(), level, LOG_DIR)
    except OSError as e:
        print("日志目录不可写（%s），改为仅输出到控制台" % _one(e))
        sys.stdout.flush()
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        log.addHandler(sh)
    _log_ready = True
    return log


def _ms(t0):
    return int((time.perf_counter() - t0) * 1000)


def _urltag(url):
    """日志里只留主机 + 路径 + FRED 序列号：完整 URL 带两个日期参数，太长且每次一样地占位。"""
    u = urlparse(url)
    ids = parse_qs(u.query).get("id") or []
    return u.netloc + u.path + ("?id=" + ids[0] if ids else "")


def remote(url, as_json=False, ms=20000, tag="up"):
    handlers = []
    if PROXY:
        handlers.append(urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, headers={
        # FRED 的边缘节点会挂起「请求头过于简洁」的客户端连接（实测：只带 UA+Accept 时 read 超时；
        # 补齐下面这组常规头后 1~3 秒返回）。Node fetch / curl 不受影响，Python 必须带全。
        "user-agent": UA,
        "accept": "application/json" if as_json else "text/csv,*/*",
        "accept-language": "en-US,en;q=0.9",
        "accept-encoding": "identity",
        "cache-control": "no-cache",
        "upgrade-insecure-requests": "1",
    })
    deadline = ms / 1000.0
    t0 = time.perf_counter()
    err = None
    body = ""
    try:
        with opener.open(req, timeout=deadline) as r:
            if r.status >= 400:
                raise RuntimeError("HTTP %d" % r.status)
            body = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        err = "HTTP %d" % e.code
    except (socket.timeout, TimeoutError):
        err = "超时"
    except urllib.error.URLError as e:
        err = str(e.reason)[:60] or "网络不可达"
    if err is None and ("<html" in body[:400].lower() or "<!doctype" in body[:400].lower()
                        or "Object moved" in body[:400]):
        err = "上游返回 HTML（可能被限流）"
    used = _ms(t0)
    if err:
        log.warning("[%s] 上游失败 %dms  %s  ::  %s", tag, used, _urltag(url), err)
        raise RuntimeError(err)
    log.info("[%s] 上游 OK %dms  %s  (%d 字符)", tag, used, _urltag(url), len(body))
    return json.loads(body) if as_json else body


def cached(key, ttl, run, force):
    """命中且未过期直接返回；取数失败时退回上一次成功结果。

    同键并发做 single-flight：实测启动预热与页面首屏的 force=1 会同时打同一个键，
    导致上游被重复请求两次（行情源本就容易限流），故排队者直接复用先行者的结果。
    """
    with cache_lock:
        hit = cache.get(key)
        ver0 = _ver.get(key, 0)
        lock = _inflight.setdefault(key, threading.Lock())
    if hit and not force and now_ms() - hit[0] < ttl:
        log.debug("[cache] %-12s 命中 age=%ds/%ds", key, int(now_ms() - hit[0]), ttl)
        return hit[1]
    t_wait = time.perf_counter()
    with lock:
        with cache_lock:
            newest = cache.get(key)
            newer = _ver.get(key, 0) != ver0          # 排队期间已有同键请求取数完成
        if newest and (newer or (not force and now_ms() - newest[0] < ttl)):
            log.info("[cache] %-12s 复用并发请求的结果（排队 %dms，未重复打上游）", key, _ms(t_wait))
            return newest[1]
        used0 = _ms(t_wait)
        t0 = time.perf_counter()
        data = run()
        used = _ms(t0)
        data["cached_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        why = "强制穿透" if force else ("过期重取" if hit else "首次取数")
        if used0:
            why += "（排队 %dms）" % used0
        with cache_lock:
            if data.get("ok"):
                log.info("[cache] %-12s %s OK %dms（TTL %ds）", key, why, used, ttl)
                cache[key] = (now_ms(), data)
                _ver[key] = _ver.get(key, 0) + 1
            elif newest:
                log.warning("[cache] %-12s %s 失败 %dms: %s → 沿用 %ds 前的旧值（页面标为快照）",
                            key, why, used, data.get("error") or "未知错误",
                            int(now_ms() - newest[0]))
                return newest[1]
            else:
                log.warning("[cache] %-12s %s 失败 %dms: %s（无旧值可退）",
                            key, why, used, data.get("error") or "未知错误")
        return data


def parse_fred(text, sid):
    rows = []
    for line in text.strip().splitlines()[1:]:
        parts = line.split(",")
        if len(parts) < 2:
            continue
        d, v = parts[0].strip().strip('"'), parts[1].strip()
        if not d or v == "." or v == "":
            continue
        try:
            rows.append({"d": d, "v": float(v)})
        except ValueError:
            pass
    return {"ok": True, "series": sid, "rows": rows, "latest": rows[-1] if rows else None}


def fred(key, force):
    sid, ttl, unit = SERIES[key]
    today = date.today()
    url = ("https://fred.stlouisfed.org/graph/fredgraph.csv?id=%s&cosd=%s&coed=%s"
           % (sid, (today - timedelta(days=480)).isoformat(), today.isoformat()))

    def run():
        with gov_lock:
            out = parse_fred(remote(url, tag="fred:" + sid), sid)
        rows = out["rows"]
        log.info("[fred] %s 解析 %d 行  最新 %s=%s  区间起点 %s",
                 sid, len(rows),
                 rows[-1]["d"] if rows else "—", rows[-1]["v"] if rows else "—",
                 rows[0]["d"] if rows else "—")
        if not rows:
            log.warning("[fred] %s 无有效观测值（上游可能改了口径或该序列被撤）", sid)
        return out

    out = cached("fred:" + key, ttl, run, force)
    out = dict(out)
    out["unit"] = unit
    out["source"] = "FRED " + sid
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
                    errs.append("%s: %s" % (eid, _short(e)))
                    log.warning("[btc] 日线 %s 失败 %dms: %s", eid, _ms(t0), _short(e))
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
                    quotes.append({"n": eid, "err": _short(e)})
                    log.warning("[btc] 现价 %s 失败 %dms: %s", eid, _ms(e0), _short(e))
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


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self._status, self._size = code, len(body)
        self.send_response(code)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", "no-store")
        self.send_header("access-control-allow-origin", "*")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            log.warning("[http] 响应中断（客户端提前断开）%s %s", self.command, self.path)

    def do_GET(self):
        t0 = time.perf_counter()
        self._status, self._size = 0, 0
        u = urlparse(self.path)
        q = parse_qs(u.query)
        force = q.get("force", [""]) == ["1"]
        p = unquote(u.path)
        try:
            if p == "/api/health":
                return self._send(200, json.dumps(
                    {"ok": True, "runtime": "python %s" % sys.version.split()[0],
                     "proxy": PROXY or "(未配置)", "config": CONFIG, "config_loaded": HAS_CONFIG,
                     "show_fix": SHOW_FIX, "log_dir": LOG_DIR,
                     "time": datetime.now().astimezone().isoformat(timespec="seconds")}))
            if p == "/api/fred":
                k = (q.get("series") or [""])[0]
                if k not in SERIES:
                    log.warning("[http] 拒绝白名单外的序列 series=%r", k[:40])
                    return self._send(400, json.dumps({"ok": False, "error":
                        "未知序列，允许: " + ",".join(SERIES)}, ensure_ascii=False))
                d = fred(k, force)
                return self._send(200 if d.get("ok") else 502, json.dumps(d, ensure_ascii=False))
            if p == "/api/btc":
                d = btc(force)
                if force:
                    log.info("[http] 页面强制刷新 BTC（force=1）")
                return self._send(200 if d.get("ok") else 502, json.dumps(d, ensure_ascii=False))
            if p == "/api/treasury":
                d = treasury(force)
                return self._send(200 if d.get("ok") else 502, json.dumps(d, ensure_ascii=False))

            rel = os.path.normpath(p.lstrip("/") or "index.html")
            if rel.startswith("..") or os.path.isabs(rel):
                log.warning("[http] 拒绝越界路径 %r", p[:120])
                return self._send(400, "bad path", "text/plain")
            with open(os.path.join(ROOT, rel), "rb") as fh:
                body = fh.read()
            ext = os.path.splitext(rel)[1].lower()
            if ext == ".html":
                body = body.replace(b"{{SHOW_FIX}}", SHOW_FIX.encode())
            return self._send(200, body, MIME.get(ext, "application/octet-stream"))
        except Exception as e:
            log.exception("[http] 处理 %s 时异常: %s", self.path, _one(e)[:160])
            if p.startswith("/api/"):
                return self._send(502, json.dumps(
                    {"ok": False, "error": str(e)[:160]}, ensure_ascii=False))
            return self._send(404, "not found", "text/plain")
        finally:
            log.info("[http] %s %s -> %s %dB %dms", self.command, self.path,
                     self._status or "未响应", self._size, _ms(t0))


def serve(open_panel=False):
    setup_logging()
    ThreadingHTTPServer.daemon_threads = True
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = "http://127.0.0.1:%d/macro-liquidity.html" % PORT
    print("宏观流动性服务已启动 %s  代理=%s" % (url, PROXY or "(未配置，见 config.ini 或 HTTPS_PROXY)"))
    print("日志：%s" % os.path.join(LOG_DIR, LOG_NAME))
    print("配置：%s%s" % (CONFIG, "" if HAS_CONFIG else "（未找到，使用内置默认值）"))
    sys.stdout.flush()
    log.info("服务监听 127.0.0.1:%d  代理=%s  配置=%s(%s)  行情源=%s  白名单 %d 个序列  修订记录=%s",
             PORT, PROXY or "(未配置)", CONFIG, "已加载" if HAS_CONFIG else "未找到",
             ",".join(BTC_EX), len(SERIES), "展示" if SHOW_FIX == "1" else "隐藏")
    if open_panel or "--open" in sys.argv or os.environ.get("OPEN_PANEL"):
        # 端口来自 config.ini，故由服务自己开页，避免启动器写死 4319
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    if ccxt is None:
        print("提示：未安装 ccxt，BTC 卡片将显示取数失败（python -m pip install ccxt）")
    else:
        # 首个请求要为每家交易所 load_markets（实测约 27 秒），启动时先预热，页面首屏才不会空等
        def warm():
            t0 = time.perf_counter()
            r = btc(True)
            log.info("[warm] 行情预热%s 用时 %dms  现价=%s 可达源=%d",
                     "成功" if r.get("ok") else "失败", _ms(t0),
                     r.get("spot") if r.get("ok") else r.get("error"), r.get("n") or 0)
        threading.Thread(target=warm, daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log.info("===== 收到 Ctrl+C，服务退出 =====")
        raise


if __name__ == "__main__":
    serve()
