# -*- coding: utf-8 -*-
# -------------------------
# @Time    :  2026/2/13 13:39
# @Author  : alvin
# @Description:  使用免费数据源获取 SOPR Z-Score（On-chain Zscore 复合指标）
# -------------------------
"""
SOPR Z-Score（On-chain Zscore | QuantumResearch）
📊 指标解读
项目	内容
指标名称	On-chain Zscore | QuantumResearch（复合指标）
核心逻辑	SOPR + MVRV + NUPL 分别计算Z-Score后平均
底部阈值	< -0.44（历史底部信号）
顶部阈值	> 0.73（历史顶部信号）
数据频率	日线

detail["mvrv_z"]、detail["sopr_z"]、detail["nupl_z"] 分别是三个分量

🆓 免费数据源（本实现）
- Bitbo API：MVRV Z-Score、SOPR 日线序列（无 Key）https://bitbo.io/api/docs/
- Looknode API：MVRV 日线 → 推算 NUPL 序列（无 Key）https://www.looknode.com/api/mCapRealizedRatio
- 回退：Bitbo MVRV Z-Score 图表页解析（API 失败时）
"""
import math
import os
import re
import sys
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from utils.operationConfig import OperationConfig

# Bitbo 免费 API（无需 Key）
URL_BITBO_MVRV_Z = "https://charts.bitbo.io/api/v1/mvrv-z/"
URL_BITBO_SOPR = "https://charts.bitbo.io/api/v1/sopr/"
# Bitbo 图表页（API 失败时尝试从页面解析最新值）
URL_BITBO_MVRV_Z_PAGE = "https://charts.bitbo.io/mvrv-z-score/"
# Looknode 免费：MVRV → NUPL = 1 - 1/MVRV
URL_LOOKNODE_MVRV = "https://www.looknode.com/api/mCapRealizedRatio"

# 数据源 URL/API 地址（供输出或文档使用）
DATA_SOURCE_URLS = {
    "Bitbo MVRV Z-Score API": URL_BITBO_MVRV_Z,
    "Bitbo SOPR API": URL_BITBO_SOPR,
    "Bitbo MVRV Z-Score 图表页": URL_BITBO_MVRV_Z_PAGE,
    "Looknode MVRV API": URL_LOOKNODE_MVRV,
}

