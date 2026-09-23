# -*- coding: utf-8 -*-
"""全球优质资产配置（GlobalQualityAssetAllocation 子页面）取数模块 —— 贪婪恐慌深度版

展示结构参考 onebitking.com 的「全球优质资产配置 · 9 个全球市场的贪婪恐慌深度」；
恐慌深度/贪婪深度的算法**不复刻**对方私有口径，由页面代码按公开规则实时生成
（见 staic/GlobalQualityAssetAllocation.html 的「判级规则」区）。本模块只回原始序列。

路由：
  /api/allocation/health
  /api/allocation/asset?sym=<白名单符号>   10 年日线收盘 + SMA50/200 + 20 日动量
  /api/allocation/btc[?force=1]            同 /api/liquidity/btc 契约（共享缓存）—— BTC 实时现价
  /api/allocation/macro                    DGS3 / DGS10 十年序列（利率历史分位面板）
  /api/allocation/report?kind=crypto|us    持仓报告：运行 cryptoTrader 对应的报表脚本并回传 stdout。
                                           crypto 按 [report] daily_limit（默认 3 次/天）、us 按 us_daily_limit
                                           （默认 2 次/天）各自限次，超限 429；两者都不设访问凭据，
                                           本机版与公网版同一口径（2026-09-22 用户定）。

白名单 = 参考页 9 标的 + TLT（独立观察标的，不进全球温度）。
BTC 历史画像用 Yahoo BTC-USD 日线；实时现价走 ccxt 多所中位（委托 liquidity 模块，与流动性页共享缓存）。
"""
import json
import os
import subprocess
import threading
import time
from datetime import date

from core import (ROOT, cached, downsample, fred_series, gov_lock, log, sma,
                  yahoo_bars)
import liquidity
import db

ASSET_TTL = 600
ASSETS = {          # 白名单：Yahoo 符号 -> 中文名（日志用）。绝不允许任意 URL / 任意符号转发。
    "GC=F":        "黄金期货",
    "^NSEI":       "印度Nifty50",
    "^STOXX50E":   "欧洲斯托克50",
    "^N225":       "日经225",
    "^HSI":        "恒生指数",
    "^GSPC":       "标普500",
    "000001.SS":   "上证指数",
    "BTC-USD":     "比特币",
    "^NDX":        "纳斯达克100",
    "TLT":         "TLT 20Y+美债ETF",
}
MACRO_SERIES = {    # key -> (缓存键, FRED 序列, TTL 秒, 回溯天数)；十年窗口供利率历史分位用
    "dtb3":  ("alloc:fred:dgs3",  "DGS3",  3600, 3650),
    "dgs10": ("alloc:fred:dgs10", "DGS10", 3600, 3650),
}


def _force(q):
    return q.get("force") == ["1"]


def _chg(rows, k):
    """末行相对倒数第 k+1 行的变化（%）与差值；数据不足返回 None。"""
    if len(rows) < k + 1:
        return None, None
    a, b = rows[-1]["v"], rows[-k - 1]["v"]
    return round(a - b, 4), round((a / b - 1) * 100, 2) if b else None


def asset(sym, force):
    def run():
        with gov_lock:
            out = yahoo_bars(sym, tag="alloc", days_range="10y")
        if not out.get("ok"):
            return out
        rows = out["rows"]
        diff, pct = _chg(rows, 20)
        m200 = sma(rows, 200)
        m200_prev = sma(rows[:-20], 200) if len(rows) >= 220 else None
        out.update(sym=sym, name=ASSETS[sym], sma200=m200, sma50=sma(rows, 50),
                   chg20_diff=diff, chg20_pct=pct,
                   ma200_rising=(None if m200 is None or m200_prev is None
                                 else m200 > m200_prev))
        log.info("[alloc] %s(%s) 收盘 %s @ %s，共 %d 根（10y）",
                 sym, ASSETS[sym], rows[-1]["v"], rows[-1]["d"], len(rows))
        return out

    return cached("alloc10:" + sym, ASSET_TTL, run, force)


