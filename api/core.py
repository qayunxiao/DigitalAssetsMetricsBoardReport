# -*- coding: utf-8 -*-
"""DigitalAssetsMetricsBoard 公共核心层（Python 标准库，零依赖）

合并服务唯一的「基础设施」：config.ini 读取、带代理的上游取数、TTL 缓存 +
single-flight、上游串行队列、日志、HTTP 路由与静态文件。

三个子模块（api/liquidity.py、api/crash.py、api/allocation.py）只写取数与
判级逻辑，通过 register(name, routes, warm) 把 /api/<name>/* 挂进来；
app.py 负责装配，两个入口都用它：main.py（本机 ThreadingHTTPServer）与
passenger_wsgi.py（公网 Passenger/WSGI，见 README 第 11 节）。

路由签名：fn(q) -> (status:int, obj)，obj 为 dict/list（自动 json.dumps）或 str/bytes。
q 为 parse_qs 结果，核心层已解析 q["force"] == ["1"] 的强制穿透标志到 ctx.force。

安全边界：本地版只监听 127.0.0.1；公网版（PUBLIC=1）额外收敛——静态文件只放
页面/样式/脚本/图标（config.ini、api/*.py、logs 不可下载），路径穿越一律 400。
持仓报告不设访问凭据（2026-09-22 用户定：报表正文发到他自己的 Telegram，公网点了就跑），
只有 `[report] daily_limit` / `us_daily_limit` 的每日次数上限（加密、美股各自计数）和 `_report_lock` 的串行锁挡着。
所有上游 URL 必须写在模块代码里的固定白名单（FRED 序列键、有限的行情/API 端点），
本服务绝不代理任意 URL。
"""
import configparser
import json
import logging
import os
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import date, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import TimedRotatingFileHandler
from urllib.parse import urlparse, parse_qs, unquote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 项目根目录
API_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG = os.environ.get("CONFIG") or os.path.join(ROOT, "config.ini")
# config.ini 的键 → 环境变量。语义：环境已有值就不覆盖（临时改一次用 set，不必动文件）。
CONFIG_ENV = {("proxy", "http"): "HTTP_PROXY", ("proxy", "https"): "HTTPS_PROXY",
              ("server", "port"): "PORT", ("log", "dir"): "LOG_DIR", ("log", "level"): "LOG_LEVEL",
              ("page", "show_fix"): "SHOW_FIX", ("server", "public"): "PUBLIC",
              ("report", "python"): "REPORT_PY", ("report", "crypto_script"): "REPORT_CRYPTO_SCRIPT",
              ("report", "us_script"): "REPORT_US_SCRIPT",
              ("report", "daily_limit"): "REPORT_DAILY_LIMIT",
              ("report", "us_daily_limit"): "REPORT_US_DAILY_LIMIT"}
CONFIG_ABS = {"LOG_DIR", "REPORT_CRYPTO_SCRIPT", "REPORT_US_SCRIPT"}


def apply_config():
    """读 config.ini 填充未设置的环境变量；文件缺失或某项为空则跳过，交由各常量兜底。

    有些键的值是**这台 Windows 机器上的绝对路径**，同一个文件传到 FreeBSD/Linux 服务器上根本
    不存在那个东西，照抄只会让功能全废，所以非 nt 一律跳过：
      `[proxy]` 本机代理客户端的 127.0.0.1 端口；
      `[report] python` cryptoTrader 自己的 venv 解释器（服务器上用代码里的 Linux/FreeBSD 默认值）。
    非 Windows 真要用代理/换解释器，显式给环境变量即可（环境变量本来就优先于文件，这条路径不受影响）。"""
    cfg = configparser.ConfigParser()
    read = cfg.read(CONFIG, encoding="utf-8")
    win_only = os.name != "nt"
    for (sect, opt), env in CONFIG_ENV.items():
        if env in os.environ:
            continue
        if win_only and (sect == "proxy" or (sect, opt) == ("report", "python")):
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
    PORT = int(os.environ.get("PORT") or 8888)
