# -*- coding: utf-8 -*-
"""
请求 looknode 两个接口，取最近 200 条数据，分析 mCapRealizedRatio 与 BTCPrice 的对应关系，结果写入 log。
从 2025-10-01 至今按天整理为：每天一条 {"日期": t, "BTC价格": 整数, "MVRV": 1.23}。
- https://www.looknode.com/api/mCapRealizedRatio  (t: 毫秒, v: MVRV 比值)
- https://www.looknode.com/api/BTCPrice?params=%7B%7D  (t: 秒, v: BTC 价格字符串)
"""
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from utils.operationConfig import OperationConfig
from utils.handle_log import log

REQUEST_TIMEOUT = 20
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

URL_MCAP_REALIZED = "https://www.looknode.com/api/mCapRealizedRatio"
URL_BTC_PRICE = "https://www.looknode.com/api/BTCPrice?params=%7B%7D"
RECENT_COUNT = 200
# 只处理 2025-10-01 00:00:00 UTC 至今
START_TS = int(datetime(2025, 10, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp())


def _get_proxies() -> Optional[Dict[str, str]]:
    """从 config.ini [proxy] 读取代理配置（与 handle_mvrv 一致）。"""
    return OperationConfig().get_proxy_config()


def _fetch_json(url: str) -> Optional[Dict[str, Any]]:
    """请求接口，返回 JSON；失败返回 None。"""
    proxies = _get_proxies()
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, proxies=proxies or {})
        if not r.ok:
            return None
        return r.json()
    except Exception:
        return None


def _parse_mvrv_response(raw: Optional[Dict]) -> List[Tuple[int, float]]:
    """
    解析 mCapRealizedRatio：data 为 [{"t": 毫秒, "v": 数值}, ...]。
    t 转为秒、v 转为 float，取最后 RECENT_COUNT 条，且只保留 2025-10-01 至今。
    返回 [(ts_秒, value), ...]。
    """
    if not raw or raw.get("code") != 100:
        return []
    data = raw.get("data")
    if not isinstance(data, list):
        return []
    out = []
    for item in data[-RECENT_COUNT:]:
        if not isinstance(item, dict):
            continue
        t = item.get("t")
        v = item.get("v")
        if t is None or v is None:
            continue
        try:
            ts = int(float(t))
            val = float(v)
            # 若 t 为毫秒（> 1e12 量级），转为秒
            if ts > 1e12:
                ts = ts // 1000
            if ts >= START_TS:
                out.append((ts, val))
        except (TypeError, ValueError):
            continue
    return out


def _parse_btc_price_response(raw: Optional[Dict]) -> List[Tuple[int, float]]:
    """
    解析 BTCPrice：data 为 [{"t": 秒, "v": "价格字符串"}, ...]。
    取最后 RECENT_COUNT 条，只保留 2025-10-01 至今。返回 [(ts_秒, price), ...]。
    """
    if not raw or raw.get("code") != 100:
        return []
    data = raw.get("data")
    if not isinstance(data, list):
        return []
    out = []
    for item in data[-RECENT_COUNT:]:
        if not isinstance(item, dict):
            continue
        t = item.get("t")
        v = item.get("v")
        if t is None or v is None:
            continue
        try:
            ts = int(float(t))
            val = float(v) if isinstance(v, (int, float)) else float(str(v).strip())
            if ts >= START_TS:
                out.append((ts, val))
        except (TypeError, ValueError):
            continue
    return out


def _align_by_time(
    mvrv_list: List[Tuple[int, float]],
    btc_list: List[Tuple[int, float]],
) -> List[Tuple[int, float, float]]:
    """
    按时间戳对齐：以 mvrv 的时间为基准，为每个 mvrv 找 btc 中同一天（86400 秒）内最近的一个点。
    返回 [(ts, mvrv, btc_price), ...]。
    """
    if not mvrv_list or not btc_list:
        return []
    btc_by_ts = {ts: price for ts, price in btc_list}
    btc_ts_sorted = sorted(btc_by_ts.keys())
    out = []
    for ts, mvrv in mvrv_list:
        # 找 btc 中与 ts 最接近的时间（同一天或最近）
        if ts in btc_by_ts:
            out.append((ts, mvrv, btc_by_ts[ts]))
            continue
        idx = _bisect_right(btc_ts_sorted, ts)
        cands = []
        if idx > 0:
            cands.append(btc_ts_sorted[idx - 1])
        if idx < len(btc_ts_sorted):
            cands.append(btc_ts_sorted[idx])
        if not cands:
            continue
        best_ts = min(cands, key=lambda t: abs(t - ts))
        if abs(best_ts - ts) <= 86400 * 2:  # 允许 2 天内对齐
            out.append((ts, mvrv, btc_by_ts[best_ts]))
    return out


