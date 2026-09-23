# -*- coding: utf-8 -*-
# -------------------------
# @Time    :  2026/2/13 13:39
# @Author  : alvin
# @Description:  从 CoinGlass 获取 BTC NUPL 最新值（优先 API，其次网页）
# -------------------------
"""
英文：Net Unrealized Profit/Loss

📊 指标含义
公式：(市值 - 实现市值) ÷ 市值

通俗：整个市场的平均浮盈/浮亏率

范围：-1 到 1（负数 = 整体浮亏）

🎯 六色分区（行业标准）
NUPL区间	颜色	情绪	阶段
>0.75	🟢 极度贪婪	狂欢	牛市顶部区域
0.5 - 0.75	🟢 乐观	牛市中期	持有
0.25 - 0.5	🟡 中性	观望	不确定性
0 - 0.25	🟠 焦虑	牛市回调/熊市初期	谨慎
-0.25 - 0	🔴 绝望	熊市中期	接近底部
<-0.25	⚫ 极度绝望	历史大底	极度低估
📉 为什么红色区域是底？
逻辑链：

NUPL < 0 → 市场整体浮亏
NUPL < -0.25 → 平均亏损25%以上
历史上只有极端事件才会到这个位置：

2015年：-0.37
2018年：-0.30
2020年3月：-0.35
2022年11月：-0.26
🟡 当前（你截图时）：
还在黄色区域（0到-0.25之间），未到红色
结论：还没到最绝望的时刻
意味着可能还有最后一跌，或者需要更长时间磨底

数据来源（多源可选）：
- CryptoQuant API：https://cryptoquant.com/docs，Key 见 https://cryptoquant.com/settings/api
- CoinGlass：https://coinglass.com/zh/pro/i/BTC-NUPL，https://docs.coinglass.com/...
- CryptoQuant 图表页：https://cryptoquant.com/asset/btc/chart/network-indicator/net-unrealized-profit-loss-nupl
"""
import json
import os
import re
import sys
from typing import Any, Dict, Optional, Union

import requests

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from utils.operationConfig import OperationConfig

# CryptoQuant API：BTC NUPL，多路径兼容不同套餐/版本（404/403 时可能需升级或端点已变更），见 https://cryptoquant.com/docs
URLS_CRYPTOQUANT_NUPL_API = (
    "https://api.cryptoquant.com/v1/btc/network-indicator/net-unrealized-profit-loss-nupl",
    "https://api.cryptoquant.com/v1/btc/network-data/net-unrealized-profit-loss-nupl",
    "https://api.cryptoquant.com/v1/btc/network-indicator/nupl",
    "https://api.cryptoquant.com/v1/btc/utxo-indicator/net-unrealized-profit-loss-nupl",
    "https://api.cryptoquant.com/v1/btc/utxo-indicator/nupl",
)
# Bitcoin CounterFlow：NUPL，需 Nakamoto Pro 订阅，见 https://bitcoincounterflow.com/api-access/
URL_COUNTERFLOW_NUPL = "https://api.bitcoincounterflow.com/api/nupl"
# Looknode 免费接口：MVRV（市值/全市场实现市值），无 Key；推算的是「网络未实现盈亏比」即整体 NUPL，非 STH/LTH-NUPL
# NUPL = (市值-实现市值)/市值 = 1 - 1/MVRV
URL_LOOKNODE_MVRV = "https://www.looknode.com/api/mCapRealizedRatio"
# CoinGlass API v4：BTC NUPL
URL_COINGLASS_NUPL = "https://open-api-v4.coinglass.com/api/index/bitcoin-net-unrealized-profit-loss"
# 网页备用（数据多为 JS 动态加载，可能拿不到）
URL_PAGE = "https://coinglass.com/zh/pro/i/BTC-NUPL"
# CryptoQuant NUPL 图表页（未登录时可能无图表数据，仅尝试解析）
URL_CRYPTOQUANT_NUPL = (
    "https://cryptoquant.com/asset/btc/chart/network-indicator/"
    "net-unrealized-profit-loss-nupl?window=DAY&sma=0&ema=0&priceScale=log&metricScale=linear&chartStyle=line"
)
REQUEST_TIMEOUT = 25
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


