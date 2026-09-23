# -*- coding: utf-8 -*-
"""
风险评分模型 (Risk Model) — v1.3
====================================
从 app.py 抽离的评分逻辑, 并升级为:
  1. 新增第6因子: 高收益债信用利差 (HY OAS) —— 与股市自身指标正交的"聪明钱"信号
  2. 分位数化评分: 有历史序列的因子用5年滚动分位数, 无序列的因子用校准阈值映射
  3. 非线性放大: 极端读数贡献非线性增长 (幂变换)
  4. 共振警报: 多个因子同时进入极端分位时触发红色警报 (崩盘的非线性特征)
  5. 最大单项红线: 防止某个极端因子被其他温和因子稀释

设计原则: 指标不是越多越好。CNN恐慌贪婪指数已内含VIX/Put-Call/动量/宽度,
          故不重复添加; 只补一个与现有5因子零重叠的信用维度。
"""

import numpy as np

# ------------------------------------------------------------------
# 因子元数据: key -> (中文名, 权重key)
# ------------------------------------------------------------------
FACTOR_META = {
    "buffett":   {"name": "巴菲特指标",   "weight_key": "buffett"},
    "shiller":   {"name": "席勒市盈率",   "weight_key": "shiller"},
    "credit":    {"name": "信用利差",     "weight_key": "credit"},
    "yield":     {"name": "美债利差",     "weight_key": "yield"},
    "technical": {"name": "均线乖离",     "weight_key": "technical"},
    "sentiment": {"name": "恐慌贪婪",     "weight_key": "sentiment"},
}

# 默认权重 (6因子, 合计100%)
DEFAULT_WEIGHTS = {
    "buffett": 0.15,
    "shiller": 0.20,
    "credit": 0.20,      # 信用利差: 新增, 给较高权重(聪明钱信号)
    "yield": 0.20,
    "technical": 0.15,
    "sentiment": 0.10,
}


# ------------------------------------------------------------------
# 非线性放大: 分位数 -> 风险分
# 用幂变换让极端读数贡献非线性增长。
# percentile 为 0~1 (当前值在历史中处于的分位)。
# exponent>1 时, 越极端(分位越高)分数增长越快。
# ------------------------------------------------------------------
def _nonlinear(percentile, exponent=1.6):
    p = max(0.0, min(1.0, percentile))
    return round(100.0 * (p ** exponent), 1)


# ------------------------------------------------------------------
# 各因子的风险分计算 (统一输出 0-100, 越高越危险)
# 每个函数返回 (risk_score_0_100, display_value, status_text)
# ------------------------------------------------------------------

def score_buffett(buffett_val):
    """巴菲特指标(总市值/GDP %)。无逐日历史序列, 用校准阈值映射(本质即分位)。"""
    v = buffett_val
    if v > 200:
        r = 100
    elif v > 180:
        r = 90
    elif v > 150:
        r = 75
    elif v > 120:
        r = 50
    elif v > 100:
        r = 35
    else:
        r = 20
    return r, f"{v:.1f}%", _level_text(r)


def score_shiller(shiller_val):
    """席勒市盈率 CAPE。无逐日历史序列, 用校准阈值映射。"""
    v = shiller_val
    if v > 40:
        r = 100
    elif v > 35:
        r = 90
    elif v > 30:
        r = 70
    elif v > 25:
        r = 50
    elif v > 20:
        r = 35
    else:
        r = 20
    return r, f"{v:.1f}", _level_text(r)


def score_credit(hy_oas, history=None):
    """
    高收益债信用利差 (%)。有历史序列, 用5年分位数 + 非线性放大。
    利差越大风险越高。history 为历史利差 list (用于算分位)。
    """
    v = hy_oas
    if history and len(history) > 20:
        pct = sum(1 for h in history if h <= v) / len(history)   # 0~1
        r = _nonlinear(pct, exponent=1.6)
        status = f"5年{pct*100:.0f}%分位"
    else:
        # 无历史时退化为绝对阈值 (HY OAS 历史经验: <3低 3-4正常 4-5紧张 >5危险)
        if v > 6:
            r = 100
        elif v > 5:
            r = 85
        elif v > 4:
            r = 65
        elif v > 3:
            r = 40
        else:
            r = 20
        status = "绝对阈值"
    return r, f"{v:.2f}%", status


def score_yield(us_10y, us_2y, spread_history=None):
    """
    美债 10Y-2Y 利差。倒挂/解挂是衰退预警。
    利差因子方向特殊: 深度倒挂和解挂期都危险, 用规则映射(不单纯分位)。
    """
    spread = us_10y - us_2y
    if spread < -0.5:
        r, status = 80, "深度倒挂"
    elif spread < 0:
        r, status = 60, "轻度倒挂"
    elif 0 <= spread < 0.5:
        r, status = 70, "解挂/平坦(危)"   # 倒挂后解挂是历史最危险时刻
    else:
        r, status = 30, "正常"
    return r, f"{spread:.2f}%", status


