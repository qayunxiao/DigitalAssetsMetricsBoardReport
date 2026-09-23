# -*- coding: utf-8 -*-
"""
获取 BTC/USDT 日、周、月级别的 KDJ 值。
数据来源：Binance 公开 API（无需 key）。支持通过 config.ini [proxy] 配置代理。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import requests

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
REQUEST_TIMEOUT = 30
HEADERS = {"User-Agent": "Mozilla/5.0"}

# Binance 周期: 1d=日, 1w=周, 1M=月
INTERVAL_DAY = "1d"
INTERVAL_WEEK = "1w"
INTERVAL_MONTH = "1M"

# KDJ 参数：RSV 周期、K 平滑、D 平滑
KDJ_N = 9
KDJ_M1 = 3
KDJ_M2 = 3

# 至少需要的 K 线根数（RSV 用 n 根，K/D 再平滑）
MIN_KLINES = KDJ_N + KDJ_M1 + KDJ_M2 + 5


def _get_proxies() -> Optional[dict]:
    """从 config.ini [proxy] 读取代理；仅 Windows 使用代理，FreeBSD/Linux 等直连。"""
    if sys.platform != "win32":
        return None
    try:
        import configparser
        path = os.path.join(_ROOT, "config", "config.ini")
        cfg = configparser.ConfigParser()
        cfg.read(path, encoding="utf-8-sig")
        if not cfg.has_section("proxy"):
            return None
        if cfg.get("proxy", "ENABLED", fallback="0").strip().lower() not in ("1", "true", "yes"):
            return None
        host = cfg.get("proxy", "HOST", fallback="127.0.0.1").strip()
        port_http = cfg.get("proxy", "PORT_HTTP", fallback="7897").strip()
        port_https = cfg.get("proxy", "PORT_HTTPS", fallback="7899").strip()
        return {
            "http": "http://%s:%s" % (host, port_http),
            "https": "http://%s:%s" % (host, port_https),
        }
    except Exception:
        return None


def fetch_klines(
    symbol: str = "BTCUSDT",
    interval: str = "1d",
    limit: int = 500,
    end_time_ms: Optional[int] = None,
) -> List[List]:
    """
    从 Binance 拉取 K 线。返回 [[openTime, open, high, low, close, volume, ...], ...]。
    """
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    if end_time_ms is not None:
        params["endTime"] = end_time_ms
    proxies = _get_proxies()
    r = requests.get(
        BINANCE_KLINES_URL,
        params=params,
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT,
        proxies=proxies or None,
    )
    if not r.ok:
        return []
    data = r.json()
    if not isinstance(data, list):
        return []
    return data


def kdj_series(
    high: List[float],
    low: List[float],
    close: List[float],
    n: int = KDJ_N,
    m1: int = KDJ_M1,
    m2: int = KDJ_M2,
) -> Tuple[List[float], List[float], List[float]]:
    """
    计算 K、D、J 序列。
    RSV = (Close - Low_n) / (High_n - Low_n) * 100；
    K = SMA(RSV, m1) 平滑，D = SMA(K, m2) 平滑，J = 3*K - 2*D。
    返回 (k_line, d_line, j_line)，长度与 close 相同；前段为 nan。
    """
    size = len(close)
    if size < n:
        return [float("nan")] * size, [float("nan")] * size, [float("nan")] * size

    rsv_list: List[float] = []
    for i in range(size):
        if i < n - 1:
            rsv_list.append(float("nan"))
            continue
        h_n = max(high[i - n + 1 : i + 1])
        l_n = min(low[i - n + 1 : i + 1])
        if h_n <= l_n:
            rsv_list.append(50.0)  # 约定：高低相等时 RSV=50
            continue
        rsv = (close[i] - l_n) / (h_n - l_n) * 100.0
        rsv_list.append(rsv)

    def _sma(arr: List[float], period: int) -> List[float]:
        out: List[float] = []
        for i in range(size):
            if i < period - 1 or arr[i] != arr[i]:
                out.append(float("nan"))
                continue
            start = i - period + 1
            valid = [arr[j] for j in range(start, i + 1) if arr[j] == arr[j]]
            if len(valid) < period:
                out.append(float("nan"))
                continue
            out.append(sum(valid) / period)
        return out

    k_line = _sma(rsv_list, m1)
    d_line = _sma(k_line, m2)

    j_line: List[float] = []
    for i in range(size):
        k_val = k_line[i] if i < len(k_line) else float("nan")
        d_val = d_line[i] if i < len(d_line) else float("nan")
        if k_val == k_val and d_val == d_val:
            j_line.append(3.0 * k_val - 2.0 * d_val)
        else:
            j_line.append(float("nan"))

    return k_line, d_line, j_line


def klines_to_ohlc(klines: List[List]) -> Tuple[List[float], List[float], List[float]]:
    """Binance K 线 -> (high, low, close)。"""
    high = [float(k[2]) for k in klines]
    low = [float(k[3]) for k in klines]
    close = [float(k[4]) for k in klines]
    return high, low, close


def get_kdj_for_interval(
    symbol: str = "BTCUSDT",
    interval: str = "1d",
    limit: int = 500,
) -> Dict[str, Any]:
    """获取指定周期的 KDJ 最新值。"""
    klines = fetch_klines(symbol=symbol, interval=interval, limit=limit)
    if len(klines) < MIN_KLINES:
        return {
            "interval": interval,
            "error": "K线数据不足",
            "bars": len(klines),
            "k": None,
            "d": None,
            "j": None,
            "time_open_ts": None,
            "time_open_iso": None,
        }
    high, low, close = klines_to_ohlc(klines)
    k_line, d_line, j_line = kdj_series(high, low, close)

    i = len(klines) - 1
    ts_ms = int(klines[i][0])
    time_iso = datetime.utcfromtimestamp(ts_ms / 1000.0).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _last_valid(arr: List[float]):
        for j in range(len(arr) - 1, -1, -1):
            v = arr[j]
            if v == v:
                return round(v, 4)
        return None

    return {
        "interval": interval,
        "bars": len(klines),
        "k": _last_valid(k_line),
        "d": _last_valid(d_line),
        "j": _last_valid(j_line),
        "time_open_ts": ts_ms,
        "time_open_iso": time_iso,
        "params": {"n": KDJ_N, "m1": KDJ_M1, "m2": KDJ_M2},
    }


def get_kdj_daily(symbol: str = "BTCUSDT", limit: int = 500) -> Dict[str, Any]:
    """日线 KDJ。"""
    return get_kdj_for_interval(symbol=symbol, interval=INTERVAL_DAY, limit=limit)


def get_kdj_weekly(symbol: str = "BTCUSDT", limit: int = 500) -> Dict[str, Any]:
    """周线 KDJ。"""
    return get_kdj_for_interval(symbol=symbol, interval=INTERVAL_WEEK, limit=limit)


def get_kdj_monthly(symbol: str = "BTCUSDT", limit: int = 500) -> Dict[str, Any]:
    """月线 KDJ。"""
    return get_kdj_for_interval(symbol=symbol, interval=INTERVAL_MONTH, limit=limit)


def get_kdj_all_timeframes(
    symbol: str = "BTCUSDT",
    limit: int = 500,
) -> Dict[str, Any]:
    """一次性获取日、周、月三个周期的 KDJ 最新值。"""
    return {
        "symbol": symbol,
        "fetch_time": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "daily": get_kdj_daily(symbol=symbol, limit=limit),
        "weekly": get_kdj_weekly(symbol=symbol, limit=limit),
        "monthly": get_kdj_monthly(symbol=symbol, limit=limit),
    }


def main():
    import json
    result = get_kdj_all_timeframes()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    main()
