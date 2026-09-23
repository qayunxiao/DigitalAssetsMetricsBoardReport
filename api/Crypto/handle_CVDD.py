# -*- coding: utf-8 -*-
"""
获取最新 CVDD（Cumulative Value Coin Days Destroyed）。
- 优先：Bitcoin Magazine Pro API（需 config.ini [bmpro] API_KEY）。
- 免费回退：Looknode 直接 API https://www.looknode.com/api/CVDD（JSON），
  失败再解析图表页 https://www.looknode.com/charts?chartId=CVDD 内嵌数据。

CVDD = 累计价值币天销毁，由 @woonomic 提出，历史上对 BTC 周期底部有较好指示。
"""
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Union

import requests

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from utils.operationConfig import OperationConfig

# BM Pro API：CVDD 指标名为 cvdd，见 https://www.bitcoinmagazinepro.com/api/docs/
URL_BMPRO_METRICS_CVDD = "https://api.bitcoinmagazinepro.com/metrics/cvdd"
# Looknode 免费：直接 API 返回 JSON {"code":100,"data":[{"t":ts,"v":val},...]}
URL_LOOKNODE_API_CVDD = "https://www.looknode.com/api/CVDD"
# Looknode 图表页（备用：从页面内嵌数据解析）
URL_LOOKNODE_CVDD = "https://www.looknode.com/charts?chartId=CVDD"
REQUEST_TIMEOUT = 25
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/csv, text/plain;q=0.9",
}
HEADERS_HTML = {
    **HEADERS,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _get_proxies() -> Dict[str, str]:
    """从 config [proxy] 读取代理；Linux 或未启用时返回 {} 直连。"""
    p = OperationConfig().get_proxy_config()
    return p if p else {}


def _parse_latest_value_from_csv(text: str) -> Optional[float]:
    """从 CSV 文本解析最后一行最后一个数值（视为最新 CVDD）。"""
    if not text or not text.strip():
        return None
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if not lines:
        return None
    last_line = lines[-1]
    parts = [p.strip() for p in last_line.split(",")]
    for i in range(len(parts) - 1, -1, -1):
        try:
            return float(parts[i].replace(" ", "").replace('"', ""))
        except (ValueError, TypeError):
            continue
    return None


def _parse_latest_value_from_json(data: Union[dict, list]) -> Optional[float]:
    """从 API JSON 解析最新 CVDD 数值。支持多种常见结构。"""
    if data is None:
        return None
    if isinstance(data, list):
        if not data:
            return None
        last = data[-1]
        if isinstance(last, (int, float)):
            return float(last)
        if isinstance(last, (list, tuple)) and len(last) >= 2:
            try:
                return float(last[-1])
            except (TypeError, ValueError):
                pass
        if isinstance(last, dict):
            for k in ("value", "cvdd", "y", "v", "close"):
                if k in last and last[k] is not None:
                    try:
                        return float(last[k])
                    except (TypeError, ValueError):
                        pass
        return None
    if isinstance(data, dict):
        if "value" in data and data["value"] is not None:
            try:
                return float(data["value"])
            except (TypeError, ValueError):
                pass
        if "data" in data:
            return _parse_latest_value_from_json(data["data"])
        if "values" in data:
            return _parse_latest_value_from_json(data["values"])
        if "series" in data:
            return _parse_latest_value_from_json(data["series"])
    return None


def _extract_latest_from_timeseries_candidates(obj: Any, candidates: List[float]) -> None:
    """
    递归遍历 JSON，寻找形如 [[ts, val], ...] 的序列，将最后一个 val 加入 candidates。
    CVDD 数值量级约在数千到数万，只收集看起来像价格的数值（避免误取百分比等）。
    """
    if isinstance(obj, list):
        if len(obj) > 10 and isinstance(obj[0], (list, tuple)) and len(obj[0]) >= 2:
            try:
                last = obj[-1]
                if isinstance(last, (list, tuple)) and len(last) >= 2:
                    v = last[-1] if len(last) > 1 else last[0]
                    if isinstance(v, (int, float)) and 100 < abs(v) < 1e10:
                        candidates.append(float(v))
            except (IndexError, TypeError, ValueError):
                pass
        for item in obj:
            _extract_latest_from_timeseries_candidates(item, candidates)
    elif isinstance(obj, dict):
        for v in obj.values():
            _extract_latest_from_timeseries_candidates(v, candidates)


def _fetch_cvdd_from_looknode_api() -> Optional[float]:
    """
    从 Looknode 直接 API 获取 CVDD 最新数值（免费）。
    GET https://www.looknode.com/api/CVDD 返回 {"code":100,"data":[{"t":ts,"v":val},...]}。
    """
    try:
        r = requests.get(
            URL_LOOKNODE_API_CVDD,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            proxies=_get_proxies() or {},
        )
        if not r.ok:
            return None
        data = r.json()
        if not isinstance(data, dict) or data.get("code") != 100:
            return None
        arr = data.get("data")
        if not isinstance(arr, list) or len(arr) == 0:
            return None
        last = arr[-1]
        if isinstance(last, dict) and "v" in last:
            try:
                return float(last["v"])
            except (TypeError, ValueError):
                pass
        return None
    except Exception:
        return None


def _fetch_cvdd_from_looknode() -> Optional[float]:
    """
    从 Looknode 获取最新 CVDD：先请求直接 API，失败再解析图表页 HTML。
    """
    val = _fetch_cvdd_from_looknode_api()
    if val is not None:
        return val
    # 备用：从图表页 HTML 解析
    try:
        r = requests.get(
            URL_LOOKNODE_CVDD,
            headers=HEADERS_HTML,
            timeout=REQUEST_TIMEOUT,
            proxies=_get_proxies() or {},
        )
        if not r.ok:
            return None
        html = r.text
        # Next.js 内嵌数据：定位 __NEXT_DATA__ 后取完整 JSON 对象（括号匹配）
        idx = html.find('id="__NEXT_DATA__"')
        if idx != -1:
            start_brace = html.find("{", idx)
            if start_brace != -1:
                depth = 0
                for i in range(start_brace, len(html)):
                    if html[i] == "{":
                        depth += 1
                    elif html[i] == "}":
                        depth -= 1
                        if depth == 0:
                            try:
                                data = json.loads(html[start_brace : i + 1])
                                candidates: List[float] = []
                                _extract_latest_from_timeseries_candidates(data, candidates)
                                if candidates:
                                    return candidates[-1]
                            except json.JSONDecodeError:
                                pass
                            break
        # 备用：查找任意 script 中的 JSON，含 data/series 数组
        for blob in re.findall(r'<script[^>]*type="application/json"[^>]*>\s*(\{.*?\})\s*</script>', html, re.DOTALL):
            try:
                data = json.loads(blob)
                val = _parse_latest_value_from_json(data)
                if val is not None and 100 < abs(val) < 1e10:
                    return val
            except (json.JSONDecodeError, TypeError):
                continue
        return None
    except Exception:
        return None


def _fetch_cvdd_from_bmpro(api_key: str) -> Optional[float]:
    """
    请求 Bitcoin Magazine Pro API 获取 CVDD 数据，解析最新值。
    API: GET https://api.bitcoinmagazinepro.com/metrics/cvdd
    Auth: Authorization: Bearer {api_key}
    """
    if not api_key:
        return None
    try:
        r = requests.get(
            URL_BMPRO_METRICS_CVDD,
            headers={
                **HEADERS,
                "Authorization": "Bearer {}".format(api_key),
            },
            timeout=REQUEST_TIMEOUT,
            proxies=_get_proxies() or {},
        )
        if not r.ok:
            return None
        ct = (r.headers.get("Content-Type") or "").lower()
        if "json" in ct:
            val = _parse_latest_value_from_json(r.json())
            if val is not None:
                return val
        val = _parse_latest_value_from_csv(r.text)
        if val is not None:
            return val
        try:
            val = _parse_latest_value_from_json(r.json())
            return val
        except Exception:
            pass
        return None
    except Exception:
        return None


def get_cvdd() -> Dict[str, Any]:
    """
    获取最新 CVDD 数值。优先 Bitcoin Magazine Pro API（需 [bmpro] API_KEY），
    未配置或失败时使用 Looknode 免费图表页数据。
    返回 {"cvdd": float|None, "success": bool, "source": str}。
    """
    result = {"cvdd": None, "success": False, "source": None}
    api_key = OperationConfig().get_bmpro_api_key()
    if api_key:
        value = _fetch_cvdd_from_bmpro(api_key)
        if value is not None:
            result["cvdd"] = round(value, 2)
            result["success"] = True
            result["source"] = "Bitcoin Magazine Pro API"
            return result
    # 无 key 或 BM Pro 失败时使用 Looknode 免费源
    value = _fetch_cvdd_from_looknode()
    if value is not None:
        result["cvdd"] = round(value, 2)
        result["success"] = True
        result["source"] = "Looknode (free)"
    else:
        result["source"] = (
            "未配置 [bmpro] API_KEY 且 Looknode 解析失败"
            if not api_key
            else "Bitcoin Magazine Pro 与 Looknode 均失败"
        )
    return result


if __name__ == "__main__":
    res = get_cvdd()
    print("CVDD:", res.get("cvdd"))
    print("success:", res.get("success"))
    print("source:", res.get("source"))