except ValueError:
    PORT = 8888
    print("config.ini 的 [server] port 不是数字，已退回 8888")
PROXY = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or ""
SHOW_FIX = "0" if (os.environ.get("SHOW_FIX") or "1").strip().lower() in ("0", "false", "no") else "1"
# 公网模式：由 passenger_wsgi.py 写死，或在 config.ini 的 [server] public = 1 打开。
# 它只影响「对外暴露什么」，不改取数逻辑：见 dispatch() 里的静态白名单与 `apply_config()` 跳过
# Windows 专用绝对路径那两条。
PUBLIC = (os.environ.get("PUBLIC") or "").strip().lower() in ("1", "true", "yes", "on")

LOG_DIR = os.environ.get("LOG_DIR") or os.path.join(ROOT, "logs")
LOG_NAME = "board_server.log"
log = logging.getLogger("board")
_log_ready = False

MIME = {".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript",
        ".svg": "image/svg+xml", ".json": "application/json", ".ico": "image/x-icon"}
# 公网模式下只允许这些后缀作为静态文件被读到，其余（config.ini、api/*.py、logs/、data/）一律 404，
# 免得别人顺着 URL 把本机路径配置和源码拉走。本地版不受此限制（本来就只监听 127.0.0.1）。
STATIC_ALLOW = {".html", ".css", ".js", ".svg", ".ico"}
JSON_CT = "application/json; charset=utf-8"
# 非 Mozilla 签名的标识：财政部 / FRED / 行情源均接受（实测）。CNN dataviz 例外，需浏览器 UA（见下）。
UA = "python-digital-assets-board/1.0 (local metrics dashboard)"
UA_BROWSER = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

cache = {}
cache_lock = threading.Lock()
_inflight = {}          # key -> Lock：同键并发只放一个去上游，其余等结果复用
_ver = {}               # key -> 成功写入次数；判「排队期间是否有人取完了」。
                        # 不用时间戳比大小：Windows 下 time.time() 粒度约 15.6ms，会误判。
# 上游分两条队列：FRED 对并发请求限流并返回 HTML，行情源并发会被 CDN 拦掉，各自内部必须串行；
# 两者是不同主机，共用一把锁会让慢队列（行情预热 40~60s）阻塞快队列（FRED 约 11s）。
gov_lock = threading.Lock()    # FRED / 财政部 / multpl / gurufocus / CNBC / Yahoo 等 HTTP 源
mkt_lock = threading.Lock()    # ccxt 行情源


def one_line(e):
    """异常信息压成单行：上游错误体常是多行 JSON，首行足够定位。"""
    s = str(e).strip().splitlines()
    return s[0] if s else type(e).__name__


def short_err(e):
    """给页面和日志看的短因由：优先 HTTP 状态码，否则去掉 URL 只留错误性质。"""
    s = one_line(e)
    code = getattr(e, "last_http_status", None)
    if not code:
        m = re.search(r"\b([45]\d{2})\b", s)
        code = m.group(1) if m else None
    if code:
        return "HTTP %s" % code
    s = re.sub(r"https?://\S+", "", s)
    s = re.sub(r"^\s*\w+\s+(?:GET|POST)\s+", "", s).strip()
    return (s or type(e).__name__)[:40]


def setup_logging():
    """日志写 <项目>/logs/board_server.log；每日轮转留 14 天，目录不可写只降级为控制台。"""
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
        print("日志目录不可写（%s），改为仅输出到控制台" % one_line(e))
        sys.stdout.flush()
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        log.addHandler(sh)
    _log_ready = True
    return log


def _ms(t0):
    return int((time.perf_counter() - t0) * 1000)


def _urltag(url):
    u = urlparse(url)
    ids = parse_qs(u.query).get("id") or parse_qs(u.query).get("series_id") or []
    return u.netloc + u.path + ("?id=" + ids[0] if ids else "")