def _get_proxies() -> Dict[str, str]:
    """从 config [proxy] 读取代理；未启用时返回 {} 直连。"""
    p = OperationConfig().get_proxy_config()
    return p if p else {}


def _parse_nupl_from_api_response(data: Union[dict, list]) -> Optional[float]:
    """从 CoinGlass API 返回的 JSON 中解析最新 NUPL 数值。"""
    if data is None:
        return None
    # 常见：{"data": [{"t": 123, "value": 0.xx}]} 或 {"data": {"list": [...]}} 或 {"list": [...]}
    if isinstance(data, dict):
        # 先检查业务错误（如 code != 0 或 success == false）
        if data.get("code") not in (None, 0, "0"):
            return None
        if data.get("success") is False:
            return None
        # CryptoQuant 可能用 result 包裹；CoinGlass 等用 data/list/series
        inner = (
            data.get("result")
            or data.get("data")
            or data.get("list")
            or data.get("series")
        )
        # CryptoQuant 常见格式: result.data 或 result.result 为数组
        if isinstance(inner, dict):
            inner = inner.get("data") or inner.get("list") or inner.get("result")
        if inner is not None:
            if isinstance(inner, (int, float)):
                return float(inner)
            if isinstance(inner, list) and inner:
                last = inner[-1]
                if isinstance(last, (int, float)):
                    return float(last)
                if isinstance(last, dict):
                    for key in ("value", "nupl", "nuplValue", "v", "y", "nv"):
                        if key in last and last[key] is not None:
                            try:
                                return float(last[key])
                            except (TypeError, ValueError):
                                pass
        for key in ("value", "nupl"):
            if key in data and data[key] is not None:
                try:
                    return float(data[key])
                except (TypeError, ValueError):
                    pass
    if isinstance(data, list) and data:
        last = data[-1]
        if isinstance(last, (int, float)):
            return float(last)
        if isinstance(last, dict):
            for key in ("value", "nupl", "v", "y"):
                if key in last and last[key] is not None:
                    try:
                        return float(last[key])
                    except (TypeError, ValueError):
                        pass
    return None


def _fetch_nupl_from_cryptoquant_api(api_key: str):
    """
    请求 CryptoQuant API 获取 BTC NUPL，解析最新值。
    依次尝试多个端点路径（不同套餐可能不同）。
    Header: Authorization: Bearer {api_key}
    返回 (value or None, error_msg)。
    参考：https://cryptoquant.com/docs 与 https://cryptoquant.com/settings/api
    """
    if not api_key:
        return None, "未配置 API_KEY"
    api_key = api_key.strip()
    if not api_key:
        return None, "API_KEY 为空"
    errors = []
    for base_url in URLS_CRYPTOQUANT_NUPL_API:
        try:
            url = f"{base_url}?window=day"
            r = requests.get(
                url,
                headers={
                    **HEADERS,
                    "Authorization": f"Bearer {api_key}",
                },
                timeout=REQUEST_TIMEOUT,
                proxies=_get_proxies() or {},
            )
            try:
                data = r.json()
            except Exception:
                data = None
            if not r.ok:
                msg = f"HTTP {r.status_code}"
                if isinstance(data, dict):
                    for k in ("message", "msg", "error"):
                        if data.get(k):
                            msg = f"{msg} {data.get(k)}"
                            break
                errors.append(msg)
                continue
            value = _parse_nupl_from_api_response(data)
            if value is not None:
                return value, ""
            errors.append("返回数据格式无法解析（缺少 value/nupl 等字段）")
        except requests.exceptions.ProxyError as e:
            return None, f"代理错误: {e}"
        except requests.exceptions.Timeout:
            return None, "请求超时"
        except requests.exceptions.RequestException as e:
            errors.append(str(e))
        except Exception as e:
            errors.append(f"异常: {e}")
    return None, "; ".join(errors) if errors else "所有端点均失败"


