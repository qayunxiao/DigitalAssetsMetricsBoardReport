# -*- coding: utf-8 -*-
"""
BTC 日 K 成交量缓存：用于计算 30 天成交均量/365 天成交均量（VOLUME_RATIO_MAX）。
数据缓存到 data/cache/btc_cache.json，每次请求以 7 天 K 线为单位、请求间隔 5～20 秒随机，减少网络请求与负载。
"""
import json
import os
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    from utils.handle_log import log
except Exception:
    log = None


def _ts_to_date(ts_ms: int) -> str:
    """时间戳(毫秒)转日期字符串，便于 log 展示。"""
    try:
        return datetime.utcfromtimestamp(ts_ms / 1000.0).strftime("%Y-%m-%d")
    except Exception:
        return str(ts_ms)

# 项目根目录
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_SCRIPT_DIR))


def _cache_path() -> str:
    return os.path.join(_ROOT, "data", "cache", "btc_cache.json")


def _get_proxies() -> Optional[Dict[str, str]]:
    try:
        from utils.operationConfig import OperationConfig
        return OperationConfig().get_proxy_config()
    except Exception:
        return None


def _load_cache() -> Tuple[List[List], str]:
    """加载缓存。返回 (daily_list, updated_str)。daily_list 元素为 [timestamp_ms, volume]。"""
    path = _cache_path()
    if not os.path.exists(path):
        if log:
            log.info("btc_volume_cache: 缓存文件不存在 path=%s", path)
        return [], ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        daily = data.get("daily") or []
        updated = data.get("updated") or ""
        if not isinstance(daily, list):
            return [], ""
        # 按时间升序
        daily = [x for x in daily if isinstance(x, (list, tuple)) and len(x) >= 2]
        daily.sort(key=lambda x: x[0])
        if log and daily:
            first_ts = daily[0][0]
            last_ts = daily[-1][0]
            log.info("btc_volume_cache: 加载缓存 条数=%s 日期范围 %s ~ %s updated=%s", len(daily), _ts_to_date(first_ts), _ts_to_date(last_ts), updated or "—")
        return daily, updated
    except Exception as e:
        if log:
            log.warning("btc_volume_cache: 加载缓存失败 path=%s err=%s", path, e)
        return [], ""