def remote(url, as_json=False, ms=20000, tag="up", browser_ua=False, headers=None,
           expect_html=False):
    """经代理 GET 上游。默认带全套常规头：FRED 边缘节点会挂起「请求头过简」的 Python 客户端
    （实测只带 UA+Accept 时读超时，补齐 Accept-Language/Encoding/Cache-Control 后 1~3 秒返回）。
    browser_ua=True 用于认浏览器签名的源（CNN dataviz，否则返回 418）。
    expect_html=True 用于刻意抓 HTML 的源（multpl/gurufocus），跳过 CSV 限流嗅探。"""
    handlers = []
    if PROXY:
        handlers.append(urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
    opener = urllib.request.build_opener(*handlers)
    hdr = {
        "user-agent": UA_BROWSER if browser_ua else UA,
        "accept": "application/json" if as_json else "application/json,text/csv,text/html,*/*",
        "accept-language": "en-US,en;q=0.9",
        "accept-encoding": "identity",
        "cache-control": "no-cache",
        "upgrade-insecure-requests": "1",
    }
    if browser_ua:
        hdr["referer"] = "https://www.cnn.com/"
    if headers:
        hdr.update(headers)
    req = urllib.request.Request(url, headers=hdr)
    t0 = time.perf_counter()
    err = None
    body = ""
    try:
        with opener.open(req, timeout=ms / 1000.0) as r:
            if r.status >= 400:
                raise RuntimeError("HTTP %d" % r.status)
            body = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        err = "HTTP %d" % e.code
    except (socket.timeout, TimeoutError):
        err = "超时"
    except urllib.error.URLError as e:
        err = str(e.reason)[:60] or "网络不可达"
    if err is None and not expect_html \
            and ("<html" in body[:400].lower() or "Object moved" in body[:400]) and not as_json:
        err = "上游返回 HTML（可能被限流）"
    used = _ms(t0)
    if err:
        log.warning("[%s] 上游失败 %dms  %s  ::  %s", tag, used, _urltag(url), err)
        raise RuntimeError(err)
    log.info("[%s] 上游 OK %dms  %s  (%d 字符)", tag, used, _urltag(url), len(body))
    return json.loads(body) if as_json else body


def cached(key, ttl, run, force):
    """命中且未过期直接返回；取数失败时退回上一次成功结果（页面据此标「○ 快照」）。
    同键并发 single-flight：排队者复用先行者结果，不重复打上游。"""
    with cache_lock:
        hit = cache.get(key)
        ver0 = _ver.get(key, 0)
        lock = _inflight.setdefault(key, threading.Lock())
    if hit and not force and time.time() - hit[0] < ttl:
        log.debug("[cache] %-16s 命中 age=%ds/%ds", key, int(time.time() - hit[0]), ttl)
        return hit[1]
    t_wait = time.perf_counter()
    with lock:
        with cache_lock:
            newest = cache.get(key)
            newer = _ver.get(key, 0) != ver0
        if newest and (newer or (not force and time.time() - newest[0] < ttl)):
            log.info("[cache] %-16s 复用并发请求的结果（排队 %dms，未重复打上游）", key, _ms(t_wait))
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
                log.info("[cache] %-16s %s OK %dms（TTL %ds）", key, why, used, ttl)
                cache[key] = (time.time(), data)
                _ver[key] = _ver.get(key, 0) + 1
            elif newest:
                log.warning("[cache] %-16s %s 失败 %dms: %s → 沿用 %ds 前的旧值（页面标为快照）",
                            key, why, used, data.get("error") or "未知错误",
                            int(time.time() - newest[0]))
                return newest[1]
            else:
                log.warning("[cache] %-16s %s 失败 %dms: %s（无旧值可退）",
                            key, why, used, data.get("error") or "未知错误")
        return data


def parse_fred_csv(text, sid):
    """fredgraph.csv → {ok, series, rows[{d,v}], latest}；缺测点（"."）跳过。"""
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


def fred_series(cache_key, sid, ttl, force, days=480, tag="fred"):
    """共享的 FRED 官方 CSV 取数（fredgraph.csv 免 key，经代理、gov_lock 串行、TTL 缓存）。
    三个子模块都从这里取官方序列，不再各自实现一份。"""
    today = date.today()
    url = ("https://fred.stlouisfed.org/graph/fredgraph.csv?id=%s&cosd=%s&coed=%s"
           % (sid, (today - timedelta(days=days)).isoformat(), today.isoformat()))

    def run():
        with gov_lock:
            out = parse_fred_csv(remote(url, tag="%s:%s" % (tag, sid)), sid)
        rows = out["rows"]
        log.info("[%s] %s 解析 %d 行  最新 %s=%s  区间起点 %s",
                 tag, sid, len(rows),
                 rows[-1]["d"] if rows else "—", rows[-1]["v"] if rows else "—",
                 rows[0]["d"] if rows else "—")
        if not rows:
            log.warning("[%s] %s 无有效观测值（上游可能改了口径或该序列被撤）", tag, sid)
        return out

    out = dict(cached(cache_key, ttl, run, force))
    out["source"] = "FRED " + sid
    return out


def downsample(rows, step):
    """长序列每隔 step 行取一条（末行必留），避免响应体过大——分位数等统计仍足够密。"""
    if step <= 1 or len(rows) <= step:
        return rows
    out = rows[::step]
    if out[-1] is not rows[-1]:
        out.append(rows[-1])
    return out


def yahoo_bars(symbol, tag="yahoo", days_range="2y"):
    """Yahoo chart API 日线收盘（crash 与 allocation 共用；调用方负责 gov_lock 与缓存）。
    返回 {"ok", "rows":[{d,v}], "latest"}；失败返回 {"ok": false, "error"}。"""
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/%s?range=%s&interval=1d"
           % (symbol.replace("^", "%5E"), days_range))
    try:
        # Yahoo 对非浏览器签名直接 429（实测 curl 带 Chrome UA 即 200），必须走浏览器头
        j = remote(url, as_json=True, tag=tag + ":" + symbol, browser_ua=True,
                   headers={"referer": "https://finance.yahoo.com/"})
        res = j["chart"]["result"][0]
        ts = res.get("timestamp") or []
        closes = res["indicators"]["quote"][0].get("close") or []
    except Exception as e:
        return {"ok": False, "error": "Yahoo 行情失败: " + one_line(e)[:120]}
    rows = []
    for t, c in zip(ts, closes):
        if c is None:
            continue
        rows.append({"d": datetime.fromtimestamp(t).strftime("%Y-%m-%d"), "v": round(c, 2)})
    log.info("[%s] %s 收盘 %d 根（%s → %s）", tag, symbol, len(rows),
             rows[0]["d"] if rows else "—", rows[-1]["d"] if rows else "—")
    return {"ok": bool(rows), "rows": rows, "latest": rows[-1] if rows else None,
            "source": "Yahoo chart " + symbol}