REQUEST_TIMEOUT = 25
Z_SCORE_WINDOW_DAYS = 365  # 用于计算 SOPR/NUPL Z-Score 的滚动窗口（天）
# 阈值：底部 < BOTTOM_THRESHOLD，顶部 > TOP_THRESHOLD
BOTTOM_THRESHOLD = -0.44
TOP_THRESHOLD = 0.73

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}
HEADERS_HTML = {
    **HEADERS,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _get_proxies() -> Dict[str, str]:
    """从 config [proxy] 读取代理；未启用时返回 {} 直连。"""
    p = OperationConfig().get_proxy_config()
    return p if p else {}


def _z_score_from_series(values: List[float]) -> Optional[float]:
    """根据序列计算最后一个值的 Z-Score：(last - mean) / std。至少需要 2 个点。"""
    if not values or len(values) < 2:
        return None
    last = values[-1]
    n = len(values)
    mean = sum(values) / n
    variance = sum((x - mean) ** 2 for x in values) / n
    if variance <= 0:
        return 0.0
    std = math.sqrt(variance)
    return (last - mean) / std if std else 0.0


def _parse_mvrv_z_from_bitbo_page(html: str) -> Optional[float]:
    """从 Bitbo MVRV Z-Score 图表页 HTML 中解析最新数值（API 失败时回退）。"""
    if not html or len(html) < 100:
        return None
    # 常见：内嵌 JSON 如 data: [[date, value], ...]，或 "mvrv_z_score": "1.23"
    for pattern in (
        r'"data"\s*:\s*\[\[[^\]]+\]\s*,\s*\[[^,]+\s*,\s*"([-]?\d+\.\d+)"\]',
        r'mvrv_z_score["\']?\s*:\s*["\']?([-]?\d+\.\d+)',
        r'\["\d{4}-\d{2}-\d{2}"\s*,\s*"([-]?\d+\.\d+)"\]\s*\]\s*[;\}]',
        r'\[[^,]+\s*,\s*([-]?\d+\.\d{4,})\s*\]',  # 最后一组 [x, 1.2345]
    ):
        matches = re.findall(pattern, html)
        for s in reversed(matches):
            try:
                v = float(s)
                if -3.5 <= v <= 5.5:  # MVRV Z-Score 合理范围
                    return v
            except ValueError:
                continue
    return None


def _parse_bitbo_mvrv_z_rows(rows: list) -> Optional[float]:
    """从 Bitbo 返回的 data 数组中解析最新 MVRV Z-Score。"""
    if not rows or not isinstance(rows, list):
        return None
    last = rows[-1]
    if isinstance(last, (list, tuple)) and len(last) >= 2:
        try:
            return float(last[1])
        except (TypeError, ValueError):
            pass
    return None


def _fetch_bitbo_mvrv_z_latest() -> Tuple[Optional[float], Optional[str]]:
    """从 Bitbo 获取最新 MVRV Z-Score（已是 Z-Score，无需再算）。返回 (value, error_msg)。"""
    try:
        r = requests.get(
            URL_BITBO_MVRV_Z,
            params={"latest": "true"},
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            proxies=_get_proxies() or {},
        )
        if not r.ok:
            return None, f"HTTP {r.status_code}"
        try:
            data = r.json()
        except ValueError as e:
            return None, f"Bitbo 返回非 JSON: {e}"
        if not isinstance(data, dict) or "data" not in data:
            return None, "返回格式无 data"
        rows = data["data"]
        val = _parse_bitbo_mvrv_z_rows(rows)
        if val is not None:
            return val, None
        # 备用：不带 latest，拉取最近 7 天取最后一条
        end = datetime.utcnow().date()
        start = end - timedelta(days=7)
        r2 = requests.get(
            URL_BITBO_MVRV_Z,
            params={"start_date": start.isoformat(), "end_date": end.isoformat()},
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            proxies=_get_proxies() or {},
        )
        if r2.ok:
            try:
                data2 = r2.json()
                if isinstance(data2, dict) and isinstance(data2.get("data"), list) and data2["data"]:
                    val = _parse_bitbo_mvrv_z_rows(data2["data"])
                    if val is not None:
                        return val, None
            except ValueError:
                pass
        return None, "无法解析 mvrv_z_score 数值"
    except requests.exceptions.Timeout:
        return None, "Bitbo 请求超时"
    except requests.exceptions.RequestException as e:
        return None, f"Bitbo 请求异常: {e}"
    except Exception as e:
        return None, f"Bitbo 异常: {e}"


def _fetch_bitbo_sopr_series(days: int = Z_SCORE_WINDOW_DAYS) -> Optional[List[float]]:
    """从 Bitbo 获取近期 SOPR 日线序列，用于计算 SOPR Z-Score。"""
    def _parse_sopr_rows(rows: list) -> List[float]:
        values = []
        if not isinstance(rows, list):
            return values
        for row in rows:
            if isinstance(row, (list, tuple)) and len(row) >= 2:
                try:
                    values.append(float(row[1]))
                except (TypeError, ValueError):
                    continue
        return values

    try:
        end = datetime.utcnow().date()
        start = end - timedelta(days=days)
        r = requests.get(
            URL_BITBO_SOPR,
            params={
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            },
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            proxies=_get_proxies() or {},
        )
        if not r.ok:
            return None
        try:
            data = r.json()
        except ValueError:
            return None
        if not isinstance(data, dict) or "data" not in data:
            return None
        values = _parse_sopr_rows(data["data"])
        if len(values) >= 2:
            return values
        # 若当天无数据，用昨日为止再试
        end = end - timedelta(days=1)
        start = end - timedelta(days=days)
        r2 = requests.get(
            URL_BITBO_SOPR,
            params={"start_date": start.isoformat(), "end_date": end.isoformat()},
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            proxies=_get_proxies() or {},
        )
        if not r2.ok:
            return None
        try:
            data2 = r2.json()
            if isinstance(data2, dict) and "data" in data2:
                values = _parse_sopr_rows(data2["data"])
                if len(values) >= 2:
                    return values
        except ValueError:
            pass
        return None
    except requests.exceptions.Timeout:
        return None
    except requests.exceptions.RequestException:
        return None
    except Exception:
        return None


def _fetch_looknode_mvrv_series() -> Optional[List[float]]:
    """从 Looknode 获取 MVRV 序列，用于推算 NUPL 序列（NUPL = 1 - 1/MVRV）。"""
    try:
        r = requests.get(
            URL_LOOKNODE_MVRV,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            proxies=_get_proxies() or {},
        )
        if not r.ok:
            return None
        try:
            raw = r.json()
        except ValueError:
            return None
        if not isinstance(raw, dict) or raw.get("code") != 100:
            return None
        data = raw.get("data")
        if not isinstance(data, list) or len(data) < 2:
            return None
        nupl_list = []
        for item in data[-Z_SCORE_WINDOW_DAYS:]:
            if not isinstance(item, dict):
                continue
            v = item.get("v")
            if v is None:
                continue
            try:
                mvrv = float(v)
                if mvrv > 0:
                    nupl_list.append(1.0 - (1.0 / mvrv))
            except (TypeError, ValueError):
                continue
        return nupl_list if len(nupl_list) >= 2 else None
    except requests.exceptions.Timeout:
        return None
    except requests.exceptions.RequestException:
        return None
    except Exception:
        return None


def _get_signal_from_zscore(z: float) -> Tuple[str, str]:
    """根据复合 Z-Score 返回信号与中文描述。"""
    if z < BOTTOM_THRESHOLD:
        return "bottom", "底部区域"
    if z > TOP_THRESHOLD:
        return "top", "顶部区域"
    return "neutral", "中性区间"


def _fetch_mvrv_z_from_bitbo_page() -> Optional[float]:
    """Bitbo MVRV Z-Score 图表页解析（API 失败时回退）。"""
    try:
        r = requests.get(
            URL_BITBO_MVRV_Z_PAGE,
            headers=HEADERS_HTML,
            timeout=REQUEST_TIMEOUT,
            proxies=_get_proxies() or {},
        )
        if not r.ok:
            return None
        return _parse_mvrv_z_from_bitbo_page(r.text)
    except Exception:
        return None


def get_sopr_zscore() -> Dict[str, Any]:
    """
    获取 On-chain Z-Score（SOPR + MVRV + NUPL 三者 Z-Score 的平均）。
    免费数据源：Bitbo API（MVRV Z、SOPR）+ Looknode API（MVRV→NUPL）；Bitbo API 失败时尝试图表页解析。
    返回 {"sopr_zscore", "success", "source", "detail", "signal", "message"}。
    阈值：底部 < -0.44，顶部 > 0.73。
    """
    result = {
        "sopr_zscore": None,
        "success": False,
        "source": "",
        "detail": {},
        "signal": None,
        "message": "",
        "urls": dict(DATA_SOURCE_URLS),  # 获取数据使用的 URL/API 地址
    }
    z_sopr: Optional[float] = None
    z_mvrv: Optional[float] = None
    z_nupl: Optional[float] = None
    sources_used: List[str] = []
    errors: List[str] = []

    # 1) Bitbo MVRV Z-Score（API 优先，失败则尝试图表页）
    z_mvrv, err = _fetch_bitbo_mvrv_z_latest()
    if z_mvrv is None and err:
        errors.append(err)
    if z_mvrv is None:
        z_mvrv = _fetch_mvrv_z_from_bitbo_page()
        if z_mvrv is not None:
            sources_used.append("Bitbo 图表页 MVRV Z")
    if z_mvrv is not None:
        result["detail"]["mvrv_z"] = round(z_mvrv, 4)
        if "Bitbo 图表页" not in str(sources_used):
            sources_used.append("Bitbo MVRV Z")

    # 2) Bitbo SOPR 序列 → 计算 SOPR Z-Score
    sopr_series = _fetch_bitbo_sopr_series()
    if sopr_series:
        z_sopr = _z_score_from_series(sopr_series)
        if z_sopr is not None:
            result["detail"]["sopr_z"] = round(z_sopr, 4)
            sources_used.append("Bitbo SOPR")

    # 3) Looknode MVRV → NUPL 序列 → 计算 NUPL Z-Score
    nupl_series = _fetch_looknode_mvrv_series()
    if nupl_series:
        z_nupl = _z_score_from_series(nupl_series)
        if z_nupl is not None:
            result["detail"]["nupl_z"] = round(z_nupl, 4)
            sources_used.append("Looknode MVRV→NUPL")

    components = [x for x in (z_sopr, z_mvrv, z_nupl) if x is not None]
    if not components:
        result["source"] = "；".join(errors) if errors else "Bitbo 与 Looknode 免费源均未返回有效数据，请检查网络或稍后重试"
        result["message"] = "获取失败"
        result["urls"] = dict(DATA_SOURCE_URLS)
        return result

    composite = sum(components) / len(components)
    result["sopr_zscore"] = round(composite, 4)
    result["success"] = True
    result["source"] = "、".join(sources_used) + "（免费）"
    result["detail"]["components_used"] = len(components)
    result["signal"], result["message"] = _get_signal_from_zscore(composite)
    return result


def get_sopr_zscore_short_message() -> str:
    """
    获取一句可读的 SOPR Z-Score 文案，便于报表或钉钉拼接。
    成功时返回如 "SOPR Z-Score: 0.52 中性区间"；失败时返回 "SOPR Z-Score: 获取失败"。
    """
    res = get_sopr_zscore()
    if res.get("success") and res.get("sopr_zscore") is not None:
        return "SOPR Z-Score: {} {}".format(
            res["sopr_zscore"],
            res.get("message") or "—",
        )
    return "SOPR Z-Score: 获取失败"


if __name__ == "__main__":
    res = get_sopr_zscore()
    print("SOPR Z-Score (On-chain Zscore):", res.get("sopr_zscore"))
    print("success:", res.get("success"))
    print("source:", res.get("source"))
    print("signal:", res.get("signal"), "| message:", res.get("message"))
    print("detail:", res.get("detail"))
    print("阈值: 底部 < {}, 顶部 > {}".format(BOTTOM_THRESHOLD, TOP_THRESHOLD))
    print("短文案:", get_sopr_zscore_short_message())
    print("\n--- 获取数据的 URL/API 地址 ---")
    for name, url in (res.get("urls") or DATA_SOURCE_URLS).items():
        print("  {}: {}".format(name, url))
