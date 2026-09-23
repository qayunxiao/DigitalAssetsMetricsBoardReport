# -*- coding: utf-8 -*-
"""
从 https://colintalkscrypto.com/cbbi/index.html 或数据接口获取 CBBI（Colin Talks Crypto Bitcoin Bull Run Index）数值。
返回当前信心分数，约 0–100。需代理时使用 _get_proxies。

数据来源与小数/整数说明：
- 数值来自官网数据（latest.json 的 Confidence），不是 mock 假数据。
- 原始为 0–1，乘 100 后可得小数（如 38.3）。页面通常显示为整数：
  38.3 四舍五入到整数 = 38；若页面显示 39，多为四舍五入时取到了 38.5+，或站点用向上取整。
- 本模块默认返回一位小数（38.3）；若需与页面一致可传 round_to_int=True 得到 38 或 39。
"""
import math
import os
import random
import re
import sys
import time
from typing import Any, Dict, Optional

import requests

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from utils.operationConfig import OperationConfig

URL_CBBI_PAGE = "https://colintalkscrypto.com/cbbi/index.html"
URL_CBBI_API = "https://colintalkscrypto.com/api/cbbi"
# 官网数据文件：与页面同源，含 Price、各指标及 Confidence（时间戳→数值），取 Confidence 最新值即当前 CBBI
URL_CBBI_LATEST_JSON = "https://colintalkscrypto.com/cbbi/data/latest.json"
REQUEST_TIMEOUT = 20
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def _get_proxies() -> Dict[str, str]:
    """从 config.ini [proxy] 读取代理；Linux 或未启用时返回 {} 直连。"""
    p = OperationConfig().get_proxy_config()
    return p if p else {}


def _fetch_latest_json() -> Optional[Dict[str, Any]]:
    """请求 cbbi/data/latest.json，返回完整 JSON；失败返回 None。"""
    try:
        r = requests.get(
            URL_CBBI_LATEST_JSON,
            headers={**HEADERS, "Accept": "application/json"},
            timeout=REQUEST_TIMEOUT,
            proxies=_get_proxies() or {},
        )
        if not r.ok:
            return None
        return r.json()
    except Exception:
        return None


def _parse_cbbi_from_latest_json(data: Optional[Dict], *, as_integer: bool = False) -> Optional[float]:
    """
    从 latest.json 解析当前 CBBI。结构为各列名 -> { 时间戳: 数值 }；
    Confidence 列为 9 个指标均值，数值多为 0–1，取最新时间戳对应的值，若 < 1 则乘 100 得到 0–100 分。
    as_integer=True 时四舍五入为整数，与页面展示一致（如 38.3→38，38.6→39）。
    """
    if not data or not isinstance(data, dict):
        return None
    confidence = data.get("Confidence")
    if not isinstance(confidence, dict):
        return None
    # 时间戳为字符串 key，取最大时间戳即最新
    try:
        ts_keys = [int(k) for k in confidence if k.strip().isdigit()]
    except (ValueError, TypeError):
        return None
    if not ts_keys:
        return None
    latest_ts = str(max(ts_keys))
    val = confidence.get(latest_ts)
    if val is None:
        return None
    try:
        v = float(val)
    except (TypeError, ValueError):
        return None
    if v < 0:
        return None
    if 0 <= v <= 1:
        v = v * 100
    if not (0 <= v <= 100):
        return None
    return float(round(v, 0)) if as_integer else round(v, 1)


def _fetch_cbbi_api() -> Optional[Dict[str, Any]]:
    """请求 CBBI 官方 API，返回 JSON；失败返回 None。"""
    try:
        r = requests.get(
            URL_CBBI_API,
            headers={**HEADERS, "Accept": "application/json"},
            timeout=REQUEST_TIMEOUT,
            proxies=_get_proxies() or {},
        )
        if not r.ok:
            return None
        return r.json()
    except Exception:
        return None


def _parse_cbbi_from_api(data: Optional[Dict]) -> Optional[float]:
    """从 API 返回的 JSON 中解析 CBBI 数值（0–100）。"""
    if not data or not isinstance(data, dict):
        return None
    # 常见字段名
    for key in ("current", "value", "cbbi", "score", "confidence"):
        v = data.get(key)
        if v is not None and isinstance(v, (int, float)):
            return float(v)
    # 嵌套结构
    if isinstance(data.get("data"), dict):
        return _parse_cbbi_from_api(data["data"])
    return None


def _parse_cbbi_from_html(html: str) -> Optional[float]:
    """从 CBBI 页面 HTML 中解析当前 CBBI 数值（0–100）。"""
    if not html or len(html) < 50:
        return None
    # 1) 页面中 “CONFIDENCE WE ARE AT THE PEAK” 后紧跟的数字
    m = re.search(
        r"CONFIDENCE\s+WE\s+ARE\s+AT\s+THE\s+PEAK[^0-9]*?(\d{1,3})",
        html,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        v = float(m.group(1))
        if 0 <= v <= 100:
            return v
    # 2) 内联 script 中的数值（如 window.__INITIAL__ = { score: 39 }）
    m = re.search(
        r"(?:cbbi|score|confidence|value)\s*[=:]\s*(\d{1,3}(?:\.\d+)?)",
        html,
        re.IGNORECASE,
    )
    if m:
        v = float(m.group(1))
        if 0 <= v <= 100:
            return v
    return None


def get_cbbi(round_to_int: bool = False) -> Dict[str, Any]:
    """
    获取 CBBI 数值：优先 latest.json（Confidence 最新值），否则 API，再否则解析 index 页面 HTML。
    round_to_int: 为 True 时四舍五入为整数，与页面展示一致（默认 False 保留一位小数，如 38.3）。
    返回 {"cbbi": 38.3|39, "success": True, "source": "latest_json|api|html"} 或 {"cbbi": None, "success": False, "source": None}。
    """
    time.sleep(random.uniform(1, 10))
    result = {"cbbi": None, "success": False, "source": None}
    # 1) 优先 cbbi/data/latest.json（与页面同源，含 Confidence 时间序列）
    latest_data = _fetch_latest_json()
    value = _parse_cbbi_from_latest_json(latest_data, as_integer=round_to_int)
    if value is not None:
        result["cbbi"] = value
        result["success"] = True
        result["source"] = "latest_json"
        return result
    # 2) 再试 API
    api_data = _fetch_cbbi_api()
    value = _parse_cbbi_from_api(api_data)
    if value is not None:
        result["cbbi"] = float(round(value, 0)) if round_to_int else value
        result["success"] = True
        result["source"] = "api"
        return result
    # 3) 再试页面
    try:
        r = requests.get(
            URL_CBBI_PAGE,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            proxies=_get_proxies() or {},
        )
        if r.ok:
            value = _parse_cbbi_from_html(r.text)
            if value is not None:
                result["cbbi"] = float(round(value, 0)) if round_to_int else value
                result["success"] = True
                result["source"] = "html"
    except Exception:
        pass
    return result


if __name__ == "__main__":
    res = get_cbbi()
    cbbi = res.get("cbbi")
    if cbbi is not None:
        print("CBBI: {} 取整{}".format(cbbi, int(math.ceil(cbbi))))
    else:
        print("CBBI:", cbbi)
    print("success:", res.get("success"))
    print("source:", res.get("source"))