def _fetch_nupl_from_api(api_key: str):
    """
    请求 CoinGlass API v4 获取 BTC NUPL，解析最新值。
    GET https://open-api-v4.coinglass.com/api/index/bitcoin-net-unrealized-profit-loss
    Header: CG-API-KEY: {api_key}
    返回 (value or None, error_msg)。
    """
    if not api_key:
        return None, "未配置 API_KEY"
    api_key = api_key.strip()
    if not api_key:
        return None, "API_KEY 为空"
    try:
        r = requests.get(
            URL_COINGLASS_NUPL,
            headers={
                **HEADERS,
                "CG-API-KEY": api_key,
            },
            timeout=REQUEST_TIMEOUT,
            proxies=_get_proxies() or {},
        )
        # 先尝试解析 JSON（4xx 时也可能返回 JSON 错误信息）
        try:
            data = r.json()
        except Exception:
            data = None
        if not r.ok:
            msg = f"HTTP {r.status_code}"
            if isinstance(data, dict) and data.get("msg"):
                msg = f"{msg} {data.get('msg')}"
            return None, msg
        value = _parse_nupl_from_api_response(data)
        if value is not None:
            return value, ""
        # 解析失败时给出提示
        if isinstance(data, dict) and "msg" in data:
            return None, f"解析失败: {data.get('msg')}"
        return None, "返回数据格式无法解析（缺少 value/nupl 等字段）"
    except requests.exceptions.ProxyError as e:
        return None, f"代理错误: {e}"
    except requests.exceptions.Timeout:
        return None, "请求超时"
    except requests.exceptions.RequestException as e:
        return None, f"请求异常: {e}"
    except Exception as e:
        return None, f"异常: {e}"


def _fetch_nupl_from_looknode_mvrv():
    """
    免费：从 Looknode 的 MVRV 接口推算「网络未实现盈亏比」(整体 NUPL)，非短期/长期持有者 NUPL。
    MVRV 使用全市场实现市值，故 NUPL = (市值 - 实现市值) / 市值 = 1 - 1/MVRV 为网络级指标。
    接口：https://www.looknode.com/api/mCapRealizedRatio，返回 {"code":100,"data":[{"t":ts,"v":mvrv},...]}
    可能有延迟，但无需 API Key。
    返回 (value or None, error_msg)。
    """
    try:
        r = requests.get(
            URL_LOOKNODE_MVRV,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            proxies=_get_proxies() or {},
        )
        if not r.ok:
            return None, f"HTTP {r.status_code}"
        raw = r.json()
        if not isinstance(raw, dict) or raw.get("code") != 100:
            return None, "返回 code 非 100 或格式异常"
        data = raw.get("data")
        if not isinstance(data, list) or not data:
            return None, "无 data 或 data 为空"
        last = data[-1]
        if not isinstance(last, dict):
            return None, "最后一条非对象"
        v = last.get("v")
        if v is None:
            return None, "无 v 字段"
        try:
            mvrv = float(v)
        except (TypeError, ValueError):
            return None, "MVRV 无法转为数值"
        if mvrv <= 0:
            return None, "MVRV 需为正数"
        nupl = 1.0 - (1.0 / mvrv)
        if -1.5 <= nupl <= 1.5:
            return nupl, ""
        return None, "推算值超出合理范围"
    except requests.exceptions.ProxyError as e:
        return None, f"代理错误: {e}"
    except requests.exceptions.Timeout:
        return None, "请求超时"
    except requests.exceptions.RequestException as e:
        return None, str(e)
    except Exception as e:
        return None, str(e)


