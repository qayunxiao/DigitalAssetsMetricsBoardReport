# -*- coding: utf-8 -*-
"""
获取指定周期的 EMA 均线，用于金叉/死叉判断（如 EMA5 上穿 EMA10 为金叉，下穿为死叉）。
数据来源：Binance 公开 API。支持 config.ini [proxy] 配置代理。
"""
from __future__ import annotations

import os
import sys
from typing import List, Optional, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import requests

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
REQUEST_TIMEOUT = 30
HEADERS = {"User-Agent": "Mozilla/5.0"}

# 默认快线/慢线周期（可被 config EMA_FAST / EMA_SLOW 覆盖）
DEFAULT_FAST = 5
DEFAULT_SLOW = 10


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
    """从 Binance 拉取 K 线。返回 [[openTime, open, high, low, close, volume, ...], ...]。"""
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    if end_time_ms is not None:
        params["endTime"] = end_time_ms
    r = requests.get(
        BINANCE_KLINES_URL,
        params=params,
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT,
        proxies=_get_proxies() or None,
    )
    if not r.ok:
        return []
    data = r.json()
    return data if isinstance(data, list) else []


def ema(close: List[float], period: int) -> List[float]:
    """收盘价的 EMA，前 period-1 个用 SMA 预热。"""
    n = len(close)
    out: List[float] = []
    k = 2.0 / (period + 1)
    for i in range(n):
        if i < period - 1:
            out.append(close[i])
            continue
        if i == period - 1:
            out.append(sum(close[:period]) / period)
            continue
        out.append(close[i] * k + out[-1] * (1 - k))
    return out


def klines_to_close(klines: List[List]) -> List[float]:
    """Binance K 线 -> 收盘价列表。"""
    return [float(k[4]) for k in klines]


def get_ema_last_two(
    symbol: str = "BTCUSDT",
    interval: str = "1d",
    limit: int = 500,
    fast: int = DEFAULT_FAST,
    slow: int = DEFAULT_SLOW,
    use_closed_bar_only: bool = False,
) -> Optional[Tuple[float, float, float, float, int]]:
    """
    获取最近两根（或仅已收盘两根）K 线的快线/慢线 EMA 值，用于金叉/死叉。
    返回 (prev_fast, prev_slow, curr_fast, curr_slow, curr_bar_open_ts_ms)，不足则 None。
    金叉：prev_fast <= prev_slow 且 curr_fast > curr_slow；死叉：prev_fast >= prev_slow 且 curr_fast < curr_slow。
    """
    if fast >= slow:
        fast, slow = slow, fast
    need_bars = slow + 5
    klines = fetch_klines(symbol=symbol, interval=interval, limit=limit)
    if len(klines) < need_bars:
        return None
    close = klines_to_close(klines)
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    # 有效起点为 slow-1（ema_slow 从该下标开始有效）
    need = 3 if use_closed_bar_only else 2
    valid_items: List[Tuple[int, float, float]] = []
    for i in range(len(close) - 1, slow - 2, -1):
        if i < 0:
            break
        f, s = ema_fast[i], ema_slow[i]
        valid_items.append((i, f, s))
        if len(valid_items) >= need:
            break
    if len(valid_items) < need:
        return None
    if use_closed_bar_only:
        prev_fast, prev_slow = valid_items[2][1], valid_items[2][2]
        curr_fast, curr_slow = valid_items[1][1], valid_items[1][2]
        curr_idx = valid_items[1][0]
    else:
        curr_idx, curr_fast, curr_slow = valid_items[0][0], valid_items[0][1], valid_items[0][2]
        prev_fast, prev_slow = valid_items[1][1], valid_items[1][2]
    curr_bar_open_ts_ms = int(klines[curr_idx][0])
    return (prev_fast, prev_slow, curr_fast, curr_slow, curr_bar_open_ts_ms)


if __name__ == "__main__":
    r = get_ema_last_two(symbol="BTCUSDT", interval="1d", fast=5, slow=10)
    print("EMA last two (5/10):", r)