def macro(force):
    out = {"ok": True, "sources": {}}
    good = 0
    for key, (ckey, sid, ttl, days) in MACRO_SERIES.items():
        d = fred_series(ckey, sid, ttl, force, days=days, tag="fred:alloc")
        rows = d.get("rows") or []
        diff, pct = _chg(rows, 63)        # 约一个季度
        out[key] = {"latest": rows[-1] if rows else None,
                    "chg_q": diff, "chg_q_pct": pct,
                    "history": downsample(rows, 5)}
        out["sources"][key] = d.get("source") or d.get("error") or ""
        if rows:
            good += 1
    out["ok"] = good > 0
    log.info("[alloc] 利率序列 %d/%d 可达：%s", good, len(MACRO_SERIES),
             " ".join("%s=%s" % (k, (out[k]["latest"] or {}).get("v"))
                      for k in MACRO_SERIES if out[k]["latest"]))
    return out


# ---------------------------------------------------------------- 路由

def r_health(q):
    d = {"ok": True, "module": "allocation", "assets": list(ASSETS),
         "macro": sorted(MACRO_SERIES)}
    d["report_quota"] = _quota()
    return 200, d


def r_asset(q):
    sym = (q.get("sym") or [""])[0]
    if sym not in ASSETS:
        log.warning("[alloc] 拒绝白名单外的符号 sym=%r", sym[:40])
        return 400, {"ok": False, "error": "未知资产符号，允许: " + ",".join(ASSETS)}
    d = asset(sym, _force(q))
    return (200 if d.get("ok") else 502), d


def r_btc(q):
    d = liquidity.btc(_force(q))       # 共享 "btc" 缓存键与启动预热结果
    return (200 if d.get("ok") else 502), d


def r_macro(q):
    d = macro(_force(q))
    return (200 if d.get("ok") else 502), d


# 持仓报告 = 运行 cryptoTrader 的报表脚本，脚本 stdout 即报表正文（两个 kind 同一套流程）。
# 解释器/脚本按 OS 选，config.ini [report] 可覆盖；环境（含 HTTPS_PROXY）原样继承给子进程，
# 脚本自己的代理开关在 cryptoTrader/config/config.ini 的 [proxy] 段。
# ⚠ 两个脚本都是**无参数运行即推送 Telegram**（`--DD` 才是只发钉钉），所以点一次 = 发一条。
REPORT = {          # kind -> 默认脚本（下标 0 = Windows，1 = Linux/FreeBSD；Windows 用正斜杠即可，os.path 与 subprocess 都认）/ 上限键
    "crypto": {
        "name": "加密持仓",
        "script": ("./runningOrder.py",
                   "./runningOrder.py"),
        "script_env": "REPORT_CRYPTO_SCRIPT", "limit_env": "REPORT_DAILY_LIMIT", "limit": 3,
    },
    "us": {
        "name": "美股持仓",
        "script": ("./runningStorcksOrder.py",
                   "./runningStorcksOrder.py"),
        "script_env": "REPORT_US_SCRIPT", "limit_env": "REPORT_US_DAILY_LIMIT", "limit": 2,
    },
}
REPORT_TIMEOUT = 180          # 脚本要读单 + 拉价 + 发 TG，给足超时
_report_lock = threading.Lock()  # 同一时刻只允许一个报表进程，防连点重复发 TG

# 每天每个 kind 各点几次：脚本一次运行就是一条 Telegram 推送，靠人自觉点不动手不行，所以落盘计数。
# 记在文件而不是内存里，是为了让服务重启（改代码、开机自启、start_app.bat）不重置当日额度。
QUOTA_FILE = os.path.join(ROOT, "data", "report_quota.json")


def _limit(kind):
    try:
        return max(0, int(os.environ.get(REPORT[kind]["limit_env"]) or REPORT[kind]["limit"]))
    except ValueError:
        return REPORT[kind]["limit"]


def _quota():
    """→ {date, kinds: {crypto: {used, limit, left}, us: {...}}}；文件缺失/损坏/跨天都按「今天还没点过」处理。"""
    today = date.today().isoformat()
    used = dict.fromkeys(REPORT, 0)
    try:
        with open(QUOTA_FILE, encoding="utf-8") as f:
            j = json.load(f)
        if j.get("date") == today:
            k = j.get("kinds")
            if k is None:                 # 旧格式只有一个 used 字段，那记的就是加密报告的次数
                k = {"crypto": j.get("used") or 0}
            for kind in used:
                used[kind] = max(0, int(k.get(kind) or 0))
    except (OSError, ValueError, TypeError):
        pass
    kinds = {}
    for kind in REPORT:
        lim = _limit(kind)
        kinds[kind] = {"used": used[kind], "limit": lim, "left": max(0, lim - used[kind])}
    return {"date": today, "kinds": kinds}


