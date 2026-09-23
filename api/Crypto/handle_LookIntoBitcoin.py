# -*- coding: utf-8 -*-
"""
Look Into Bitcoin 爬虫：获取 NUPL、Supply in Profit、CVDD 最新值。
数据来源：https://www.lookintobitcoin.com/charts/

注意：production.lookintobitcoin.com 已废弃（502），现为 Bitcoin Magazine Pro。
- 旧免费接口（已不可用）：https://production.lookintobitcoin.com/api/nupl
- 新 API（需 Pro 订阅）：https://api.bitcoinmagazinepro.com/metrics/nupl
  在 config.ini [bmpro] API_KEY 配置后，handle_NUPL 会通过 BM Pro 获取。
"""
import os
import sys
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import requests

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from utils.operationConfig import OperationConfig

BASE_URL = "https://production.lookintobitcoin.com/api"
ENDPOINTS = {
    "nupl": f"{BASE_URL}/nupl",
    "supply_in_profit": f"{BASE_URL}/supply-in-profit",
    "cvdd": f"{BASE_URL}/cvdd",
}
REQUEST_TIMEOUT = 20
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://www.lookintobitcoin.com/",
}


def _get_proxies() -> Dict[str, str]:
    """从 config [proxy] 读取代理；未启用时返回 {}。"""
    p = OperationConfig().get_proxy_config()
    return p if p else {}


def _log_proxy_usage(proxies: Dict[str, str], retry_direct: bool = False) -> None:
    """若使用代理则打印提示；retry_direct 为 True 时表示因 SSL 错误正在重试直连。"""
    if retry_direct:
        print("[LookIntoBitcoin] 代理请求出现 SSL 错误，正在重试直连...")
        return
    if proxies:
        https_proxy = proxies.get("https") or proxies.get("http") or ""
        print(f"[LookIntoBitcoin] 使用代理: {https_proxy}")


def _is_ssl_related_error(e: Exception) -> bool:
    """判断是否为 SSL 相关错误（含被包装的 SSLEOFError 等）。"""
    msg = str(e).lower()
    if "ssl" in msg or "eof" in msg or "unexpected_eof" in msg:
        return True
    cause = getattr(e, "__cause__", None)
    if cause and _is_ssl_related_error(cause):
        return True
    return False


# 仅首次使用代理时打印一次
_proxy_usage_logged: bool = False


def _fetch_series(url: str) -> Tuple[Optional[float], Optional[str], str]:
    """
    请求 Look Into Bitcoin 某指标接口，解析最新数值。
    优先使用 config.ini [proxy] 代理；若出现 SSL 错误则自动重试直连。
    返回 (value, date_str, error_msg)。成功时 error_msg 为空。
    常见返回：{"data": [[timestamp_ms, value], ...]} 或 {"data": [[date_str, value], ...]}
    """
    global _proxy_usage_logged
    proxies = _get_proxies() or {}
    if proxies and not _proxy_usage_logged:
        _log_proxy_usage(proxies)
        _proxy_usage_logged = True
    try:
        r = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            proxies=proxies,
        )
        r.raise_for_status()
        raw = r.json()
    except (requests.exceptions.SSLError, requests.exceptions.RequestException) as e:
        # 代理 HTTPS 拦截常导致 SSL EOF（有时被包在 ConnectionError 里），重试一次直连
        if proxies and _is_ssl_related_error(e):
            _log_proxy_usage(proxies, retry_direct=True)
            try:
                r = requests.get(
                    url,
                    headers=HEADERS,
                    timeout=REQUEST_TIMEOUT,
                    proxies={},
                )
                r.raise_for_status()
                raw = r.json()
            except requests.exceptions.RequestException as e2:
                return None, None, str(e2)
        else:
            return None, None, str(e)
    except Exception as e:
        return None, None, f"解析异常: {e}"

    data = raw.get("data") if isinstance(raw, dict) else raw
    if not data or not isinstance(data, (list, tuple)):
        return None, None, "返回无 data 或格式异常"

    # 取最后一条
    last = data[-1]
    # 格式1: [[ts, val], ...] 或 [["date", val], ...]
    if isinstance(last, (list, tuple)) and len(last) >= 2:
        try:
            val = float(last[1])
        except (TypeError, ValueError):
            return None, None, "数值无法转为 float"
        date_part = last[0]
        if isinstance(date_part, (int, float)):
            try:
                date_str = datetime.utcfromtimestamp(date_part / 1000.0).strftime("%Y-%m-%d")
            except Exception:
                date_str = str(date_part)
        else:
            date_str = str(date_part)
        return val, date_str, ""
    # 格式2: [{"t": ts, "v": value}, ...]
    if isinstance(last, dict):
        v = last.get("v") or last.get("value") or last.get("y")
        t = last.get("t") or last.get("date") or last.get("x")
        if v is not None:
            try:
                val = float(v)
                date_str = str(t) if t is not None else ""
                if isinstance(t, (int, float)):
                    try:
                        ts_sec = t / 1000.0 if t > 1e12 else t
                        date_str = datetime.utcfromtimestamp(ts_sec).strftime("%Y-%m-%d")
                    except Exception:
                        pass
                return val, date_str, ""
            except (TypeError, ValueError):
                pass
    return None, None, "data 格式无法解析"


def get_nupl() -> Dict[str, Any]:
    """获取 NUPL 最新值。返回 {"value": float|None, "date": str|None, "success": bool, "source": str}。"""
    value, date_str, err = _fetch_series(ENDPOINTS["nupl"])
    if value is not None:
        return {
            "value": round(value, 4),
            "date": date_str,
            "success": True,
            "source": "Look Into Bitcoin",
        }
    return {
        "value": None,
        "date": None,
        "success": False,
        "source": f"Look Into Bitcoin: {err}" if err else "Look Into Bitcoin 请求失败",
    }


def get_supply_in_profit() -> Dict[str, Any]:
    """获取 Supply in Profit（盈利供应占比 %）最新值。返回 {"value": float|None, "date": str|None, "success": bool, "source": str}。"""
    value, date_str, err = _fetch_series(ENDPOINTS["supply_in_profit"])
    if value is not None:
        return {
            "value": round(value, 2),
            "date": date_str,
            "success": True,
            "source": "Look Into Bitcoin",
        }
    return {
        "value": None,
        "date": None,
        "success": False,
        "source": f"Look Into Bitcoin: {err}" if err else "Look Into Bitcoin 请求失败",
    }


def get_cvdd() -> Dict[str, Any]:
    """获取 CVDD 最新值。返回 {"value": float|None, "date": str|None, "success": bool, "source": str}。"""
    value, date_str, err = _fetch_series(ENDPOINTS["cvdd"])
    if value is not None:
        return {
            "value": round(value, 2),
            "date": date_str,
            "success": True,
            "source": "Look Into Bitcoin",
        }
    return {
        "value": None,
        "date": None,
        "success": False,
        "source": f"Look Into Bitcoin: {err}" if err else "Look Into Bitcoin 请求失败",
    }


def get_latest_all() -> Dict[str, Dict[str, Any]]:
    """一次性获取 NUPL、Supply in Profit、CVDD 三个指标的最新结果。"""
    return {
        "nupl": get_nupl(),
        "supply_in_profit": get_supply_in_profit(),
        "cvdd": get_cvdd(),
    }


if __name__ == "__main__":
    all_result = get_latest_all()
    for name, res in all_result.items():
        print(f"{name}: value={res.get('value')}, date={res.get('date')}, success={res.get('success')}, source={res.get('source')}")