def score_technical(current_price, sma_200):
    """200日均线乖离率 (%)。偏离越大越超买(正乖离高风险)。"""
    if sma_200 and not np.isnan(sma_200) and sma_200 != 0:
        dev_pct = (current_price - sma_200) / sma_200 * 100
    else:
        dev_pct = 0
    d = dev_pct
    if d > 25:
        r = 100
    elif d > 20:
        r = 85
    elif d > 15:
        r = 65
    elif d > 5:
        r = 40
    elif d < -10:
        r = 10
    else:
        r = 20
    return r, f"{d:.1f}%", _level_text(r)


def score_sentiment(fear_val):
    """
    CNN恐慌贪婪指数 (0-100)。反向指标: 极度贪婪高风险。
    注意: 极度恐慌(<20)给低分但不给0 —— 恐慌也可能是崩盘进行中。
    """
    v = fear_val
    if v > 80:
        r = 100
    elif v > 60:
        r = 70
    elif v < 20:
        r = 25      # 极度恐慌: 可能见底, 但也可能是崩盘中段, 给低中分而非0
    else:
        r = 40
    return r, f"{int(v)}", _level_text(r)


def _level_text(r):
    if r >= 80:
        return "极高"
    if r >= 60:
        return "偏高"
    if r >= 40:
        return "中性"
    return "低"


# ------------------------------------------------------------------
# 共振检测: 多个因子同时进入极端区(>=80分)时, 风险非线性放大
# ------------------------------------------------------------------
def detect_resonance(factor_scores, threshold=80):
    """
    factor_scores: dict key->risk_score(0-100)
    返回 (extreme_count, resonance_active, boost)
      extreme_count: 进入极端区的因子数
      resonance_active: 是否触发共振(>=3个因子极端)
      boost: 共振加分 (非线性, 最多+15)
    """
    extreme = sum(1 for s in factor_scores.values() if s >= threshold)
    active = extreme >= 3
    # 共振加分: 3个极端+8, 4个+12, 5个及以上+15 (非线性但封顶)
    boost = {3: 8, 4: 12}.get(extreme, 15 if extreme >= 5 else 0)
    return extreme, active, boost


# ------------------------------------------------------------------
# 主评分函数
# ------------------------------------------------------------------
def calculate_risk(factor_inputs, weights, hy_history=None):
    """
    综合风险评分。

    参数:
      factor_inputs: dict, 含各因子原始值:
          buffett(%)  shiller  hy_oas(%)  us_10y  us_2y
          price  sma200  fear(0-100)
      weights: dict, key->0~1 权重 (会自动归一化)
      hy_history: 高收益债利差历史list (用于分位数, 可None)

    返回:
      (final_score, detail_dict)
      detail_dict 含: 各因子(risk,value,status), 共振信息, 最大单项红线
    """
    # 权重归一化 (防止总和不是100)
    total_w = sum(weights.get(k, 0) for k in FACTOR_META)
    if total_w <= 0:
        weights = dict(DEFAULT_WEIGHTS)
        total_w = 1.0
    wn = {k: weights.get(k, 0) / total_w for k in FACTOR_META}

    details = {}
    factor_scores = {}

    # 各因子打分
    r, v, s = score_buffett(factor_inputs["buffett"])
    details["buffett"] = (r, v, s);      factor_scores["buffett"] = r

    r, v, s = score_shiller(factor_inputs["shiller"])
    details["shiller"] = (r, v, s);      factor_scores["shiller"] = r

    r, v, s = score_credit(factor_inputs["hy_oas"], hy_history)
    details["credit"] = (r, v, s);       factor_scores["credit"] = r

    r, v, s = score_yield(factor_inputs["us_10y"], factor_inputs["us_2y"])
    details["yield"] = (r, v, s);        factor_scores["yield"] = r

    r, v, s = score_technical(factor_inputs["price"], factor_inputs["sma200"])
    details["technical"] = (r, v, s);    factor_scores["technical"] = r

    r, v, s = score_sentiment(factor_inputs["fear"])
    details["sentiment"] = (r, v, s);    factor_scores["sentiment"] = r

    # 加权总分
    weighted = sum(factor_scores[k] * wn[k] for k in FACTOR_META)

    # 共振检测
    extreme_cnt, resonance, boost = detect_resonance(factor_scores)

    # 最大单项红线: 防止极端信号被温和因子稀释。
    # 若某因子 >=90 (极端), 总分下限托底到该因子分的 70%;
    # 这捕捉"单点突破即危机"的非线性 (如2008雷曼: 信用利差爆表但其他因子温和)。
    max_factor = max(factor_scores, key=factor_scores.get)
    max_score = factor_scores[max_factor]
    redline_floor = 0.0
    if max_score >= 90:
        redline_floor = max_score * 0.7     # 单因子爆表 -> 总分至少 63
    elif max_score >= 80:
        redline_floor = max_score * 0.6     # 单因子高危 -> 总分至少 48

    final = max(weighted, redline_floor)    # 红线托底
    final = min(100.0, final + boost)       # 共振加分, 封顶100

    details["_meta"] = {
        "weighted": round(weighted, 1),
        "resonance": resonance,
        "extreme_count": extreme_cnt,
        "boost": boost,
        "max_factor": FACTOR_META[max_factor]["name"],
        "max_score": max_score,
        "max_factor_key": max_factor,
        "redline_floor": round(redline_floor, 1),
    }
    return round(final, 1), details