def sma(rows, k):
    """末 k 根收盘均值；不足 k 根返回 None（宁缺毋假）。"""
    if len(rows) < k:
        return None
    return round(sum(r["v"] for r in rows[-k:]) / k, 2)


# ---------------------------------------------------------------- 路由与静态

_MODULES = {}           # name -> {"routes": {sub: fn}, "warm": fn|None}
_BOOT_TS = time.time()  # core 被 import 的时刻 ≈ 本进程启动时刻，用来判断「盘上的 .py 比内存里的新」


def register(name, routes, warm=None):
    """子模块接入：路由挂在 /api/<name>/<sub>；warm 为可选的启动预热函数。"""
    _MODULES[name] = {"routes": routes, "warm": warm}


def _code_stamp():
    """(最近一次 .py 改动时间, 本进程是否在改动之前 import 的) —— Passenger 只在**首个请求**时
    import 代码，之后静态 HTML 每次现读磁盘、Python 却一直在内存里，于是「HTML 是新的、路由是旧的」
    这种半新半旧的状态是常态，只能这样自证：stale=true 就是要 touch tmp/restart.txt。"""
    newest = 0.0
    here = os.path.dirname(os.path.abspath(__file__))
    for name in os.listdir(here):
        if name.endswith(".py"):
            try:
                newest = max(newest, os.path.getmtime(os.path.join(here, name)))
            except OSError:
                pass
    return datetime.fromtimestamp(newest).astimezone().isoformat(timespec="seconds") if newest else "—", newest > _BOOT_TS