def _bisect_right(a: List[int], x: int) -> int:
    """bisect_right 简易实现（避免仅为此引入 bisect 模块）。"""
    lo, hi = 0, len(a)
    while lo < hi:
        mid = (lo + hi) // 2
        if x < a[mid]:
            hi = mid
        else:
            lo = mid + 1
    return lo


def _to_daily_records(
    aligned: List[Tuple[int, float, float]],
) -> List[Dict[str, Any]]:
    """
    从对齐结果中只保留 2025-10-01 至今，按天聚合，每天一条。
    返回 [{"日期": t, "BTC价格": 整数, "MVRV": 1.23}, ...]，按日期升序。
    """
    filtered = [(ts, mvrv, price) for ts, mvrv, price in aligned if ts >= START_TS]
    if not filtered:
        return []
    # 按天分组：day_ts = ts // 86400，同一天取该天最后一个点（ts 最大）
    by_day: Dict[int, Tuple[int, float, float]] = {}
    for ts, mvrv, price in filtered:
        day_ts = ts // 86400
        if day_ts not in by_day or ts > by_day[day_ts][0]:
            by_day[day_ts] = (ts, mvrv, price)
    # 每天一条：日期用该天的代表时间戳 t，BTC 价格保留整数，MVRV 保留两位小数
    daily = [
        {"日期": t, "BTC价格": int(price), "MVRV": round(mvrv, 2)}
        for t, mvrv, price in sorted(by_day.values(), key=lambda x: x[0])
    ]
    return daily


def _get_today_from_aligned(
    aligned: List[Tuple[int, float, float]],
) -> Optional[Dict[str, Any]]:
    """
    从对齐结果中取时间戳最大的一条，返回单条字典。
    结构: {"时间戳": 1770624000, "日期": "2026-02-10", "BTC价格": 70125, "MVRV": 1.27}，BTC价格取整。
    """
    if not aligned:
        return None
    t, mvrv, price = max(aligned, key=lambda x: x[0])
    date_str = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
    return {
        "时间戳": t,
        "日期": date_str,
        "BTC价格": int(price),
        "MVRV": round(mvrv, 2),
    }


def get_today_data() -> Optional[Dict[str, Any]]:
    """
    请求两个接口，按时间对齐后取时间戳最大的一条数据。
    返回 {"时间戳": 1770624000, "日期": "2026-02-10", "BTC价格": 70125, "MVRV": 1.27}，BTC价格取整，无数据则返回 None。
    """
    raw_mvrv = _fetch_json(URL_MCAP_REALIZED)
    mvrv_list = _parse_mvrv_response(raw_mvrv)
    if not mvrv_list:
        return None
    raw_btc = _fetch_json(URL_BTC_PRICE)
    btc_list = _parse_btc_price_response(raw_btc)
    if not btc_list:
        return None
    aligned = _align_by_time(mvrv_list, btc_list)
    return _get_today_from_aligned(aligned)


def _analyze(aligned: List[Tuple[int, float, float]]) -> Dict[str, Any]:
    """对对齐后的 (ts, mvrv, btc_price) 做简单分析。"""
    if not aligned:
        return {"message": "无对齐数据", "count": 0}
    n = len(aligned)
    mvrv_vals = [x[1] for x in aligned]
    btc_vals = [x[2] for x in aligned]
    ts_min, ts_max = aligned[0][0], aligned[-1][0]

    # 简单相关系数（Pearson 近似：用标准化后的点积）
    def mean(vs):
        return sum(vs) / len(vs) if vs else 0

    def std(vs):
        m = mean(vs)
        var = sum((x - m) ** 2 for x in vs) / len(vs) if vs else 0
        return var ** 0.5 if var else 0

    m_mvrv, m_btc = mean(mvrv_vals), mean(btc_vals)
    s_mvrv, s_btc = std(mvrv_vals), std(btc_vals)
    if s_mvrv and s_btc:
        corr = sum((a - m_mvrv) * (b - m_btc) for a, b in zip(mvrv_vals, btc_vals)) / (n * s_mvrv * s_btc)
    else:
        corr = 0.0

    return {
        "count": n,
        "ts_range": [ts_min, ts_max],
        "mvrv_min": min(mvrv_vals),
        "mvrv_max": max(mvrv_vals),
        "mvrv_mean": round(m_mvrv, 4),
        "btc_price_min": min(btc_vals),
        "btc_price_max": max(btc_vals),
        "btc_price_mean": round(m_btc, 4),
        "correlation_mvrv_btc": round(corr, 4),
        "message": (
            "MVRV 与 BTC 价格在同时间对齐下呈正相关，符合「市值/实现价值」与价格同向变动的预期；"
            if corr > 0.3
            else "MVRV 与 BTC 价格相关性较弱或为负，可能因周期、采样间隔或实现价值滞后导致。"
        ),
    }


