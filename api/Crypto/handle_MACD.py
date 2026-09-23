# -*- coding: utf-8 -*-
"""
获取 BTC/USDT 日、周、月级别的 MACD 值。
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

# MACD 参数：快线周期、慢线周期、信号线周期
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# 至少需要的 K 线根数（慢线 EMA26 + 信号 EMA9 需要一定预热）
MIN_KLINES = MACD_SLOW + MACD_SIGNAL + 10


def _get_proxies() -> Optional[dict]:
    try:
        from utils.operationConfig import OperationConfig
        return OperationConfig().get_proxy_config()
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


def ema(close: List[float], period: int) -> List[float]:
    """计算收盘价的 EMA。前 period-1 个为 None 占位，之后为有效值。"""
    n = len(close)
    out: List[float] = []
    k = 2.0 / (period + 1)
    for i in range(n):
        if i < period - 1:
            out.append(close[i])  # 预热用 SMA
            continue
        if i == period - 1:
            s = sum(close[:period]) / period
            out.append(s)
            continue
        prev = out[-1]
        out.append(close[i] * k + prev * (1 - k))
    # 前 period-1 个改为用第一个有效 EMA 填充，避免索引错位；这里直接保持，计算 MACD 时从足够下标开始
    return out


def macd_series(
    close: List[float],
    fast: int = MACD_FAST,
    slow: int = MACD_SLOW,
    signal: int = MACD_SIGNAL,
) -> Tuple[List[float], List[float], List[float]]:
    """
    计算 MACD 线、信号线、柱状图序列。
    返回 (macd_line, signal_line, histogram)，长度与 close 相同；前段为 NaN 占位。
    """
    n = len(close)
    if n < slow + signal:
        return [float("nan")] * n, [float("nan")] * n, [float("nan")] * n

    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    macd_line = [ema_fast[i] - ema_slow[i] for i in range(n)]

    # 信号线：对 MACD 线做 EMA(signal)，仅对有效 MACD 部分计算
    macd_valid = macd_line[slow - 1 :]
    if len(macd_valid) < signal:
        signal_line = [float("nan")] * n
        histogram = [float("nan")] * n
        return macd_line, signal_line, histogram
    signal_ema = ema(macd_valid, signal)
    signal_line = [float("nan")] * (slow - 1) + signal_ema
    # 柱状图 = MACD - 信号线（nan 判断用 v != v）
    histogram = []
    for i in range(n):
        sl = signal_line[i] if i < len(signal_line) else float("nan")
        ml = macd_line[i]
        if sl == sl and ml == ml:
            histogram.append(ml - sl)
        else:
            histogram.append(float("nan"))
    return macd_line, signal_line, histogram


def klines_to_close(klines: List[List]) -> List[float]:
    """Binance K 线 [openTime, open, high, low, close, ...] -> 收盘价列表。"""
    return [float(k[4]) for k in klines]


def get_macd_last_two(
    symbol: str = "BTCUSDT",
    interval: str = "1d",
    limit: int = 500,
    use_closed_bar_only: bool = False,
) -> Optional[Tuple[float, float, float, float, int]]:
    """
    获取最近两根（或仅已收盘两根）有效 K 线的 MACD 与 Signal 值，用于判断金叉/死叉。
    返回 (prev_macd, prev_signal, curr_macd, curr_signal, curr_bar_open_ts_ms)，不足则返回 None。
    use_closed_bar_only=True 时用倒数第2、3 根有效（均为已收盘），减少未收盘 K 线抖动。
    """
    klines = fetch_klines(symbol=symbol, interval=interval, limit=limit)
    if len(klines) < MIN_KLINES:
        return None
    close = klines_to_close(klines)
    macd_line, signal_line, _ = macd_series(close)
    need = 3 if use_closed_bar_only else 2
    valid_items: List[Tuple[int, float, float]] = []  # (idx, macd, signal)
    for i in range(len(macd_line) - 1, -1, -1):
        m, s = macd_line[i], signal_line[i]
        if m == m and s == s:
            valid_items.append((i, m, s))
            if len(valid_items) >= need:
                break
    if len(valid_items) < need:
        return None
    if use_closed_bar_only:
        prev_macd, prev_signal = valid_items[2][1], valid_items[2][2]
        curr_macd, curr_signal = valid_items[1][1], valid_items[1][2]
        curr_idx = valid_items[1][0]
    else:
        curr_idx, curr_macd, curr_signal = valid_items[0][0], valid_items[0][1], valid_items[0][2]
        prev_macd, prev_signal = valid_items[1][1], valid_items[1][2]
    curr_bar_open_ts_ms = int(klines[curr_idx][0])
    return (prev_macd, prev_signal, curr_macd, curr_signal, curr_bar_open_ts_ms)


def get_macd_for_interval(
    symbol: str = "BTCUSDT",
    interval: str = "1d",
    limit: int = 500,
) -> Dict[str, Any]:
    """
    获取指定周期的 MACD。返回包含最新一根的 MACD/信号/柱状图及时间。
    """
    klines = fetch_klines(symbol=symbol, interval=interval, limit=limit)
    if len(klines) < MIN_KLINES:
        return {
            "interval": interval,
            "error": "K线数据不足",
            "bars": len(klines),
            "macd": None,
            "signal": None,
            "histogram": None,
            "time_open_ts": None,
            "time_open_iso": None,
        }
    close = klines_to_close(klines)
    macd_line, signal_line, hist = macd_series(close)
    # 最新一根（最后一条）
    i = len(klines) - 1
    ts_ms = int(klines[i][0])
    time_iso = datetime.utcfromtimestamp(ts_ms / 1000.0).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _last_valid(arr: List[float]):
        for j in range(len(arr) - 1, -1, -1):
            v = arr[j]
            if v == v:  # 非 nan（Python 中 nan != nan）
                return round(v, 8)
        return None

    return {
        "interval": interval,
        "bars": len(klines),
        "macd": _last_valid(macd_line),
        "signal": _last_valid(signal_line),
        "histogram": _last_valid(hist),
        "time_open_ts": ts_ms,
        "time_open_iso": time_iso,
        "params": {"fast": MACD_FAST, "slow": MACD_SLOW, "signal": MACD_SIGNAL},
    }


def get_macd_daily(symbol: str = "BTCUSDT", limit: int = 500) -> Dict[str, Any]:
    """日线 MACD。"""
    return get_macd_for_interval(symbol=symbol, interval=INTERVAL_DAY, limit=limit)


def get_macd_weekly(symbol: str = "BTCUSDT", limit: int = 500) -> Dict[str, Any]:
    """周线 MACD。"""
    return get_macd_for_interval(symbol=symbol, interval=INTERVAL_WEEK, limit=limit)


def get_macd_monthly(symbol: str = "BTCUSDT", limit: int = 500) -> Dict[str, Any]:
    """月线 MACD。"""
    return get_macd_for_interval(symbol=symbol, interval=INTERVAL_MONTH, limit=limit)


def get_macd_all_timeframes(
    symbol: str = "BTCUSDT",
    limit: int = 500,
) -> Dict[str, Any]:
    """
    一次性获取日、周、月三个周期的 MACD 最新值。
    """
    return {
        "symbol": symbol,
        "fetch_time": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "daily": get_macd_daily(symbol=symbol, limit=limit),
        "weekly": get_macd_weekly(symbol=symbol, limit=limit),
        "monthly": get_macd_monthly(symbol=symbol, limit=limit),
    }


def main():
    import json
    result = get_macd_all_timeframes()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    main()