def _quota_consume(kind):
    q = _quota()
    os.makedirs(os.path.dirname(QUOTA_FILE), exist_ok=True)
    tmp = QUOTA_FILE + ".tmp"
    counts = {k: v["used"] for k, v in q["kinds"].items()}
    counts[kind] += 1
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"date": q["date"], "kinds": counts}, f, ensure_ascii=False)
    os.replace(tmp, QUOTA_FILE)          # 原子替换，避免半截文件
    log.info("[report] %s 今日额度 %d/%d 已用（%s）", kind, counts[kind], q["kinds"][kind]["limit"], q["date"])


def run_report(kind):
    cfg = REPORT[kind]
    if os.name == "nt":
        py, script = "python", cfg["script"][0]
    else:
        py, script = "/home/myaibtc/vevns/web3/bin/python", cfg["script"][1]
    # 环境 > config.ini（其中 [report] python 只在 Windows 读，见 core.apply_config）> 代码默认
    py = os.environ.get("REPORT_PY") or py
    script = os.environ.get(cfg["script_env"]) or script
    if not os.path.isfile(script):
        return False, {"error": "脚本不存在：%s" % script}
    if not _report_lock.acquire(blocking=False):
        return False, {"error": "已有报表进程在跑，请等待上一次完成", "busy": True}
    _quota_consume(kind)      # 占用成功即计一次：脚本一跑就是一条 TG，失败的那次也一样发
    try:
        log.info("[report] 运行%s报表 %s %s", cfg["name"], py, script)
        t0 = time.time()
        r = subprocess.run([py, script], capture_output=True, text=True,
                           encoding="utf-8", errors="replace",      # 服务器 locale 常是 C/POSIX，
                           env=dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8"),  # 不强制则子进程按本机代码页(GBK)吐，UTF-8 解出来全是乱码
                           timeout=REPORT_TIMEOUT, cwd=os.path.dirname(script))   # 不写死就会按 ASCII 解中文 stdout 崩掉
        sec = round(time.time() - t0, 1)
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        if r.returncode != 0:
            return False, {"error": "脚本退出码 %d：%s" % (r.returncode, (err or out)[-500:] or "无输出"),
                           "stdout": out, "sec": sec}
        log.info("[report] %s报表完成 %d 字符 / %.1fs", cfg["name"], len(out), sec)
        return True, {"stdout": out, "sec": sec, "stderr": err[-500:] if err else ""}
    except subprocess.TimeoutExpired:
        return False, {"error": "脚本超时（>%ds）未返回" % REPORT_TIMEOUT}
    except FileNotFoundError:
        return False, {"error": "找不到解释器 %s（服务器上换 venv 用环境变量 REPORT_PY 指绝对路径）" % py}
    except Exception as e:
        return False, {"error": "运行失败：%s" % e}
    finally:
        _report_lock.release()


def r_report(q):
    """持仓报告：运行 cryptoTrader 对应的报表脚本，每个 kind 各自限每日次数
    （[report] daily_limit / us_daily_limit）。本机版与公网版同一口径、不设访问凭据。"""
    kind = (q.get("kind") or [""])[0]
    if kind not in REPORT:
        return 400, {"ok": False, "error": "kind 仅支持 " + "|".join(REPORT)}
    q = _quota()
    kq = q["kinds"][kind]
    if kq["left"] <= 0:
        log.info("[report] 拒绝 %s：%s 已点满 %d 次", kind, q["date"], kq["used"])
        return 429, {"ok": False, "kind": kind, "quota": q,
                     "error": "今天已发送 %d 次了，明天再来" % kq["limit"]}
    ok, d = run_report(kind)
    # 留痕一行：只记元数据（kind / 成败 / 耗时 / 字符数 / 当天第几次），**报表正文不落库**——
    # 正文里是持仓明细与金额，而这套库与账号是共享环境。store_report 内部吞异常，不影响这次返回。
    db.store_report(kind, ok, sec=d.get("sec") or 0, chars=len(d.get("stdout") or ""),
                    quota_used=(q["kinds"][kind]["limit"] - _quota()["kinds"][kind]["left"]),
                    err=d.get("error") or "")
    return (200 if ok else 502), {"ok": ok, "kind": kind, "quota": _quota(), **d}


ROUTES = {"health": r_health, "asset": r_asset, "btc": r_btc, "macro": r_macro,
          "report": r_report}
