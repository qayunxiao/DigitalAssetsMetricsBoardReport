# -*- coding: UTF-8 -*-
"""
币安 BTC/USDT 全量日 K 成交量：从 2015 年至今，按 30 天一批请求，间隔 3～20 秒，写入 data/cache/btc_all_cache.json。
格式与 btc_cache.json 一致，但时间戳改为日期 YYYYMMDD。
"""
import json
import os
import random
import sys

# 直接运行本脚本时，把项目根加入 path，才能 import utils
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_script_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
import time
from datetime import datetime, timezone

try:
    from utils.handle_log import log
except Exception:
    log = None

from utils.handle_path import project_path
from utils.operationConfig import OperationConfig

SYMBOL = "BTC/USDT"
# 2015-01-01 00:00:00 UTC（币安 2017 年上线，接口会从最早可用日 K 开始返回）
START_DATE = datetime(2015, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
DAYS_PER_REQUEST = 30
DELAY_MIN, DELAY_MAX = 3, 20
CACHE_FILENAME = "btc_all_cache.json"


def _get_proxies():
    """从 config.ini [proxy] 读取代理；未配置时返回 None。"""
    try:
        return OperationConfig().get_proxy_config()
    except Exception:
        return None


def _ts_to_yyyymmdd(ts_ms: int) -> str:
    """时间戳(毫秒) -> YYYYMMDD"""
    try:
        return datetime.utcfromtimestamp(ts_ms / 1000.0).strftime("%Y%m%d")
    except Exception:
        return str(ts_ms)


def _fetch_chunk(exchange, since_ms: int, limit: int = 30):
    """拉取一批日 K，返回 [[time_ms, open, high, low, close, vol], ...]"""
    return exchange.fetch_ohlcv(SYMBOL, timeframe="1d", since=since_ms, limit=limit)


def run():
    cache_path = os.path.join(project_path, "data", "cache", CACHE_FILENAME)
    _proxies = _get_proxies()
    if _proxies:
        print("handle_all_btc: 使用代理 https=%s" % _proxies.get("https", ""))
    else:
        print("handle_all_btc: 未使用代理（若遇「地区限制」请在 config.ini [proxy] 中 ENABLED=1 并确保代理软件已启动）")
    exchange = __import__("ccxt").binance({
        "timeout": 15000,
        "enableRateLimit": True,
        **({"proxies": _proxies} if _proxies else {}),
    })

    start_ms = int(START_DATE.timestamp() * 1000)
    now_utc = datetime.now(timezone.utc)
    end_ms = int(now_utc.timestamp() * 1000)
    one_day_ms = 24 * 3600 * 1000

    daily_list = []  # 元素 [YYYYMMDD, volume]
    since_ms = start_ms
    request_count = 0

    while since_ms < end_ms:
        request_count += 1
        try:
            chunk = _fetch_chunk(exchange, since_ms, limit=DAYS_PER_REQUEST)
        except Exception as e:
            err_msg = str(e).lower()
            if "restricted" in err_msg or "eligibility" in err_msg or "unavailable" in err_msg:
                print("")
                print("币安返回「地区限制」：当前网络无法直接访问。请确认：")
                print("  1. config.ini [proxy] 中 ENABLED=1，HOST/PORT_HTTP/PORT_HTTPS 正确；")
                print("  2. 代理软件（如 Clash、V2Ray）已启动，且端口与 config 一致。")
                print("  3. 代理规则允许 api.binance.com 走代理。")
                if log:
                    log.warning("handle_all_btc: 请求被地区限制 err=%s", e)
            raise
        if not chunk:
            if log:
                log.warning("handle_all_btc: 本批无数据 since=%s %s", since_ms, _ts_to_yyyymmdd(since_ms))
            since_ms += DAYS_PER_REQUEST * one_day_ms
            delay = random.uniform(DELAY_MIN, DELAY_MAX)
            time.sleep(delay)
            continue

        for row in chunk:
            if len(row) < 6:
                continue
            ts_ms = int(row[0])
            vol = float(row[5])
            if ts_ms >= end_ms:
                break
            date_str = _ts_to_yyyymmdd(ts_ms)
            daily_list.append([date_str, vol])

        last_ts = chunk[-1][0]
        since_ms = last_ts + one_day_ms
        print("handle_all_btc: 第 %s 批 获取 %s 条 日期 %s ~ %s" % (request_count, len(chunk), _ts_to_yyyymmdd(int(chunk[0][0])), _ts_to_yyyymmdd(int(chunk[-1][0]))))
        if log:
            log.info("handle_all_btc: 第 %s 批 获取 %s 条 日期 %s ~ %s", request_count, len(chunk), _ts_to_yyyymmdd(int(chunk[0][0])), _ts_to_yyyymmdd(int(chunk[-1][0])))

        if last_ts >= end_ms:
            break

        delay = random.uniform(DELAY_MIN, DELAY_MAX)
        if log:
            log.info("handle_all_btc: 等待 %.1f 秒后下一批", delay)
        time.sleep(delay)

    # 去重：同一 YYYYMMDD 只保留一条（以最后一次出现为准，或第一次——这里按第一次）
    seen = set()
    unique = []
    for d, v in daily_list:
        if d not in seen:
            seen.add(d)
            unique.append([d, v])
    daily_list = unique

    payload = {
        "daily": daily_list,
        "updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
    }
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print("handle_all_btc: 写入完成 共 %s 条 路径 %s 日期范围 %s ~ %s" % (len(daily_list), cache_path, daily_list[0][0] if daily_list else "-", daily_list[-1][0] if daily_list else "-"))
    if log:
        log.info("handle_all_btc: 写入 %s 条 路径 %s", len(daily_list), cache_path)
    return cache_path


if __name__ == "__main__":
    run()