def _rss_mb():
    """本进程峰值内存（MB）：一个进程的量，不是账户总额，也不是整机 —— 首页那行 RAM 的标签就是这么写的。
    Unix 走 `resource`（Linux 的 ru_maxrss 单位是 KB，FreeBSD/macOS 是字节）；Windows 没有这个模块，
    改问 kernel32 的 PeakWorkingSetSize（工作集就是 Windows 侧的 RSS）。取不到一律回 None，让页面显示「—」。"""
    try:
        import resource
    except ImportError:
        return _rss_mb_windows()
    v = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if not v or v < 0:
        return None
    return round(v / 1024.0, 1) if sys.platform.startswith("linux") else round(v / 1024.0 / 1024.0, 1)


def _rss_mb_windows():
    try:
        import ctypes
        import ctypes.wintypes as wt

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

        buf = PMC()
        buf.cb = ctypes.sizeof(buf)
        # GetProcessMemoryInfo 在 psapi.dll；kernel32 上导出的那份叫 K32GetProcessMemoryInfo。
        k32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
        fn = getattr(k32, "K32GetProcessMemoryInfo", None) or getattr(psapi, "GetProcessMemoryInfo", None)
        if fn is None:
            return None
        fn.argtypes = [wt.HANDLE, ctypes.POINTER(PMC), wt.DWORD]
        fn.restype = wt.BOOL
        if not fn(k32.GetCurrentProcess(), ctypes.byref(buf), buf.cb):
            return None
        return round(buf.PeakWorkingSetSize / 1024.0 / 1024.0, 1) or None
    except Exception:
        return None


def health_all():
    code_mtime, stale = _code_stamp()
    return {"ok": True, "mode": "public" if PUBLIC else "local",
            "runtime": "python %s" % sys.version.split()[0],
            "proxy": PROXY or "(未配置)", "config": CONFIG, "config_loaded": HAS_CONFIG,
            "show_fix": SHOW_FIX, "log_dir": LOG_DIR,
            "modules": sorted(_MODULES),
            "routes": {m: sorted(_MODULES[m]["routes"]) for m in _MODULES},
            "pid": os.getpid(), "booted": datetime.fromtimestamp(_BOOT_TS).astimezone().isoformat(timespec="seconds"),
            "rss_mb": _rss_mb(), "platform": sys.platform,
            "code_mtime": code_mtime, "stale": stale,
            "time": datetime.now().astimezone().isoformat(timespec="seconds")}


def _js(status, obj):
    """把路由返回值编码成 (status, bytes, ctype)，dict/list 走 json。"""
    if isinstance(obj, (dict, list)):
        obj = json.dumps(obj, ensure_ascii=False)
    if isinstance(obj, str):
        obj = obj.encode("utf-8")
    return status, obj, JSON_CT


def _static(p):
    rel = os.path.normpath(p.lstrip("/") or "Index.html")
    if rel.startswith("..") or os.path.isabs(rel):
        log.warning("[http] 拒绝越界路径 %r", p[:120])
        return 400, b"bad path", "text/plain; charset=utf-8"
    ext = os.path.splitext(rel)[1].lower()
    if PUBLIC and ext not in STATIC_ALLOW:
        log.warning("[public] 拒绝静态文件 %s", rel[:120])
        return 404, b"not found", "text/plain; charset=utf-8"
    with open(os.path.join(ROOT, rel), "rb") as fh:
        body = fh.read()
    if ext == ".html":
        body = body.replace(b"{{SHOW_FIX}}", SHOW_FIX.encode())
    return 200, body, MIME.get(ext, "application/octet-stream")


def _route(p, q):
    if p == "/api/health":
        return _js(200, health_all())
    m = re.match(r"^/api/([a-z]+)/(.+)$", p)
    if m:
        mod = _MODULES.get(m.group(1))
        fn = mod and mod["routes"].get(m.group(2))
        if not fn:
            return _js(404, {"ok": False, "error": "未知接口 " + p})
        q["force"] = ["1"] if q.get("force") == ["1"] else ["0"]
        return _js(*fn(q))
    if p.startswith("/api/"):
        return _js(404, {"ok": False, "error": "未知接口 " + p})
    return _static(p)