def _fetch_nupl_from_counterflow(api_key: str):
    """
    请求 Bitcoin CounterFlow API 获取 NUPL。
    GET https://api.bitcoincounterflow.com/api/nupl?apikey={api_key}
    返回格式通常为 [{ "timestamp", "nupl" }] 或类似。需 Nakamoto Pro 订阅。
    返回 (value or None, error_msg)。
    """
    if not api_key or not api_key.strip():
        return None, "未配置 API_KEY"
    try:
        url = f"{URL_COUNTERFLOW_NUPL}?apikey={api_key.strip()}"
        r = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            proxies=_get_proxies() or {},
        )
        try:
            data = r.json()
        except Exception:
            data = None
        if not r.ok:
            msg = f"HTTP {r.status_code}"
            if isinstance(data, dict) and (data.get("message") or data.get("error")):
                msg = f"{msg} {data.get('message') or data.get('error')}"
            return None, msg
        value = _parse_nupl_from_api_response(data)
        if value is not None and -1.5 <= value <= 1.5:
            return value, ""
        return None, "返回格式无法解析"
    except requests.exceptions.ProxyError as e:
        return None, f"代理错误: {e}"
    except requests.exceptions.Timeout:
        return None, "请求超时"
    except requests.exceptions.RequestException as e:
        return None, str(e)
    except Exception as e:
        return None, str(e)


def _fetch_nupl_from_page() -> Optional[float]:
    """
    从 Coinglass 页面 HTML 中尝试解析 NUPL（页面多为 JS 拉取，可能解析不到）。
    尝试：1) 内联 JSON/__NEXT_DATA__；2) 正则匹配 -1~1 之间的小数。
    """
    try:
        r = requests.get(
            URL_PAGE,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            proxies=_get_proxies() or {},
        )
        r.raise_for_status()
        text = r.text
    except Exception:
        return None
    # 常见：图表数据在 __NEXT_DATA__ 或 window.__INITIAL_STATE__ 等
    for pattern in (
        r'"nupl"\s*:\s*([-]?\d+\.?\d*)',
        r'"value"\s*:\s*([-]?\d+\.?\d*)\s*[,\}]',  # 可能误匹配，取最后一个
        r'nupl["\']?\s*:\s*([-]?\d+\.?\d*)',
        r'BTC-NUPL["\']?\s*[^}]*?([-]?\d+\.\d{2,6})\s*[,\}]',
    ):
        matches = re.findall(pattern, text, re.IGNORECASE)
        for m in reversed(matches):
            try:
                v = float(m)
                if -1.5 <= v <= 1.5:  # NUPL 理论范围约 -1~1
                    return v
            except ValueError:
                continue
    return None