def fetch_and_analyze() -> Dict[str, Any]:
    """
    请求两个接口，各取最近 200 条，按时间对齐后分析对应关系，并将结果写入 log。
    """
    result = {
        "mvrv_count": 0,
        "btc_count": 0,
        "aligned_count": 0,
        "today": None,
        "analysis": None,
        "error": None,
    }

    log.info("========== handle_mvrv_api 开始 ==========")
    log.info("请求 mCapRealizedRatio: %s", URL_MCAP_REALIZED)
    raw_mvrv = _fetch_json(URL_MCAP_REALIZED)
    mvrv_list = _parse_mvrv_response(raw_mvrv)
    result["mvrv_count"] = len(mvrv_list)
    if not mvrv_list:
        result["error"] = "mCapRealizedRatio 未返回有效数据或 code!=100"
        log.warning(result["error"])
        return result
    log.info("mCapRealizedRatio 解析得到 %s 条（最近 %s 条）", result["mvrv_count"], RECENT_COUNT)

    log.info("请求 BTCPrice: %s", URL_BTC_PRICE)
    raw_btc = _fetch_json(URL_BTC_PRICE)
    btc_list = _parse_btc_price_response(raw_btc)
    result["btc_count"] = len(btc_list)
    if not btc_list:
        result["error"] = "BTCPrice 未返回有效数据或 code!=100"
        log.warning(result["error"])
        return result
    log.info("BTCPrice 解析得到 %s 条（最近 %s 条）", result["btc_count"], RECENT_COUNT)

    aligned = _align_by_time(mvrv_list, btc_list)
    result["aligned_count"] = len(aligned)
    log.info("按时间对齐后共 %s 个点", result["aligned_count"])

    # 时间戳最大的一条: {"时间戳": t, "日期": "YYYY-MM-DD", "BTC价格": 整数, "MVRV": 1.27}
    result["today"] = _get_today_from_aligned(aligned)
    if result["today"]:
        log.info("最新一条数据(日期最大): %s", result["today"])

    # 2025-10-01 至今按天整理：每天一条 {"日期": t, "BTC价格": 整数, "MVRV": 1.23}
    daily = _to_daily_records(aligned)
    result["daily"] = daily
    log.info("2025-10-01 至今按天汇总共 %s 条", len(daily))
    if daily:
        log.info("每日数据样例（前 3 条）: %s", daily[:3])
        log.info("每日数据样例（后 3 条）: %s", daily[-3:])

    analysis = _analyze(aligned)
    result["analysis"] = analysis
    log.info("分析结果: %s", analysis)

    # 输出可能对应关系结论到 log
    log.info("---------- 两接口对应关系结论 ----------")
    log.info(
        "1) 时间对应：mCapRealizedRatio 的 t 为毫秒，已转为秒与 BTCPrice 的 t（秒）对齐；对齐策略为取同一天或最近 2 天内最近邻。"
    )
    log.info(
        "2) 指标含义：mCapRealizedRatio = 市值/实现价值(MVRV)；BTCPrice 为当日或该周期 BTC 价格。二者理论上同向：价格上涨往往伴随市值上升，MVRV 也会抬升。"
    )
    log.info("3) 相关性（本次最近 %s 条对齐样本）: %s", RECENT_COUNT, analysis.get("correlation_mvrv_btc"))
    log.info("4) 结论摘要: %s", analysis.get("message", ""))
    if aligned:
        log.info("5) 对齐样本（前 3 条）: ts(秒), MVRV, BTC价格 -> %s", aligned[:3])
        log.info("6) 对齐样本（后 3 条）: ts(秒), MVRV, BTC价格 -> %s", aligned[-3:])
    log.info("========== handle_mvrv_api 结束 ==========")

    return result


if __name__ == "__main__":
    import json
    # 仅获取时间戳最大的一条（字典结构）
    today = get_today_data()
    if today:
        print(json.dumps(today, ensure_ascii=False))
    else:
        print("暂无对齐数据")
    # 若需完整分析并写 log，可调用: fetch_and_analyze()