def dispatch(raw_path):
    """HTTP 层与 WSGI 层共用的唯一路由入口：'/' 或带查询串的路径 → (status, body:bytes, ctype)。
    任何异常都在此收口：接口回 502，静态回 404，绝不把 traceback 漏给客户端。"""
    t0 = time.perf_counter()
    u = urlparse(raw_path)
    p = unquote(u.path)
    try:
        status, body, ctype = _route(p, parse_qs(u.query))
    except FileNotFoundError:
        status, body, ctype = 404, b"not found", "text/plain; charset=utf-8"
    except Exception as e:
        log.exception("[http] 处理 %s 时异常: %s", raw_path[:160], one_line(e)[:160])
        if p.startswith("/api/"):
            status, body, ctype = _js(502, {"ok": False, "error": str(e)[:160]})
        else:
            status, body, ctype = 404, b"not found", "text/plain; charset=utf-8"
    log.info("[http] %s -> %d %dB %dms", raw_path[:200], status, len(body), _ms(t0))
    return status, body, ctype


def wsgi_app(environ, start_response):
    """Passenger（serv00 的 python 站点类型）等 WSGI 服务器入口；只读 GET/HEAD，其余 405。"""
    method = (environ.get("REQUEST_METHOD") or "GET").upper()
    if method not in ("GET", "HEAD"):
        body = json.dumps({"ok": False, "error": "只支持 GET"}).encode()
        start_response("405 Method Not Allowed",
                       [("content-type", JSON_CT), ("content-length", str(len(body))),
                        ("allow", "GET, HEAD")])
        return [body]
    raw = (environ.get("SCRIPT_NAME") or "") + (environ.get("PATH_INFO") or "/")
    qs = environ.get("QUERY_STRING") or ""
    status, body, ctype = dispatch(raw + ("?" + qs if qs else ""))
    headers = [("content-type", ctype), ("content-length", str(len(body))),
               ("cache-control", "no-store"), ("access-control-allow-origin", "*")]
    start_response("%d %s" % (status, HTTPStatus(status).phrase), headers)
    return [] if method == "HEAD" else [body]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        pass

    def _send(self, code, body, ctype=JSON_CT):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
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
        self._send(*dispatch(self.path))


def serve(open_home=False):
    setup_logging()
    ThreadingHTTPServer.daemon_threads = True
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = "http://127.0.0.1:%d/Index.html" % PORT
    print("数字资产指标看板服务已启动 %s  代理=%s" % (url, PROXY or "(未配置，见 config.ini 或 HTTPS_PROXY)"))
    print("日志：%s" % os.path.join(LOG_DIR, LOG_NAME))
    print("配置：%s%s" % (CONFIG, "" if HAS_CONFIG else "（未找到，使用内置默认值）"))
    sys.stdout.flush()
    log.info("服务监听 127.0.0.1:%d  代理=%s  配置=%s(%s)  模块=%s  修订记录=%s",
             PORT, PROXY or "(未配置)", CONFIG, "已加载" if HAS_CONFIG else "未找到",
             ",".join(sorted(_MODULES)), "展示" if SHOW_FIX == "1" else "隐藏")
    for name, mod in _MODULES.items():
        if mod["warm"]:
            def run_warm(n=name, fn=mod["warm"]):
                t0 = time.perf_counter()
                try:
                    fn()
                    log.info("[warm] %s 预热完成 用时 %dms", n, _ms(t0))
                except Exception as e:
                    log.warning("[warm] %s 预热失败 用时 %dms: %s", n, _ms(t0), one_line(e))
            threading.Thread(target=run_warm, daemon=True).start()
    if open_home or "--open" in sys.argv or os.environ.get("OPEN_PANEL"):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log.info("===== 收到 Ctrl+C，服务退出 =====")
        raise
