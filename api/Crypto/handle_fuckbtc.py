# -*- coding: utf-8 -*-
"""
从 https://fuckbtc.com/ 获取比特币看板数据并输出为 JSON。
模块位置: api_list/handle_fuckbtc.py。命令行: python -m api_list.handle_fuckbtc [--report] [--qa|--alvin]。

无需提供接口地址：优先解析页面内嵌 JSON，同时使用公开数据源（Binance、mempool.space）补充实时价格、区块高度、算力等。

免费 API 说明（不付费、限制次数也可）：
- 价格/区块/算力：已用 Binance、mempool.space（免费无 key，仅需代理若被墙）。
- 均衡价格 Balanced Price：市面上无稳定免费 API。Glassnode 需付费；
  若不配置 [glassnode] API_KEY，本脚本返回 balanced_price_usd 为 null。
- 其他免费可选：CoinGecko（免费约 10–30 次/分钟）等。

报表并发钉钉: --report 或 --dingtalk 生成「今日价格、历史最高、跌幅、天数、
今日/平均/最低恐慌贪婪、200WMA、AHR999、下次减半时间」并发送钉钉；可选 --alvin / --qa。
历史最高价与日期来自 config.ini [fuckbtc_report] 的 ATH_PRICE、ATH_DATE。
"""
import json
import math
import os
import random
import re
import sys
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

# 项目根目录加入 path，便于引用 utils（api_list 上一级为根目录）
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from utils.operationConfig import OperationConfig

URL = "https://fuckbtc.com/"
REQUEST_TIMEOUT = 15


def _get_proxies():
    """从 config.ini [proxy] 读取代理；Linux 或未启用时返回 {} 直连（不传 None 以免 requests 用环境变量代理）。"""
    p = OperationConfig().get_proxy_config()
    return p if p else {}


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# 公开数据源（与 fuckbtc.com 页面一致：Binance · mempool.space）
BINANCE_TICKER_URL = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
BINANCE_TICKER_24H_URL = "https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT"  # 页面也用 24hr
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"  # interval=1d&limit=1000，返回 [openTime, open, high, low, close, ...]
MEMPOOL_PRICE_URL = "https://mempool.space/api/v1/prices"
MEMPOOL_TIP_HEIGHT_URL = "https://mempool.space/api/blocks/tip/height"
MEMPOOL_HASHRATE_3D_URL = "https://mempool.space/api/v1/mining/hashrate/3d"  # 页面用 /3d 取当前算力
# Balanced Price（均衡价格）：Glassnode 付费；无稳定免费 API，不配 key 则返回 null
GLASSNODE_BALANCED_PRICE_URL = "https://api.glassnode.com/v1/metrics/indicators/balanced_price_usd"
# CoinGecko 免费（约 10–30 次/分钟），无需 key。simple 仅价格；coins/bitcoin 含市值、涨跌幅、ATH/ATL 等中长线指标
COINGECKO_SIMPLE_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
COINGECKO_COIN_BTC_URL = "https://api.coingecko.com/api/v3/coins/bitcoin?localization=false&tickers=false&community_data=false&developer_data=false"
HALVING_TARGET_BLOCK = 1050000  # 下次减半目标区块

# CoinGecko 免费且对中长线投资 BTC 有帮助的指标（来自 /coins/bitcoin 的 market_data）：
# - market_cap_usd: 市值，看相对规模与周期位置
# - total_volume_usd: 24h 成交额，配合价格看活跃度
# - price_change_pct_7d/30d/60d/200d/1y: 多周期涨跌幅，看趋势与动量
# - ath_usd / atl_usd: 历史最高/最低价，心理关口
# - ath_change_pct / atl_change_pct: 距高点/低点幅度，抄底逃顶参考
# - market_cap_rank: 市值排名（BTC 常为 1）
# 另有 /coins/bitcoin/market_chart 可拉历史序列自算均线；/global 含 btc 市值占比
BLOCK_REWARD_NEXT = 1.5625  # 减半后奖励 BTC
# 200WMA：用 CoinGecko 历史价格自算（约 200 周 = 1400 天）
COINGECKO_MARKET_CHART_RANGE_URL = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart/range"
COINGECKO_MARKET_CHART_DAYS_URL = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
WEEKS_200 = 200
DAYS_FOR_200WMA = WEEKS_200 * 7  # 1400 天
# AHR999 备用代理与主代理一致，均从 config.ini [proxy] 读取
# 恐惧贪婪指数：Alternative.me 免费 API，无需 key
ALTERNATIVE_FNG_URL = "https://api.alternative.me/fng/"
# 关机价估算：参考矿机 25 J/TH，每日每 TH 耗电 0.6 kWh
SHUTDOWN_REF_J_PER_TH = 25
SHUTDOWN_KWH_PER_TH_PER_DAY = (SHUTDOWN_REF_J_PER_TH * 24 * 3600) / 3.6e6  # = 0.6
# 86400 = 24*3600（秒/天），常被误解析或公式单位混用，一律不作为关机价采用
SHUTDOWN_REJECT_MAGIC = 86400
# 关机价/成本：Braiins 免费公开 API（Cost to Mine 等）
BRAIINS_COST_TO_MINE_URL = "https://insights.braiins.com/api/v2.0/cost-to-mine"
# AHR999 合理范围（避免误取到名称里的 999）：通常 0.2～2，放宽到 0.01～10
AHR999_VALID_MIN, AHR999_VALID_MAX = 0.01, 10.0
# CoinGlass AHR999 公开接口（可能需 key，先试）
COINGLASS_AHR999_URL = "https://open-api-v4.coinglass.com/api/index/ahr999"

# metrics 各 key 的中文注释（用于返回 metrics_labels）
METRICS_LABELS_CN: Dict[str, str] = {
    "btc_price_usd": "BTC价格(美元)",
    "electricity_cost_usd": "电费(美元/kWh)",
    "current_block": "当前区块高度",
    "target_block": "下次减半目标区块高度",
    "halving_countdown_blocks": "减半倒计时(剩余区块数)",
    "halving_countdown_days_approx": "减半倒计时(约天数)",
    "reward_next_btc": "减半后区块奖励(BTC)",
    "hashrate_eh_s": "全网算力(EH/s)",
    "balanced_price_usd": "均衡价格(美元)",
    "source_binance": "价格数据来源(Binance)",
    "source_mempool": "区块/算力数据来源(mempool.space)",
    "source_balanced_price": "均衡价格数据来源(Glassnode)",
    "fetch_time": "抓取时间",
    "btc_200wma_usd": "BTC 200周均线(美元)",
    "fear_greed_index": "恐惧贪婪指数(0-100)",
    "ahr999": "AHR999 定投指数",
    "ahr999_200d_avg_usd": "AHR999 200日定投成本(美元)",
    "source_200wma": "200周均线数据来源(CoinGecko历史价自算)",
    "source_fear_greed": "恐惧贪婪数据来源(Alternative.me)",
    "source_ahr999": "AHR999数据来源(coinsoto)",
    "shutdown_price_range": "关机价(美元, 区间或单值)",
    "shutdown_price_avg_miners": "关机价(矿机详情表全部取平均)",
}
COINGECKO_BTC_LABELS_CN: Dict[str, str] = {
    "market_cap_usd": "市值(美元)",
    "total_volume_usd_24h": "24小时成交额(美元)",
    "price_change_pct_7d": "7日涨跌幅(%)",
    "price_change_pct_30d": "30日涨跌幅(%)",
    "price_change_pct_60d": "60日涨跌幅(%)",
    "price_change_pct_200d": "200日涨跌幅(%)",
    "price_change_pct_1y": "1年涨跌幅(%)",
    "ath_usd": "历史最高价(美元)",
    "atl_usd": "历史最低价(美元)",
    "ath_change_pct_usd": "距历史高点涨跌幅(%)",
    "atl_change_pct_usd": "距历史低点涨跌幅(%)",
    "market_cap_rank": "市值排名",
    "source": "数据来源",
}