def _fetch_nupl_from_cryptoquant() -> Optional[float]:
    """
    从 CryptoQuant NUPL 图表页 HTML/脚本中尝试解析最新 NUPL。
    该页未登录时可能显示 "Sign in"，图表数据多为 JS 拉取，仅尝试常见嵌入格式与正则。
    """
    try:
        r = requests.get(
            URL_CRYPTOQUANT_NUPL,
            headers={
                **HEADERS,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            timeout=REQUEST_TIMEOUT,
            proxies=_get_proxies() or {},
        )
        r.raise_for_status()
        text = r.text
    except Exception:
        return None
    # 1) 尝试 __NEXT_DATA__、__NUXT__、chartData 等内联 JSON
    for pattern in (
        r'<script[^>]*id="__NEXT_DATA__"[^>]*type="application/json"[^>]*>([^<]+)</script>',
        r'__NUXT__\s*=\s*(\{[^;]+\});',
        r'"chartData"\s*:\s*(\[[^\]]+\])',
        r'"values?"\s*:\s*(\[[^\]]+\])',
        r'nupl["\']?\s*:\s*([-]?\d+\.?\d*)',
        r'"value"\s*:\s*([-]?\d+\.?\d*)\s*[,\}\]].*?nupl',
        r'net-unrealized-profit-loss-nupl[^"]*["\s:]+([-]?\d+\.\d{2,8})',
    ):
        for m in re.finditer(pattern, text, re.IGNORECASE | re.DOTALL):
            try:
                g = m.group(1)
                if not g:
                    continue
                g = g.strip()
                if g.startswith("{") or g.startswith("["):
                    # 内联 JSON：尝试解析并提取 NUPL
                    try:
                        data = json.loads(g)
                        val = _parse_nupl_from_api_response(data)
                        if val is not None and -1.5 <= val <= 1.5:
                            return val
                    except (json.JSONDecodeError, TypeError):
                        pass
                    # 非标准 JSON 时从字符串中抽数字
                    parts = re.findall(r"[-]?\d+\.?\d*", g)
                    for p in reversed(parts):
                        v = float(p)
                        if -1.5 <= v <= 1.5:
                            return v
                else:
                    v = float(g.strip('"').strip("'"))
                    if -1.5 <= v <= 1.5:
                        return v
            except (ValueError, IndexError):
                continue
    # 2) 通用：在 -1~1 范围内找最近出现的合理小数（避免误匹配价格等）
    for pattern in (r'"v"\s*:\s*([-]?\d+\.\d{4,})', r"nupl.*?([-]?\d+\.\d{4,})"):
        matches = re.findall(pattern, text, re.IGNORECASE)
        for s in reversed(matches):
            try:
                v = float(s)
                if -1.5 <= v <= 1.5:
                    return v
            except ValueError:
                continue
    return None


def _parse_nupl_from_csv(text: str) -> Optional[float]:
    """从 BM Pro 返回的 CSV 文本解析最后一行 NUPL 数值。"""
    if not text or not text.strip():
        return None
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if not lines:
        return None
    last_line = lines[-1]
    for part in reversed([p.strip().replace(" ", "").replace('"', "") for p in last_line.split(",")]):
        try:
            v = float(part)
            if -1.5 <= v <= 1.5:
                return v
        except (ValueError, TypeError):
            continue
    return None


def _fetch_nupl_from_bmpro(api_key: str):
    """
    请求 Bitcoin Magazine Pro API 获取 NUPL。
    API: GET https://api.bitcoinmagazinepro.com/metrics/nupl
    Auth: Authorization: Bearer {api_key}
    返回 (value or None, error_msg)。BM Pro 可能返回 JSON 或 CSV。
    """
    if not api_key or not api_key.strip():
        return None, "未配置 API_KEY"
    try:
        r = requests.get(
            "https://api.bitcoinmagazinepro.com/metrics/nupl",
            headers={**HEADERS, "Authorization": f"Bearer {api_key.strip()}"},
            timeout=REQUEST_TIMEOUT,
            proxies=_get_proxies() or {},
        )
        if not r.ok:
            msg = f"HTTP {r.status_code}"
            try:
                data = r.json()
                if isinstance(data, dict) and data.get("message"):
                    msg = f"{msg} {data.get('message')}"
            except Exception:
                pass
            return None, msg
        ct = (r.headers.get("Content-Type") or "").lower()
        if "json" in ct:
            try:
                value = _parse_nupl_from_api_response(r.json())
                if value is not None and -1.5 <= value <= 1.5:
                    return value, ""
            except Exception:
                pass
        value = _parse_nupl_from_csv(r.text)
        if value is not None:
            return value, ""
        try:
            value = _parse_nupl_from_api_response(r.json())
            if value is not None and -1.5 <= value <= 1.5:
                return value, ""
        except Exception:
            pass
        return None, "返回格式无法解析"
    except requests.exceptions.ProxyError as e:
        return None, f"代理错误: {e}"
    except requests.exceptions.Timeout:
        return None, "请求超时"
    except requests.exceptions.RequestException as e:
        return None, str(e)
    except Exception as e:
        return None, str(e)


def get_nupl() -> Dict[str, Any]:
    """
    获取最新 BTC NUPL 数值。
    优先顺序：Looknode 免费(MVRV 推算) → BM Pro API → CounterFlow API → CryptoQuant API
    → CoinGlass API → CoinGlass 网页 → CryptoQuant 网页。
    免费方式：优先使用 Looknode 的 MVRV 接口按 NUPL=1-1/MVRV 推算，数据可能有延迟。
    返回 {"nupl": float|None, "success": bool, "source": str}。
    """
    result = {"nupl": None, "success": False, "source": None}
    value = None
    api_errors = []  # 收集各 API 错误，便于排查
    # 0) Looknode 免费：MVRV 推算 NUPL（无需 Key，可能有延迟）
    value, err = _fetch_nupl_from_looknode_mvrv()
    if value is not None:
        result["nupl"] = round(value, 4)
        result["success"] = True
        result["source"] = "Looknode（MVRV 推算，免费）"
        return result
    if err:
        api_errors.append(f"Looknode: {err}")
    # 1) Bitcoin Magazine Pro API（Look Into Bitcoin 继任，需 Pro 订阅）
    bmpro_key = OperationConfig().get_bmpro_api_key()
    if bmpro_key:
        value, err = _fetch_nupl_from_bmpro(bmpro_key)
        if value is not None:
            result["nupl"] = round(value, 4)
            result["success"] = True
            result["source"] = "Bitcoin Magazine Pro API"
            return result
        if err:
            api_errors.append(f"BM Pro API: {err}")
    # 2) Bitcoin CounterFlow API（需 Nakamoto Pro，见 https://bitcoincounterflow.com/api-access/）
    if value is None:
        cf_key = OperationConfig().get_counterflow_api_key()
        if cf_key:
            value, err = _fetch_nupl_from_counterflow(cf_key)
            if value is not None:
                result["nupl"] = round(value, 4)
                result["success"] = True
                result["source"] = "Bitcoin CounterFlow API"
                return result
            if err:
                api_errors.append(f"CounterFlow API: {err}")
    # 3) CryptoQuant API（与图表页一致；若 404/403 可能需升级套餐或端点已变更）
    cq_key = OperationConfig().get_cryptoquant_api_key()
    if cq_key:
        value, err = _fetch_nupl_from_cryptoquant_api(cq_key)
        if value is not None:
            result["nupl"] = round(value, 4)
            result["success"] = True
            result["source"] = "CryptoQuant API"
        elif err:
            api_errors.append(f"CryptoQuant API: {err}")
    # 4) CoinGlass API
    if value is None:
        cg_key = OperationConfig().get_coinglass_api_key()
        if cg_key:
            value, err = _fetch_nupl_from_api(cg_key)
            if value is not None:
                result["nupl"] = round(value, 4)
                result["success"] = True
                result["source"] = "CoinGlass API"
            elif err:
                api_errors.append(f"CoinGlass API: {err}")
    # 5) 网页解析
    if value is None:
        value = _fetch_nupl_from_page()
        if value is not None:
            result["nupl"] = round(value, 4)
            result["success"] = True
            result["source"] = "CoinGlass 网页解析"
    if value is None:
        value = _fetch_nupl_from_cryptoquant()
        if value is not None:
            result["nupl"] = round(value, 4)
            result["success"] = True
            result["source"] = "CryptoQuant 网页解析"
    if value is None:
        if api_errors:
            result["source"] = "；".join(api_errors) + "；网页解析无结果"
            if any("Upgrade plan" in e or "升级" in e for e in api_errors):
                result["source"] += "（CoinGlass 需升级套餐；CryptoQuant 若报 404 请到 https://cryptoquant.com/docs 核对 NUPL 端点路径）"
        else:
            result["source"] = (
                "Looknode 免费源失败；未配置付费 API_KEY 且网页解析无结果。"
                "可检查网络/代理后重试，或配置 [bmpro]/[counterflow] 等。"
            )
    return result


if __name__ == "__main__":
    res = get_nupl()
    print("NUPL:", res.get("nupl"))
    print("success:", res.get("success"))
    print("source:", res.get("source"))