def _save_cache(daily: List[List], updated: Optional[str] = None) -> None:
    """写入缓存。daily 为 [timestamp_ms, volume] 列表。"""
    path = _cache_path()
    dirname = os.path.dirname(path)
    if dirname and not os.path.isdir(dirname):
        os.makedirs(dirname, exist_ok=True)
    daily = [x for x in daily if isinstance(x, (list, tuple)) and len(x) >= 2]
    daily.sort(key=lambda x: x[0])
    payload = {
        "daily": daily,
        "updated": updated or datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _fetch_ohlcv_chunk(symbol: str, since_ms: int, limit: int = 7) -> List[List]:
    """拉取一批日 K（默认 7 根）。返回 [[time_ms, open, high, low, close, vol], ...]。"""
    try:
        import ccxt
        _proxies = _get_proxies()
        exchange = ccxt.binance({
            "timeout": 15000,
            "enableRateLimit": True,
            **({"proxies": _proxies} if _proxies else {}),
        })
        # fetch_ohlcv 返回 [timestamp, open, high, low, close, volume]
        if log:
            log.info("btc_volume_cache: 请求K线 since=%s 日期=%s limit=%s", since_ms, _ts_to_date(since_ms), limit)
        rows = exchange.fetch_ohlcv(symbol, timeframe="1d", since=since_ms, limit=limit)
        if rows:
            dates = [_ts_to_date(int(r[0])) for r in rows]
            print("btc_volume_cache: 获取K线 条数=%s 日期=%s" % (len(rows), ", ".join(dates)))
            if log:
                log.info("btc_volume_cache: 获取K线 条数=%s 日期=%s", len(rows), ",".join(dates))
        return rows
    except Exception as e:
        if log:
            log.warning("btc_volume_cache: 请求K线失败 since=%s 日期=%s err=%s", since_ms, _ts_to_date(since_ms), e)
        return []


def _ensure_365_days() -> List[List]:
    """
    确保缓存中至少有最近 365 天的日 K（时间戳 + 成交量）。
    根据需要的数据日期先查 btc_cache.json：有缓存的日期不请求接口，只请求缺失日期；新增数据写回缓存。
    返回按时间升序的 [timestamp_ms, volume] 列表（至少 365 条）。
    """
    daily, _ = _load_cache()
    # 用字典记录已有时间戳 -> 成交量（来自缓存）
    by_ts: Dict[int, float] = {}
    for row in daily:
        try:
            ts = int(row[0])
            vol = float(row[5]) if len(row) > 5 else float(row[1])
            by_ts[ts] = vol
        except (IndexError, TypeError, ValueError):
            continue
    # 目标：最近 365 天的 0 点（UTC）为起止，与 Binance/缓存 的日 K 时间戳一致（必须用 UTC 否则本地时区会导致时间戳对不上缓存）
    now_utc = datetime.now(timezone.utc)
    end_day_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
    start_day_utc = end_day_utc - timedelta(days=365)
    start_ms = int(start_day_utc.timestamp() * 1000)
    end_ms = int(end_day_utc.timestamp() * 1000)
    one_day_ms = 24 * 3600 * 1000

    # 所需日期列表（目标区间内每一天 0 点时间戳）
    required_ts_list = []
    t = start_ms
    while t < end_ms:
        required_ts_list.append(t)
        t += one_day_ms
    cached_ts = [ts for ts in required_ts_list if ts in by_ts]
    missing_ts = [ts for ts in required_ts_list if ts not in by_ts]

    # 使用缓存数据日期：输出打印
    if cached_ts:
        cached_dates = [_ts_to_date(ts) for ts in sorted(cached_ts)]
        if len(cached_dates) <= 15:
            print("btc_volume_cache: 使用缓存数据日期 共 %s 天 %s" % (len(cached_dates), ", ".join(cached_dates)))
        else:
            print("btc_volume_cache: 使用缓存数据日期 共 %s 天 %s ... %s" % (len(cached_dates), cached_dates[0], cached_dates[-1]))
        if log:
            log.info("btc_volume_cache: 使用缓存 共 %s 天 范围 %s ~ %s", len(cached_ts), _ts_to_date(min(cached_ts)), _ts_to_date(max(cached_ts)))

    if not missing_ts:
        # 全部命中缓存，无需请求接口
        print("btc_volume_cache: 所需日期均在缓存中，未请求接口")
        if log:
            log.info("btc_volume_cache: 全部使用缓存 未请求接口")
        return [[ts, vol] for ts, vol in sorted(by_ts.items())]

    # 有缺失：仅请求缺失日期对应的 K 线（按 7 天一批，间隔 5～20 秒）
    print("btc_volume_cache: 缺失 %s 天需请求接口 日期范围 %s ~ %s" % (len(missing_ts), _ts_to_date(min(missing_ts)), _ts_to_date(max(missing_ts))))
    if log:
        log.info("btc_volume_cache: 目标日期范围 %s ~ %s 需365天 缺失 %s 天", _ts_to_date(start_ms), _ts_to_date(end_ms), len(missing_ts))
    symbol = "BTC/USDT"
    newly_fetched_ts: List[int] = []
    t = start_ms
    while t < end_ms:
        chunk_end_ms = min(t + 7 * one_day_ms, end_ms)
        missing = [ts for ts in missing_ts if t <= ts < chunk_end_ms]
        if missing:
            if log:
                log.info("btc_volume_cache: 补全缺失 日期 %s ~ %s", _ts_to_date(t), _ts_to_date(chunk_end_ms - one_day_ms))
            rows = _fetch_ohlcv_chunk(symbol, t, limit=7)
            for row in rows:
                if len(row) < 6:
                    continue
                ts = int(row[0])
                if start_ms <= ts < end_ms:
                    by_ts[ts] = float(row[5])
                    newly_fetched_ts.append(ts)
            delay = random.uniform(5, 20)
            if log:
                log.info("btc_volume_cache: 本批完成 等待 %.1f 秒后下一批", delay)
            time.sleep(delay)
        t = chunk_end_ms

    # 新增写入缓存：输出打印
    if newly_fetched_ts:
        new_dates = sorted(set(newly_fetched_ts))
        new_date_strs = [_ts_to_date(ts) for ts in new_dates]
        if len(new_date_strs) <= 15:
            print("btc_volume_cache: 新增写入缓存日期 共 %s 天 %s" % (len(new_date_strs), ", ".join(new_date_strs)))
        else:
            print("btc_volume_cache: 新增写入缓存日期 共 %s 天 %s ... %s" % (len(new_date_strs), new_date_strs[0], new_date_strs[-1]))
        if log:
            log.info("btc_volume_cache: 新增写入缓存 共 %s 天 %s ~ %s", len(new_date_strs), new_date_strs[0], new_date_strs[-1])

    # 写回缓存：所有 [ts, vol] 按 ts 排序
    out = [[ts, vol] for ts, vol in sorted(by_ts.items())]
    if out:
        _save_cache(out)
        if log:
            log.info("btc_volume_cache: 写入缓存 条数=%s 日期范围 %s ~ %s", len(out), _ts_to_date(out[0][0]), _ts_to_date(out[-1][0]))
    return out


def get_btc_volume_ratio() -> Optional[float]:
    """
    计算 BTC 成交量比：30 天成交均量 / 365 天成交均量。
    优先使用 data/cache/btc_cache.json 缓存；不足时按 7 天 K 线请求并写回缓存，请求间隔 5～20 秒。
    返回 None 表示无法计算。
    """
    daily = _ensure_365_days()
    if len(daily) < 365:
        return None
    # 取最后 365 条
    last365 = daily[-365:]
    vols = [float(x[1]) for x in last365]
    avg_365 = sum(vols) / 365.0
    if avg_365 <= 0:
        return None
    avg_30 = sum(vols[-30:]) / 30.0
    return round(avg_30 / avg_365, 4)