def _build_metrics_labels(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """根据当前 metrics 的 key 生成带中文注释的 metrics_labels（仅包含本次返回中存在的 key）。"""
    labels: Dict[str, Any] = {}
    for k in metrics:
        if k in METRICS_LABELS_CN:
            labels[k] = METRICS_LABELS_CN[k]
        elif k == "coingecko_btc" and isinstance(metrics.get(k), dict):
            labels[k] = {ck: COINGECKO_BTC_LABELS_CN.get(ck, ck) for ck in metrics[k]}
        else:
            labels[k] = k  # 未知 key 原样保留
    return labels


def _fetch_public_apis() -> Dict[str, Any]:
    """从公开接口（Binance、mempool.space）拉取实时数据，无需用户提供接口地址。"""
    metrics: Dict[str, Any] = {
        "btc_price_usd": None,
        "electricity_cost_usd": "0.060",
        "current_block": None,
        "target_block": HALVING_TARGET_BLOCK,
        "halving_countdown_blocks": None,
        "halving_countdown_days_approx": None,
        "reward_next_btc": BLOCK_REWARD_NEXT,
        "hashrate_eh_s": None,
        "balanced_price_usd": None,  # 均衡价格，与页面一致需 Glassnode API
        "source_binance": None,
        "source_mempool": None,
        "source_balanced_price": None,
    }
    try:
        r = requests.get(BINANCE_TICKER_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT, proxies=_get_proxies())
        if r.ok:
            data = r.json()
            metrics["btc_price_usd"] = data.get("price")
            metrics["source_binance"] = "Binance"
    except Exception:
        pass
    if not metrics.get("btc_price_usd"):
        try:
            r = requests.get(BINANCE_TICKER_24H_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT, proxies=_get_proxies())
            if r.ok:
                data = r.json()
                metrics["btc_price_usd"] = data.get("lastPrice")
                metrics["source_binance"] = "Binance"
        except Exception:
            pass
    try:
        r = requests.get(MEMPOOL_TIP_HEIGHT_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT, proxies=_get_proxies())
        if r.ok:
            height = int(r.text.strip())
            metrics["current_block"] = height
            metrics["halving_countdown_blocks"] = max(0, HALVING_TARGET_BLOCK - height)
            # 约 10 分钟一块，一天约 144 块
            metrics["halving_countdown_days_approx"] = metrics["halving_countdown_blocks"] // 144
            metrics["source_mempool"] = "mempool.space"
    except Exception:
        pass
    try:
        r = requests.get(MEMPOOL_PRICE_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT, proxies=_get_proxies())
        if r.ok and not metrics.get("btc_price_usd"):
            data = r.json()
            if "USD" in data:
                metrics["btc_price_usd"] = str(data["USD"])
    except Exception:
        pass
    # 免费备用：CoinGecko 无需 key，约 10–30 次/分钟
    if not metrics.get("btc_price_usd"):
        try:
            r = requests.get(COINGECKO_SIMPLE_PRICE_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT, proxies=_get_proxies())
            if r.ok:
                data = r.json()
                if isinstance(data.get("bitcoin"), dict) and "usd" in data["bitcoin"]:
                    metrics["btc_price_usd"] = str(round(float(data["bitcoin"]["usd"]), 0))
        except Exception:
            pass
    # 与页面一致：使用 /3d 接口，currentHashrate 单位为 H/s，除以 1e18 得 EH/s
    try:
        r = requests.get(MEMPOOL_HASHRATE_3D_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT, proxies=_get_proxies())
        if r.ok:
            data = r.json()
            if isinstance(data, dict) and "currentHashrate" in data:
                h = data["currentHashrate"]
                if h is not None and isinstance(h, (int, float)):
                    metrics["hashrate_eh_s"] = round(float(h) / 1e18, 2)
    except Exception:
        pass
    # Balanced Price（均衡价格，页面显示如 41,528），来自 Glassnode，优先读 config.ini [glassnode] API_KEY
    api_key = OperationConfig().get_glassnode_api_key() or os.environ.get("GLASSNODE_API_KEY", "").strip()
    if api_key:
        try:
            r = requests.get(
                GLASSNODE_BALANCED_PRICE_URL,
                params={"a": "BTC", "i": "24h", "f": "json", "api_key": api_key},
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
                proxies=_get_proxies(),
            )
            if r.ok:
                data = r.json()
                if isinstance(data, list) and len(data) > 0 and isinstance(data[-1], dict) and "v" in data[-1]:
                    v = data[-1]["v"]
                    if v is not None:
                        metrics["balanced_price_usd"] = int(v) if isinstance(v, float) and v == int(v) else round(float(v), 2)
                        metrics["source_balanced_price"] = "Glassnode"
        except Exception:
            pass
    return metrics


def _fetch_coingecko_btc_indicators() -> Optional[Dict[str, Any]]:
    """
    拉取 CoinGecko 免费 API 中与中长线投资 BTC 相关的指标（市值、多周期涨跌幅、ATH/ATL 等）。
    免费、无需 key，注意控制调用频率（约 10–30 次/分钟）。
    """
    try:
        r = requests.get(
            COINGECKO_COIN_BTC_URL,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            proxies=_get_proxies(),
        )
        if not r.ok:
            return None
        data = r.json()
        md = data.get("market_data")
        if not isinstance(md, dict):
            return None
        out: Dict[str, Any] = {}
        if "market_cap" in md and isinstance(md["market_cap"], dict) and "usd" in md["market_cap"]:
            out["market_cap_usd"] = md["market_cap"]["usd"]
        if "total_volume" in md and isinstance(md["total_volume"], dict) and "usd" in md["total_volume"]:
            out["total_volume_usd_24h"] = md["total_volume"]["usd"]
        for key, label in [
            ("price_change_percentage_7d", "price_change_pct_7d"),
            ("price_change_percentage_30d", "price_change_pct_30d"),
            ("price_change_percentage_60d", "price_change_pct_60d"),
            ("price_change_percentage_200d", "price_change_pct_200d"),
            ("price_change_percentage_1y", "price_change_pct_1y"),
        ]:
            if key in md and md[key] is not None:
                val = md[key]
                if isinstance(val, dict) and "usd" in val:
                    out[label] = val["usd"]
                elif isinstance(val, (int, float)):
                    out[label] = val
        if "ath" in md and isinstance(md["ath"], dict) and "usd" in md["ath"]:
            out["ath_usd"] = md["ath"]["usd"]
        if "atl" in md and isinstance(md["atl"], dict) and "usd" in md["atl"]:
            out["atl_usd"] = md["atl"]["usd"]
        ac = md.get("ath_change_percentage")
        if ac is not None:
            out["ath_change_pct_usd"] = ac.get("usd") if isinstance(ac, dict) else ac
        alc = md.get("atl_change_percentage")
        if alc is not None:
            out["atl_change_pct_usd"] = alc.get("usd") if isinstance(alc, dict) else alc
        if "market_cap_rank" in md:
            out["market_cap_rank"] = md["market_cap_rank"]
        out["source"] = "CoinGecko"
        return out if out else None
    except Exception:
        return None


def _compute_200wma_from_prices(prices: List) -> Optional[float]:
    """从 CoinGecko prices [[ts_ms, price], ...] 按周聚合后计算 200 周均线。"""
    return _compute_200wma_from_ts_price_list(prices, ts_idx=0, price_idx=1)


def _compute_200wma_from_ts_price_list(
    items: List, ts_idx: int = 0, price_idx: int = 1
) -> Optional[float]:
    """从 [[ts, price], ...] 或 [[ts, _, _, _, close], ...] 按周聚合后计算 200 周均线。"""
    if not isinstance(items, list) or len(items) < WEEKS_200:
        return None
    week_to_price: Dict[int, float] = {}
    for item in items:
        if not isinstance(item, (list, tuple)) or len(item) <= max(ts_idx, price_idx):
            continue
        try:
            ts_ms = int(item[ts_idx])
            price = item[price_idx]
            if price is None:
                continue
            p = float(price)
            week_key = int(ts_ms // (7 * 24 * 3600 * 1000))
            week_to_price[week_key] = p
        except (TypeError, ValueError, IndexError):
            continue
    weeks_sorted = sorted(week_to_price.keys())
    if len(weeks_sorted) < WEEKS_200:
        return None
    last_200_weeks = weeks_sorted[-WEEKS_200:]
    values = [week_to_price[w] for w in last_200_weeks]
    return round(sum(values) / len(values), 2)


def _fetch_btc_200wma() -> Optional[float]:
    """
    用 CoinGecko 免费 API 拉取历史价格，按周聚合后计算 200 周均线（200WMA）。
    先试 market_chart/range，再试 market_chart?days=max（免费、无需 key）。
    """
    # 1) 先试 range（1400 天）
    try:
        to_ts = int(datetime.now().timestamp())
        from_ts = int((datetime.now() - timedelta(days=DAYS_FOR_200WMA)).timestamp())
        r = requests.get(
            COINGECKO_MARKET_CHART_RANGE_URL,
            params={"vs_currency": "usd", "from": from_ts, "to": to_ts},
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            proxies=_get_proxies(),
        )
        if r.ok:
            data = r.json()
            wma = _compute_200wma_from_prices(data.get("prices"))
            if wma is not None:
                return wma
    except Exception:
        pass
    # 2) 再试 days=max（部分环境 range 限制天数，max 可返回更长历史）
    try:
        r = requests.get(
            COINGECKO_MARKET_CHART_DAYS_URL,
            params={"vs_currency": "usd", "days": "max"},
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            proxies=_get_proxies(),
        )
        if r.ok:
            data = r.json()
            wma = _compute_200wma_from_prices(data.get("prices"))
            if wma is not None:
                return wma
    except Exception:
        pass
    # 3) 备用：Binance 日 K 线（免费、每批 1000 根，拉 2 批约 2000 天，足够 200 周）
    wma_binance = _fetch_btc_200wma_binance()
    if wma_binance is not None:
        return wma_binance
    return None


def _fetch_btc_200wma_binance() -> Optional[float]:
    """用 Binance 公开 API 拉取 BTCUSDT 日 K，合并后按周聚合计算 200 周均线。免费、无需 key。"""
    try:
        # 第一批：最近 1000 天
        r1 = requests.get(
            BINANCE_KLINES_URL,
            params={"symbol": "BTCUSDT", "interval": "1d", "limit": 1000},
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            proxies=_get_proxies(),
        )
        if not r1.ok:
            return None
        klines1 = r1.json()
        if not isinstance(klines1, list) or len(klines1) < 200:
            return None
        # 第二批：更早 1000 天（endTime 取第一批最早一根的开盘时间 - 1）
        first_ts = klines1[0][0]
        r2 = requests.get(
            BINANCE_KLINES_URL,
            params={"symbol": "BTCUSDT", "interval": "1d", "limit": 1000, "endTime": first_ts - 1},
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            proxies=_get_proxies(),
        )
        klines2 = r2.json() if r2.ok and isinstance(r2.json(), list) else []
        # 合并：Binance 单条 [openTime, open, high, low, close, ...]，close 下标 4
        merged = list(klines2) + list(klines1)
        if len(merged) < 1400:
            # 数据不足 1400 天则用现有数据尝试（可能不足 200 周）
            pass
        return _compute_200wma_from_ts_price_list(merged, ts_idx=0, price_idx=4)
    except Exception:
        return None


def _fetch_fear_greed() -> Optional[Dict[str, Any]]:
    """拉取 Alternative.me 恐惧贪婪指数（免费、无需 key）。"""
    try:
        r = requests.get(
            ALTERNATIVE_FNG_URL,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            proxies=_get_proxies(),
        )
        if not r.ok:
            return None
        data = r.json()
        arr = data.get("data")
        if not isinstance(arr, list) or len(arr) == 0:
            return None
        latest = arr[0]
        if not isinstance(latest, dict):
            return None
        value = latest.get("value")
        if value is None:
            return None
        return {
            "value": int(value) if str(value).isdigit() else None,
            "value_classification": latest.get("value_classification"),
            "timestamp": latest.get("timestamp"),
        }
    except Exception:
        return None


def _fetch_fear_greed_history(days: int) -> Optional[List[int]]:
    """拉取从某日至今的恐惧贪婪历史（Alternative.me POST history），返回每日数值列表，顺序与 API 一致。"""
    if days <= 0:
        return None
    try:
        conf = OperationConfig().get_apiinfo()
        url = conf.get("api_fear")
        if not url:
            return None
        r = requests.post(
            url,
            json={"days": min(days, 9999)},
            headers={**HEADERS, "Content-Type": "application/json"},
            timeout=REQUEST_TIMEOUT,
            proxies=_get_proxies(),
        )
        if not r.ok:
            return None
        data = r.json()
        datasets = data.get("data", {}).get("datasets")
        if not isinstance(datasets, list) or len(datasets) == 0:
            return None
        values = datasets[0].get("data")
        if not isinstance(values, list):
            return None
        out = []
        for v in values:
            if v is None:
                continue
            try:
                out.append(int(v))
            except (TypeError, ValueError):
                continue
        return out if out else None
    except Exception:
        return None


def _fetch_ahr999() -> Optional[Dict[str, Any]]:
    """从 config [url] API_ARH999NEW（coinsoto）拉取最新 AHR999，免费。先试主代理，失败则试备用代理。"""
    conf = OperationConfig().get_apiinfo()
    url = conf.get("api_arh999new")
    if not url:
        return None
    headers = {**HEADERS, "Content-Type": "application/json"}
    # 与 handle_ahr999new 一致的 User-Agent，部分接口会校验
    headers.setdefault("User-Agent", "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.198 Safari/537.36")

    def _request(proxies: Optional[Dict[str, str]]) -> Optional[Dict[str, Any]]:
        try:
            r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT, proxies=proxies)
            if not r.ok:
                return None
            data = r.json()
            arr = data.get("data")
            if not isinstance(arr, list) or len(arr) == 0:
                return None
            row = arr[0]
            if not isinstance(row, dict):
                return None
            ahr = row.get("ahr999")
            avg = row.get("avg")
            out = {}
            if ahr is not None:
                out["ahr999"] = round(float(ahr), 4) if isinstance(ahr, (int, float)) else ahr
            if avg is not None:
                out["avg_200d_usd"] = round(float(avg), 2) if isinstance(avg, (int, float)) else avg
            out["source"] = "coinsoto"
            return out if out else None
        except Exception:
            return None

    result = _request(_get_proxies())
    if result is not None and _is_valid_ahr999(result.get("ahr999")):
        return result
    result = _request(_get_proxies())
    if result is not None and _is_valid_ahr999(result.get("ahr999")):
        return result
    result = _fetch_ahr999_soulbab()
    if result is not None and _is_valid_ahr999(result.get("ahr999")):
        return result
    result = _fetch_ahr999_coinglass()
    if result is not None and _is_valid_ahr999(result.get("ahr999")):
        return result
    return _fetch_ahr999_via_project_api()


def _fetch_ahr999_coinglass() -> Optional[Dict[str, Any]]:
    """从 CoinGlass 开放接口拉取 AHR999（可能需 key，先试）。"""
    try:
        r = requests.get(
            COINGLASS_AHR999_URL,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            proxies=_get_proxies(),
        )
        if not r.ok:
            return None
        data = r.json()
        if not isinstance(data, dict):
            return None
        # 常见结构: data.list[0].value 或 data.data.ahr999
        ahr_val = None
        if "data" in data:
            d = data["data"]
            if isinstance(d, dict) and "ahr999" in d:
                ahr_val = d.get("ahr999")
            elif isinstance(d, list) and len(d) > 0:
                item = d[0]
                if isinstance(item, dict):
                    ahr_val = item.get("ahr999") or item.get("value") or item.get("index")
        if "list" in data and isinstance(data["list"], list) and len(data["list"]) > 0:
            first = data["list"][0]
            if isinstance(first, dict):
                ahr_val = ahr_val or first.get("value") or first.get("ahr999")
        if ahr_val is not None and _is_valid_ahr999(ahr_val):
            return {"ahr999": round(float(ahr_val), 4), "source": "coinglass"}
        return None
    except Exception:
        return None


def _fetch_ahr999_soulbab() -> Optional[Dict[str, Any]]:
    """从 config [url] API_ARH999（soulbab/dncapi）拉取 AHR999，免费。"""
    try:
        conf = OperationConfig().get_apiinfo()
        url = conf.get("api_arh999")
        if not url:
            return None
        r = requests.get(
            url,
            params={"code": "bitcoin", "webp": 1} if "?" not in url else None,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            proxies=_get_proxies(),
        )
        if not r.ok:
            return None
        data = r.json()
        ahr_val = None
        if isinstance(data, dict):
            ahr_val = data.get("ahr999")
            if ahr_val is None and "data" in data:
                d = data["data"]
                if isinstance(d, dict):
                    ahr_val = d.get("ahr999")
                elif isinstance(d, list) and len(d) > 0 and isinstance(d[0], dict):
                    ahr_val = d[0].get("ahr999")
            if ahr_val is not None and not isinstance(ahr_val, (int, float)):
                try:
                    ahr_val = float(ahr_val)
                except (TypeError, ValueError):
                    ahr_val = None
        if ahr_val is not None and _is_valid_ahr999(ahr_val):
            return {"ahr999": round(float(ahr_val), 4), "source": "soulbab"}
        return None
    except Exception:
        return None


def _fetch_ahr999_via_project_api() -> Optional[Dict[str, Any]]:
    """通过 api_list.handle_ahr999new 拉取 AHR999，与项目其它脚本一致。"""
    try:
        from api_list.handle_AHR999 import get_api_ahr999new
        api = get_api_ahr999new()
        data = api.get_ahr_table()
        if not data or not isinstance(data.get("data"), list) or len(data["data"]) == 0:
            return None
        row = data["data"][0]
        if not isinstance(row, dict):
            return None
        ahr = row.get("ahr999")
        avg = row.get("avg")
        out = {}
        if ahr is not None:
            out["ahr999"] = round(float(ahr), 4) if isinstance(ahr, (int, float)) else ahr
        if avg is not None:
            out["avg_200d_usd"] = round(float(avg), 2) if isinstance(avg, (int, float)) else avg
        out["source"] = "coinsoto(via handle_ahr999new)"
        return out if out else None
    except Exception:
        return None


def _is_valid_ahr999(value: Any) -> bool:
    """AHR999 定投指数合理范围约 0.2～2，避免误用名称中的 999。"""
    try:
        v = float(value)
        return AHR999_VALID_MIN <= v <= AHR999_VALID_MAX
    except (TypeError, ValueError):
        return False


def _extract_ahr999_from_fuckbtc(html: str) -> Optional[float]:
    """
    从 fuckbtc.com 页面提取「AHR999 定投指数」数值，仅接受合理范围 (0.01～10)。
    顺序：__NEXT_DATA__ → 正则 → DOM；DOM 时优先取小数 (0.xx)，排除名称中的 999。
    """
    def _valid(v: Optional[float]) -> Optional[float]:
        if v is not None and _is_valid_ahr999(v):
            return round(float(v), 4)
        return None

    # 1) __NEXT_DATA__ 内递归查找 key 含 ahr999 的数值
    next_data = _extract_next_data(html)
    if next_data:
        def _find_ahr999(obj: Any) -> Optional[float]:
            if obj is None:
                return None
            if isinstance(obj, (int, float)):
                return float(obj) if _is_valid_ahr999(obj) else None
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if "ahr999" in str(k).lower():
                        f = _find_ahr999(v)
                        if f is not None:
                            return f
                for v in obj.values():
                    f = _find_ahr999(v)
                    if f is not None:
                        return f
            if isinstance(obj, list):
                for v in obj:
                    f = _find_ahr999(v)
                    if f is not None:
                        return f
            return None
        v = _find_ahr999(next_data)
        if v is not None:
            return _valid(v)

    # 2) 正则：仅接受合理范围内的数字
    for pat in [
        r'定投指数["\s:：]+([0-9]*\.[0-9]+)',  # 优先小数 0.xx
        r'"ahr999"\s*:\s*([0-9]*\.[0-9]+)',
        r'ahr999["\s:：]+([0-9]*\.[0-9]+)',
        r'定投["\s]*[指数]*["\s]*[：:]\s*([0-9]*\.[0-9]+)',
    ]:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            try:
                return _valid(float(m.group(1)))
            except (ValueError, IndexError):
                pass

    # 3) DOM：取所有候选数字，选在合理范围内的（优先 0.x 小数，排除 999）
    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all(string=re.compile(r"AHR999|定投指数", re.I)):
            parent = tag.parent
            if not parent:
                continue
            full = parent.get_text(strip=True)
            for num_m in re.finditer(r"([0-9]+\.?[0-9]*)", full):
                try:
                    v = float(num_m.group(1))
                    if _is_valid_ahr999(v):
                        return round(v, 4)
                except ValueError:
                    pass
            for sibling in [parent.find_next_sibling(), parent.parent.find_next_sibling() if parent.parent else None]:
                if sibling is None:
                    continue
                t = sibling.get_text(strip=True)
                if re.match(r"^[0-9]+\.?[0-9]*$", t):
                    try:
                        return _valid(float(t))
                    except ValueError:
                        pass
    except Exception:
        pass
    return None


def _extract_next_data(html: str) -> Optional[dict]:
    """尝试从 Next.js 页面提取 __NEXT_DATA__ 中的 JSON。"""
    match = re.search(r'<script\s+id="__NEXT_DATA__"\s+type="application/json">(.*?)</script>', html, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass
    return None


def _extract_script_json(html: str) -> Optional[dict]:
    """尝试从任意 script type=application/json 或大块 JSON 提取数据。"""
    # type="application/json"
    for m in re.finditer(r'<script[^>]+type=["\']application/json["\'][^>]*>(.*?)</script>', html, re.DOTALL):
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            continue
    # 常见 SPA 内嵌：window.__PRELOADED_STATE__ = {...}
    for pattern in [
        r'window\.__PRELOADED_STATE__\s*=\s*(\{.*?\});?\s*(?:</script>|$)',
        r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});?\s*',
        r'__NUXT_DATA__\s*=\s*(\{.*?\});?\s*',
    ]:
        match = re.search(pattern, html, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass
    return None


def _looks_like_metric_value(txt: str) -> bool:
    """
    判断文本是否「像」指标数值，而非页面标签/描述。
    避免把「矿机详情矿机型号算力…」「ahr999 定投指数」等当成真实数据。
    """
    if not txt or len(txt) > 45:
        return False
    # 明显是标签或整句描述（含多个中文词）
    label_keywords = (
        "指数", "详情", "型号", "市值", "从未", "跌破", "参考", "过热", "低估", "正常",
        "定投", "恐惧", "贪婪", "均衡价格", "Balanced Price", "MVRV Ratio", "200WMA",
        "减半倒计时", "矿机", "功耗", "关机价", "状态", "当前价格", "历史上",
    )
    if any(k in txt for k in label_keywords):
        return False
    # 接受：纯数字、$ 价格、倍数（如 1.2x）、短数字
    if re.match(r"^[\d,.$%\sx\-]+$", txt):
        return True
    if re.match(r"^\d+\.?\d*$", txt):
        return True
    # 短且含数字（如 "72" "0.45" "$70,000"）
    if len(txt) <= 20 and re.search(r"\d", txt):
        return True
    return False


def _parse_dom_metrics(soup: BeautifulSoup) -> Dict[str, Any]:
    """从 DOM 解析指标：只采纳「像数值」的短文，丢弃标签/描述避免污染。"""
    result = {
        "btc_price": None,
        "electricity_cost_usd": None,
        "hashrate_eh_s": None,
        "shutdown_price_range": None,
        "profitable_miners": None,
        "ahr999": None,
        "fear_greed_index": None,
        "wma200_usd": None,
        "price_vs_wma200": None,
        "balanced_price_usd": None,
        "price_vs_bp": None,
        "mvrv_ratio": None,
        "halving_countdown_days": None,
        "current_block": None,
        "target_block": None,
        "reward_next": None,
        "mstr_mnav": None,
        "sbet_mnav": None,
        "bmnr_mnav": None,
        "miner_table": [],
        "fetch_time": datetime.now().isoformat(),
        "source": URL,
    }

    tables = soup.find_all("table")
    for table in tables:
        rows = []
        for tr in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if cells:
                rows.append(cells)
        if rows:
            result["miner_table"].append({
                "headers": rows[0],
                "rows": rows[1:] if len(rows) > 1 else []
            })

    # 仅当元素 class 与指标对应且文本「像数值」时才写入，避免用标签或无关数字污染
    for div in soup.find_all(["div", "span"], class_=True):
        cls = " ".join(div.get("class", []))
        txt = div.get_text(strip=True)
        if not txt or txt in ("--", "---", "加载中...", ""):
            continue
        # 关机价：class 含 shutdown/关机 且文本含数字即采纳；或文本含「关机价」时取合理区间数字（约 2万～12万）
        if ("shutdown" in cls.lower() or "关机" in cls.lower()) and result["shutdown_price_range"] is None and re.search(r"\d", txt):
            result["shutdown_price_range"] = txt.strip()
            continue
        if "关机价" in txt and result["shutdown_price_range"] is None:
            num_match = re.search(r"([4-9]\d{4}|[1-9]\d{5,6})", txt.replace(",", ""))
            if num_match:
                result["shutdown_price_range"] = num_match.group(1)
            continue
        if not _looks_like_metric_value(txt):
            continue
        if "price" in cls.lower() and "btc" in cls.lower() and result["btc_price"] is None:
            result["btc_price"] = txt
        if "electricity" in cls.lower() and result["electricity_cost_usd"] is None:
            result["electricity_cost_usd"] = txt
        if "hashrate" in cls.lower() and result["hashrate_eh_s"] is None:
            result["hashrate_eh_s"] = txt
        if "wma" in cls.lower() and result["wma200_usd"] is None:
            result["wma200_usd"] = txt
        if "balanced" in cls.lower() and result["balanced_price_usd"] is None:
            result["balanced_price_usd"] = txt
        if "mvrv" in cls.lower() and result["mvrv_ratio"] is None:
            result["mvrv_ratio"] = txt
    # ahr999、恐惧贪婪、减半天数、区块等由公开 API 或内嵌 JSON 提供，不再从 DOM 用「任意数字」填充

    return result


def _fetch_shutdown_price_from_braiins() -> Optional[str]:
    """
    从 Braiins Insights 免费 API 获取 Cost to Mine / 关机价相关数据。
    GET https://insights.braiins.com/api/v2.0/cost-to-mine 可能返回成本或 breakeven 等。
    """
    try:
        r = requests.get(
            BRAIINS_COST_TO_MINE_URL,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            proxies=_get_proxies(),
        )
        if not r.ok:
            return None
        data = r.json()
        if not isinstance(data, (dict, list)):
            return None
        # 可能结构: {"data": [{"cost_to_mine": 50000, ...}], ...} 或 直接 [{"cost": 50000}, ...]
        def _find_price(obj: Any) -> Optional[float]:
            if obj is None:
                return None
            if isinstance(obj, (int, float)) and 1000 < obj < 1e7:
                return float(obj)
            if isinstance(obj, dict):
                for key in ("cost_to_mine", "costToMine", "shutdown_price", "breakeven", "break_even", "price_usd"):
                    if key in obj and obj[key] is not None:
                        try:
                            p = float(obj[key])
                            if 1000 < p < 1e7:
                                return p
                        except (TypeError, ValueError):
                            pass
            if isinstance(obj, list) and len(obj) > 0:
                return _find_price(obj[-1])  # 取最新一条
            return None
        price = _find_price(data)
        if price is not None:
            return str(round(price, 0))
        return None
    except Exception:
        return None


def _avg_shutdown_from_miner_table(miner_table: List[Dict[str, Any]]) -> Optional[float]:
    """
    从矿机详情表（fuckbtc 矿机详情）解析「关机价」列，计算全部有效关机价的平均值。
    表结构: [{"headers": ["矿机型号", "算力", "功耗", "功耗比", "关机价", "状态"], "rows": [[...], ...]}]
    """
    if not miner_table or not isinstance(miner_table, list):
        return None
    values: List[float] = []
    for tbl in miner_table:
        if not isinstance(tbl, dict):
            continue
        headers = tbl.get("headers") or []
        rows = tbl.get("rows") or []
        if not headers or not rows:
            continue
        # 找「关机价」列下标（兼容中文表头）
        col_idx = None
        for i, h in enumerate(headers):
            if h and "关机价" in str(h).strip():
                col_idx = i
                break
        if col_idx is None:
            continue
        for row in rows:
            if not isinstance(row, (list, tuple)) or col_idx >= len(row):
                continue
            cell = row[col_idx]
            if cell is None or (isinstance(cell, str) and cell.strip() in ("", "--", "---", "–")):
                continue
            try:
                s = str(cell).strip().replace(",", "").replace("$", "").replace(" ", "")
                if not s or not re.search(r"\d", s):
                    continue
                # 去掉可能的单位或后缀
                num_str = re.match(r"([0-9]+\.?[0-9]*)", s)
                if num_str:
                    v = float(num_str.group(1))
                    if 10000 <= v <= 200000:  # 合理关机价区间
                        values.append(v)
            except (ValueError, TypeError):
                continue
    if not values:
        return None
    avg = round(sum(values) / len(values), 0)
    if avg == SHUTDOWN_REJECT_MAGIC:
        return None
    return avg


def _extract_shutdown_price_from_html(html: str) -> Optional[str]:
    """从页面 HTML 中正则提取关机价（约 2万～12万 的整数）。"""
    for pat in [
        r"关机价[^0-9]*([4-9]\d{4}|[1-9]\d{5,6})",
        r"shutdown[^0-9]*([4-9]\d{4}|[1-9]\d{5,6})",
        r"关机[^0-9]{0,20}([4-9]\d{4}|[1-9]\d{5,6})",
    ]:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            s = m.group(1).replace(",", "")
            n = int(s)
            if 20000 <= n <= 150000 and n != SHUTDOWN_REJECT_MAGIC:
                return s
    return None


def _compute_shutdown_price_estimate(metrics: Dict[str, Any]) -> Optional[str]:
    """
    根据电费与全网算力估算关机价（参考 25 J/TH 矿机）。
    公式：关机价 = (每日每TH耗电 kWh × 电费) / (每日每TH产出的 BTC)；无算力/电费时返回 None。
    """
    try:
        hashrate_eh = metrics.get("hashrate_eh_s")
        if hashrate_eh is None:
            return None
        if isinstance(hashrate_eh, str):
            hashrate_eh = float(hashrate_eh.replace(",", ""))
        hashrate_eh = float(hashrate_eh)
        if hashrate_eh <= 0:
            return None
        cost_usd = metrics.get("electricity_cost_usd")
        if cost_usd is None:
            cost_usd = 0.06
        if isinstance(cost_usd, str):
            cost_usd = float(cost_usd.replace(",", ""))
        cost_usd = float(cost_usd)
        # 当前区块奖励 3.125 BTC（减半后为 1.5625）
        cb = metrics.get("current_block")
        if isinstance(cb, str):
            try:
                cb = int(cb.replace(",", ""))
            except ValueError:
                cb = None
        block_reward = 1.5625 if (cb is not None and cb >= HALVING_TARGET_BLOCK) else 3.125
        # 每日每 TH/s 产出 BTC = block_reward * 144 / (hashrate_EH * 1e6)
        daily_btc_per_th = (block_reward * 144) / (hashrate_eh * 1e6)
        if daily_btc_per_th <= 0:
            return None
        # 每日每 TH 电费 = 0.6 kWh * cost_usd
        cost_per_th_per_day = SHUTDOWN_KWH_PER_TH_PER_DAY * cost_usd
        shutdown_usd = cost_per_th_per_day / daily_btc_per_th
        rounded = round(shutdown_usd, 0)
        # 86400 为 24*3600，多为单位/解析错误，不采用
        if rounded == SHUTDOWN_REJECT_MAGIC:
            return None
        return str(int(rounded))
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _parse_ath_date(ath_date_str: str) -> Optional[datetime]:
    """解析 config 中的 ATH_DATE（如 2025-10-06）为 date。"""
    try:
        return datetime.strptime(ath_date_str.strip()[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _next_halving_datetime(current_block: Optional[int]) -> Optional[str]:
    """根据当前区块高度估算下次减半时间，返回格式 YYYY-MM-DD HH:mm。"""
    if current_block is None or current_block <= 0:
        return None
    try:
        blocks_left = max(0, HALVING_TARGET_BLOCK - int(current_block))
        # 约 10 分钟一块
        minutes_left = blocks_left * 10
        next_ts = datetime.now() + timedelta(minutes=minutes_left)
        return next_ts.strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return None


def build_btc_report(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """
    根据 metrics 与 config [fuckbtc_report] 构建钉钉报表所需字段：
    今日价格、历史最高)、跌幅、距最高天数、今日恐慌、自最高至今平均/最低恐慌、200WMA、AHR999、下次减半时间。
    """
    time.sleep(random.uniform(1, 10))
    report_config = OperationConfig().get_fuckbtc_report_config()
    ath_price = report_config.get("ath_price", 126199)
    ath_date_str = report_config.get("ath_date", "2025-10-06")
    ath_date_dt = _parse_ath_date(ath_date_str)

    # 今日价格
    today_price_raw = metrics.get("btc_price_usd")
    if isinstance(today_price_raw, str):
        today_price = float(today_price_raw.replace(",", "")) if today_price_raw else None
    else:
        today_price = float(today_price_raw) if today_price_raw is not None else None

    # 历史最高126199到现在跌幅、天数
    drop_pct = None
    if today_price is not None and ath_price and ath_price > 0:
        drop_pct = round((ath_price - today_price) / ath_price * 100, 2)
    days_since_ath = None
    if ath_date_dt:
        days_since_ath = (datetime.now() - ath_date_dt.replace(hour=0, minute=0, second=0, microsecond=0)).days

    # 今日恐慌贪婪
    fg = metrics.get("fear_greed_index")
    fear_today = None
    if isinstance(fg, dict) and fg.get("value") is not None:
        fear_today = int(fg["value"])

    # 自历史最高至今的恐慌历史：平均、最低
    fear_history = _fetch_fear_greed_history(days_since_ath) if days_since_ath and days_since_ath > 0 else None
    fear_avg_since_ath = round(sum(fear_history) / len(fear_history), 1) if fear_history and len(fear_history) > 0 else None
    fear_min_since_ath = min(fear_history) if fear_history else None

    # 最近7/15/30/180/365天恐慌贪婪均值：各自天数之和/天数，保留整数
    fear_7d = _fetch_fear_greed_history(7)
    fear_avg_7d = int(sum(fear_7d) / 7) if fear_7d and len(fear_7d) > 0 else None
    fear_15d = _fetch_fear_greed_history(15)
    fear_avg_15d = int(sum(fear_15d) / 15) if fear_15d and len(fear_15d) > 0 else None
    fear_30d = _fetch_fear_greed_history(30)
    fear_avg_30d = int(sum(fear_30d) / 30) if fear_30d and len(fear_30d) > 0 else None
    fear_180d = _fetch_fear_greed_history(180)
    fear_avg_180d = int(sum(fear_180d) / len(fear_180d)) if fear_180d and len(fear_180d) > 0 else None
    fear_365d = _fetch_fear_greed_history(365)
    fear_avg_365d = int(sum(fear_365d) / len(fear_365d)) if fear_365d and len(fear_365d) > 0 else None

    # 200WMA、AHR999（支持字符串数值；若为空则报表阶段再拉一次）
    wma200 = metrics.get("btc_200wma_usd")
    ahr999 = metrics.get("ahr999")
    if wma200 is not None:
        try:
            wma200 = float(wma200) if isinstance(wma200, str) else (float(wma200) if isinstance(wma200, (int, float)) else None)
        except (TypeError, ValueError):
            wma200 = None
    if ahr999 is not None:
        try:
            ahr999 = float(ahr999) if isinstance(ahr999, str) else (float(ahr999) if isinstance(ahr999, (int, float)) else None)
        except (TypeError, ValueError):
            ahr999 = None
    if wma200 is None:
        wma200 = _fetch_btc_200wma()
    source_ahr999 = metrics.get("source_ahr999") or None
    if ahr999 is None:
        ahr999_data = _fetch_ahr999()
        if ahr999_data and "ahr999" in ahr999_data:
            ahr999 = ahr999_data["ahr999"]
            source_ahr999 = ahr999_data.get("source", "未知")

    # 下次产量减半时间
    current_block = metrics.get("current_block")
    if isinstance(current_block, str):
        try:
            current_block = int(current_block.replace(",", ""))
        except ValueError:
            current_block = None
    next_halving = _next_halving_datetime(current_block)

    # 关机价：优先 fuckbtc 矿机详情表全部关机价平均，再 DOM/正则、Braiins、公式估算（均带来源标注）
    shutdown_price = None
    shutdown_price_source = None
    avg_miners = metrics.get("shutdown_price_avg_miners")
    if avg_miners is not None:
        shutdown_price = str(int(avg_miners)) + " (矿机详情平均)"
        shutdown_price_source = "矿机详情平均"
    if not shutdown_price:
        shutdown_price = metrics.get("shutdown_price_range") or metrics.get("shutdown_price_usd")
        if isinstance(shutdown_price, (int, float)):
            shutdown_price = str(shutdown_price)
        if shutdown_price:
            shutdown_price_source = "fuckbtc页面"
    if not shutdown_price:
        braiins_price = _fetch_shutdown_price_from_braiins()
        if braiins_price:
            shutdown_price = "{} (Braiins)".format(braiins_price)
            shutdown_price_source = "Braiins"
    if not shutdown_price:
        estimated = _compute_shutdown_price_estimate(metrics)
        if estimated:
            shutdown_price = "{} (估算 25J/TH)".format(estimated)
            shutdown_price_source = "估算"

    # CBBI（Colin Talks Crypto 牛熊指数），来自 handle_cbbi
    cbbi = None
    try:
        from api_list.handle_CBBI import get_cbbi
        res = get_cbbi()
        if res.get("success") and res.get("cbbi") is not None:
            cbbi = res["cbbi"]
    except Exception:
        pass

    # 成交量比：30 天成交均量/365 天成交均量（优先用 data/cache/btc_cache 缓存）
    volume_ratio_max = None
    try:
        from utils.crypto.btc_volume_cache import get_btc_volume_ratio
        volume_ratio_max = get_btc_volume_ratio()
    except Exception:
        pass

    # MVRV（链上估值，底部参考；looknode/handle_mvrv_api）
    mvrv_val = None
    try:
        from api_list.handle_MVRV import get_today_data
        today_mvrv = get_today_data()
        mvrv_val = today_mvrv.get("MVRV") if today_mvrv else None
    except Exception:
        pass
    # NUPL（净未实现盈亏，底部参考；CoinGlass/CryptoQuant）
    nupl_val = None
    source_nupl = None
    try:
        from api_list.handle_NUPL import get_nupl
        res = get_nupl()
        if res.get("success") and res.get("nupl") is not None:
            nupl_val = res["nupl"]
            source_nupl = res.get("source")
    except Exception:
        pass

    # Supply in Profit（盈利供应占比 %，底部参考；<50% 历史大底、55%～65% 熊市中期；Look Into Bitcoin）
    supply_in_profit_val = None
    try:
        from api_list.handle_LookIntoBitcoin import get_supply_in_profit
        res = get_supply_in_profit()
        if res.get("success") and res.get("value") is not None:
            supply_in_profit_val = res["value"]
    except Exception:
        pass

    # CVDD（累计价值币天销毁，底部参考；价格接近或低于 CVDD 支撑常为周期底；handle_cvdd）
    cvdd_val = None
    try:
        from api_list.handle_CVDD import get_cvdd
        res = get_cvdd()
        if res.get("success") and res.get("cvdd") is not None:
            cvdd_val = res["cvdd"]
    except Exception:
        pass

    # SOPR Z-Score（On-chain Zscore 复合指标；底部 < -0.44，顶部 > 0.73；handle_SOPR_Z-Score）
    sopr_zscore_val = None
    sopr_zscore_message = None
    try:
        import importlib.util
        _sopr_path = os.path.join(os.path.dirname(__file__), "handle_SOPR_Z-Score.py")
        if os.path.isfile(_sopr_path):
            _spec = importlib.util.spec_from_file_location("handle_sopr_zscore_mod", _sopr_path)
            _mod = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            res = _mod.get_sopr_zscore()
            if res.get("success") and res.get("sopr_zscore") is not None:
                sopr_zscore_val = res["sopr_zscore"]
                sopr_zscore_message = res.get("message") or ""
    except Exception:
        pass

    return {
        "today_price_usd": today_price,
        "ath_price_usd": ath_price,
        "drop_pct_from_ath": drop_pct,
        "days_since_ath": days_since_ath,
        "fear_greed_today": fear_today,
        "fear_greed_avg_since_ath": fear_avg_since_ath,
        "fear_greed_min_since_ath": fear_min_since_ath,
        "fear_greed_avg_7d": fear_avg_7d,
        "fear_greed_avg_15d": fear_avg_15d,
        "fear_greed_avg_30d": fear_avg_30d,
        "fear_greed_avg_180d": fear_avg_180d,
        "fear_greed_avg_365d": fear_avg_365d,
        "btc_200wma_usd": wma200,
        "ahr999": ahr999,
        "source_ahr999": source_ahr999,
        "cbbi": cbbi,
        "volume_ratio_max": volume_ratio_max,
        "mvrv": mvrv_val,
        "nupl": nupl_val,
        "source_nupl": source_nupl,
        "supply_in_profit": supply_in_profit_val,
        "cvdd": cvdd_val,
        "sopr_zscore": sopr_zscore_val,
        "sopr_zscore_message": sopr_zscore_message,
        "shutdown_price": shutdown_price,
        "shutdown_price_source": shutdown_price_source,
        "next_halving_time": next_halving,
        "ath_date": ath_date_str,
    }


def format_btc_report_for_dingtalk(report: Dict[str, Any]) -> str:
    """将 build_btc_report 结果格式化为钉钉可发送的文本。首行固定为【大饼每日数据报表】，其余行按文案长度从短到长排序。"""
    def _v(v, fmt=str):
        if v is None:
            return "—"
        return fmt(v) if fmt != str else str(v)

    def _num(v):
        if v is None:
            return "—"
        return f"{float(v):.0f}" if isinstance(v, (int, float)) else str(v)

    def _ahr999_fmt(v):
        if v is None:
            return "—"
        try:
            return "%.2f" % float(v)
        except (TypeError, ValueError):
            return str(v)

    def _fmt_15d_fear(r):
        v15 = r.get("fear_greed_avg_15d")
        v7 = r.get("fear_greed_avg_7d")
        base = "最近15天恐慌贪婪均值: {}".format(_v(v15))
        if v15 is not None and v7 is not None:
            if v15 > v7:
                return base + " 增加"
            if v15 < v7:
                return base + " 减少"
        return base

    # 首行固定，不参与排序
    title = "【大饼每日数据报表】"
    cbbi_val = report.get("cbbi")
    if cbbi_val is not None:
        cbbi_str = "{} 取整{}".format(cbbi_val, int(math.ceil(cbbi_val)))
    else:
        cbbi_str = "—"
    data_lines = [
        "今日价格: {} USD".format(_v(report.get("today_price_usd"), _num)),
        "历史最高价格: {} USD".format(_v(report.get("ath_price_usd"), _num)),
        "历史最高126199到现在跌幅: {}%".format(_v(report.get("drop_pct_from_ath"))),
        "历史最高126199到现在天数: {} 天".format(_v(report.get("days_since_ath"))),
        "今日恐慌贪婪数值: {}".format(_v(report.get("fear_greed_today"))),
        "最近7天恐慌贪婪均值: {}".format(_v(report.get("fear_greed_avg_7d"))),
        _fmt_15d_fear(report),
        "最近30天恐慌贪婪均值: {}".format(_v(report.get("fear_greed_avg_30d"))),
        "从历史最高126199到现在恐慌贪婪均值: {}".format(_v(report.get("fear_greed_avg_since_ath"))),
        "最低恐慌贪婪数值: {}".format(_v(report.get("fear_greed_min_since_ath"))),
        "200WMA数值: {} USD".format(_v(report.get("btc_200wma_usd"), _num)),
        "AHR999数值: {}".format(_ahr999_fmt(report.get("ahr999"))),
        "CBBI: {}".format(cbbi_str),
        "VOLUME_RATIO_MAX(30d/365d成交均量比): {}".format(_v(report.get("volume_ratio_max"), lambda x: "%.2f" % x if x is not None else "—")),
        "下次产量减半时间: {}".format(_v(report.get("next_halving_time"))),
        "SOPR Z-Score(链上Z值 底<-0.44 顶>0.73): {} {}".format(
            _v(report.get("sopr_zscore"), lambda x: "%.4f" % x if x is not None else "—"),
            _v(report.get("sopr_zscore_message")),
        ),
    ]
    # 文案从短到长排序（首行 title 不参与，拼接时放最前）
    data_lines.sort(key=len)
    # 最近30/180/365天恐慌贪婪均值固定放在 AHR999数值 上面，顺序为 30天 → 180天 → 365天
    line_30d = "最近30天恐慌贪婪均值: {}".format(_v(report.get("fear_greed_avg_30d")))
    line_180 = "最近180天恐慌贪婪均值: {}".format(_v(report.get("fear_greed_avg_180d")))
    line_365 = "最近365天恐慌贪婪均值: {}".format(_v(report.get("fear_greed_avg_365d")))
    data_lines = [ln for ln in data_lines if not ln.startswith("最近30天恐慌贪婪均值:") and not ln.startswith("最近180天恐慌贪婪均值:") and not ln.startswith("最近365天恐慌贪婪均值:")]
    for i, ln in enumerate(data_lines):
        if ln.startswith("AHR999数值:"):
            data_lines.insert(i, line_365)
            data_lines.insert(i, line_180)
            data_lines.insert(i, line_30d)
            break
    # 最近15天恐慌贪婪均值固定放在最近7天恐慌贪婪均值后面
    idx_7d = next((i for i, ln in enumerate(data_lines) if ln.startswith("最近7天恐慌贪婪均值:")), None)
    idx_15d = next((i for i, ln in enumerate(data_lines) if ln.startswith("最近15天恐慌贪婪均值:")), None)
    if idx_7d is not None and idx_15d is not None and idx_15d != idx_7d + 1:
        line_15d = data_lines.pop(idx_15d)
        insert_at = (idx_7d + 1) if idx_15d > idx_7d else idx_7d
        data_lines.insert(insert_at, line_15d)
    return "\n".join([title] + data_lines)


def run_btc_report_and_send_dingtalk(myself: Optional[str] = None, send: bool = True) -> Dict[str, Any]:
    """
    拉取数据 → 构建报表 → 可选发送钉钉。返回包含 success、report、message、dingtalk_sent 的字典。
    myself: 传 'alvin' / 'QA' 指定钉钉机器人，不传则用默认。
    send: 为 True 时发送钉钉；为 False 时只返回 message 文本不发送（供 runningAll 合并为一条消息）。
    """
    from utils.handle_ddmsg import send_ding_msgs

    result = {"success": False, "report": None, "message": None, "dingtalk_sent": False}
    try:
        data = get_fuckbtc_json()
        if not data.get("success"):
            result["message"] = data.get("error", "get_fuckbtc_json 未返回 success")
            return result
        metrics = data.get("metrics", {})
        report = build_btc_report(metrics)
        result["report"] = report
        result["success"] = True
        msg = format_btc_report_for_dingtalk(report)
        result["message"] = msg
        if send:
            send_ding_msgs(msg, myself=myself)
            result["dingtalk_sent"] = True
    except Exception as e:
        result["message"] = str(e)
    return result


def get_fuckbtc_json() -> Dict[str, Any]:
    """
    请求 fuckbtc.com 页面，解析内嵌 JSON 或 DOM，返回统一结构的字典。
    无需提供接口地址：会从页面源码自动发现 API URL，并用 Binance / mempool.space 补充实时数据。
    """
    time.sleep(random.uniform(1, 10))
    resp = requests.get(URL, headers=HEADERS, timeout=REQUEST_TIMEOUT, proxies=_get_proxies())
    resp.raise_for_status()
    html = resp.text

    out: Dict[str, Any] = {
        "success": True,
        "url": URL,
        "fetch_time": datetime.now().isoformat(),
        "embedded_data": None,
        "metrics": {},
        "miner_table": [],
        "consistency_note": "价格/区块/减半/算力与网页同源(Binance·mempool.space)；均衡价格需 Glassnode API_KEY；200WMA/恐惧贪婪/AHR999 已用免费接口(CoinGecko·Alternative.me·coinsoto)拉取；矿机表仅表头",
    }

    # 关机价：从 fuckbtc 页面 HTML 正则提取（DOM 未命中时的备用）
    _shutdown_from_html = _extract_shutdown_price_from_html(html)
    if _shutdown_from_html:
        out["metrics"]["shutdown_price_range"] = _shutdown_from_html

    # 公开数据源补充实时指标（Binance 价格、mempool 区块/算力）
    public_metrics = _fetch_public_apis()
    out["metrics"].update(public_metrics)

    # CoinGecko 免费中长线指标（市值、7d/30d/60d/200d/1y 涨跌幅、ATH/ATL、距高低点幅度）
    cg_btc = _fetch_coingecko_btc_indicators()
    if cg_btc:
        out["metrics"]["coingecko_btc"] = cg_btc

    # 200WMA：CoinGecko 历史价格自算（免费）
    btc_200wma = _fetch_btc_200wma()
    if btc_200wma is not None:
        out["metrics"]["btc_200wma_usd"] = btc_200wma
        out["metrics"]["source_200wma"] = "CoinGecko"

    # 恐惧贪婪指数：Alternative.me 免费
    fear_greed = _fetch_fear_greed()
    if fear_greed:
        out["metrics"]["fear_greed_index"] = fear_greed
        out["metrics"]["source_fear_greed"] = "Alternative.me"

    # AHR999：优先从外部站获取（coinsoto/soulbab/coinglass/handle），仅外部无有效值时再用 fuckbtc 页面解析
    ahr999_data = _fetch_ahr999()
    if ahr999_data and _is_valid_ahr999(ahr999_data.get("ahr999")):
        out["metrics"]["ahr999"] = ahr999_data["ahr999"]
        if ahr999_data.get("avg_200d_usd") is not None:
            out["metrics"]["ahr999_200d_avg_usd"] = ahr999_data["avg_200d_usd"]
        out["metrics"]["source_ahr999"] = ahr999_data.get("source", "coinsoto")
    else:
        ahr999_fuckbtc = _extract_ahr999_from_fuckbtc(html)
        if ahr999_fuckbtc is not None and _is_valid_ahr999(ahr999_fuckbtc):
            # fuckbtc 页面/数据有时为「显示值×10」（如页面 0.31 存成 3.1），统一按 ×0.1 与网站一致
            if ahr999_fuckbtc >= 1.0:
                ahr999_fuckbtc = round(ahr999_fuckbtc * 0.1, 4)
            out["metrics"]["ahr999"] = ahr999_fuckbtc
            out["metrics"]["source_ahr999"] = "fuckbtc.com"

    # 1) 优先使用 __NEXT_DATA__
    next_data = _extract_next_data(html)
    if next_data:
        out["embedded_data"] = next_data
        props = next_data.get("props", {})
        page_props = props.get("pageProps", {})
        if page_props and isinstance(page_props, dict):
            out["metrics"].update({k: v for k, v in page_props.items() if not str(k).startswith("_")})
        # 矿机详情表从 DOM 解析（next 分支未走 DOM），取全部关机价平均
        soup = BeautifulSoup(html, "html.parser")
        dom_metrics = _parse_dom_metrics(soup)
        out["miner_table"] = dom_metrics.get("miner_table", [])
        avg_shutdown = _avg_shutdown_from_miner_table(out["miner_table"])
        if avg_shutdown is not None:
            out["metrics"]["shutdown_price_avg_miners"] = avg_shutdown
        out["metrics_labels"] = _build_metrics_labels(out["metrics"])
        return out

    # 2) 其它内嵌 JSON
    other_json = _extract_script_json(html)
    if other_json and isinstance(other_json, dict):
        out["embedded_data"] = other_json
        out["metrics"].update({k: v for k, v in other_json.items() if not str(k).startswith("_")})
        soup = BeautifulSoup(html, "html.parser")
        dom_metrics = _parse_dom_metrics(soup)
        out["miner_table"] = dom_metrics.get("miner_table", [])
        avg_shutdown = _avg_shutdown_from_miner_table(out["miner_table"])
        if avg_shutdown is not None:
            out["metrics"]["shutdown_price_avg_miners"] = avg_shutdown
        out["metrics_labels"] = _build_metrics_labels(out["metrics"])
        return out

    # 3) DOM 解析补充：仅当公开 API 未提供该键、且 DOM 值为「像数值」时才写入，避免用标签覆盖真实数据
    soup = BeautifulSoup(html, "html.parser")
    dom_metrics = _parse_dom_metrics(soup)
    for k, v in dom_metrics.items():
        if k in ("fetch_time", "source", "miner_table"):
            continue
        if v is None:
            continue
        if out["metrics"].get(k) is not None:
            continue  # 已有值（如来自 Binance/mempool）不覆盖
        if isinstance(v, str) and not _looks_like_metric_value(v):
            continue  # 再次过滤标签/长描述
        out["metrics"][k] = v
    out["metrics"]["fetch_time"] = dom_metrics["fetch_time"]
    out["miner_table"] = dom_metrics.get("miner_table", [])
    # 矿机详情表全部关机价取平均
    avg_shutdown = _avg_shutdown_from_miner_table(out["miner_table"])
    if avg_shutdown is not None:
        out["metrics"]["shutdown_price_avg_miners"] = avg_shutdown
    out["metrics_labels"] = _build_metrics_labels(out["metrics"])
    return out


def main():
    """请求页面并打印 JSON；若带 --report 或 --dingtalk 则生成报表并发送钉钉。"""
    if "--report" in sys.argv or "--dingtalk" in sys.argv:
        myself = "alvin" if "--alvin" in sys.argv else ("QA" if "--qa" in sys.argv else None)
        r = run_btc_report_and_send_dingtalk(myself=myself)
        print(json.dumps({"success": r["success"], "dingtalk_sent": r["dingtalk_sent"], "message": r["message"]}, ensure_ascii=False, indent=2))
        if r.get("report"):
            print("\n报表数据:\n" + json.dumps(r["report"], ensure_ascii=False, indent=2))
        return r

    try:
        data = get_fuckbtc_json()
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return data
    except requests.RequestException as e:
        result = {"success": False, "error": str(e), "url": URL}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result


if __name__ == "__main__":
    main()
