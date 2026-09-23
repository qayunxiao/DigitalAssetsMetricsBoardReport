import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import os

import data_fetcher as dfetch
import risk_model

# 尝试从 .env 读取 FRED API key (可选, 用于 GDP/巴菲特指标自动化)
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass
DEFAULT_FRED_KEY = os.environ.get("FRED_API_KEY", "")

# ==========================================
# 1. 页面配置与样式 (UI Configuration)
# ==========================================
st.set_page_config(
    page_title="美股崩盘风险监测仪",
    page_icon="📉",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 项目 GitHub 地址
GITHUB_URL = "https://github.com/middletoo/US_Stock_Crash_Monitor"

# 自定义CSS
st.markdown(f"""
<style>
    /* 左上角 GitHub 浮动标签 */
    .github-corner {{
        position: fixed;
        top: 10px;
        left: 10px;
        z-index: 9999;
        text-decoration: none;
        color: white;
        background: #24292e;
        padding: 6px 12px;
        border-radius: 20px;
        font-size: 13px;
        font-weight: bold;
        display: flex;
        align-items: center;
        gap: 8px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.3);
        transition: all 0.3s ease;
        border: 1px solid #444;
    }}
    .github-corner:hover {{
        background: #444;
        transform: translateY(-2px);
        box-shadow: 0 4px 8px rgba(0,0,0,0.5);
        color: #4da6ff;
    }}

    .stProgress > div > div > div > div {{
        background-color: #ff4b4b;
    }}
    h1, h2, h3 {{
        font-family: 'Roboto', sans-serif;
    }}
    /* 让Metric的label更明显一点 */
    div[data-testid="stMetricLabel"] {{
        font-size: 14px;
        color: #9da3ad;
    }}
    /* 链接样式 */
    .source-link {{
        font-size: 0.85em;
        color: #4da6ff;
        text-decoration: none;
        margin-bottom: 5px;
        display: inline-block;
    }}
    .source-link:hover {{
        text-decoration: underline;
    }}
</style>

<!-- GitHub 浮动标签 HTML -->
<a href="{GITHUB_URL}" target="_blank" class="github-corner">
    <svg height="18" width="18" viewBox="0 0 16 16" fill="white"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"></path></svg>
    GitHub 项目
</a>
""", unsafe_allow_html=True)


# ==========================================
# 2. 数据获取与处理模块 (Data Pipeline)
# ==========================================

@st.cache_data(ttl=1800, show_spinner="🔄 正在自动获取数据...")
def get_auto_data(ticker, fred_key, proxy):
    """
    一键获取所有数据(行情+宏观+情绪), 带30分钟缓存。
    行情失败自动降级为模拟数据。返回 dict, 每项含 ok/value/source/error。
    """
    key = fred_key.strip() if fred_key and fred_key.strip() else None
    return dfetch.fetch_all(ticker=ticker, fred_api_key=key, proxy=proxy)


# ==========================================
# 3. 侧边栏：配置与输入
# ==========================================
st.sidebar.title("🛠️ 设置与校准")

# 侧边栏顶部也增加一个源码链接，方便移动端查看
st.sidebar.markdown(f"[📂 查看 GitHub 源代码]({GITHUB_URL})")

# --- 标的选择 ---
st.sidebar.subheader("0. 监测标的")
target_option = st.sidebar.selectbox(
    "选择你要分析的ETF",
    ["VOO (标普500)", "QQQ (纳指100)"],
    index=0
)
ticker_symbol = "VOO" if "VOO" in target_option else "QQQ"

# --- 权重配置 (v1.3: 6因子, 新增信用利差) ---
with st.sidebar.expander("⚖️ 模型权重配置 (点击展开)", expanded=False):
    st.caption("v1.3 六因子模型。权重无需凑满100, 系统会自动归一化。")

    w_buffett_input = st.slider("1. 巴菲特指标权重", 0, 50, 15, 5, format="%d%%")
    w_shiller_input = st.slider("2. 席勒市盈率权重", 0, 50, 20, 5, format="%d%%")
    w_credit_input = st.slider("3. 信用利差权重 (新增)", 0, 50, 20, 5, format="%d%%",
                               help="高收益债利差, 与股市指标正交的'聪明钱'信号")
    w_yield_input = st.slider("4. 美债利差权重", 0, 50, 20, 5, format="%d%%")
    w_tech_input = st.slider("5. 均线乖离权重", 0, 50, 15, 5, format="%d%%")
    w_sentiment_input = st.slider("6. 恐慌指数权重", 0, 50, 10, 5, format="%d%%")

    total_weight_score = (w_buffett_input + w_shiller_input + w_credit_input +
                          w_yield_input + w_tech_input + w_sentiment_input)
    st.caption(f"当前权重总和: {total_weight_score}% (自动归一化, 无需凑整)")

    user_weights = {
        'buffett': w_buffett_input / 100.0,
        'shiller': w_shiller_input / 100.0,
        'credit': w_credit_input / 100.0,
        'yield': w_yield_input / 100.0,
        'technical': w_tech_input / 100.0,
        'sentiment': w_sentiment_input / 100.0
    }

# --- 网络设置 ---
with st.sidebar.expander("🌐 网络连接设置", expanded=False):
    st.caption("无法连接Yahoo Finance时请填入代理，或留空使用**模拟演示模式**。")
    proxy_url = st.text_input("HTTP代理地址", placeholder="例如 http://127.0.0.1:7890")

# --- 数据源自动化设置 ---
with st.sidebar.expander("🔑 数据源自动化 (推荐配置)", expanded=True):
    st.caption("填入免费 FRED API key 后，**GDP / 巴菲特指标**将自动更新。")
    st.markdown("[📌 免费申请 FRED key (30秒)](https://fred.stlouisfed.org/docs/api/api_key.html)",
                unsafe_allow_html=True)
    fred_key_input = st.text_input(
        "FRED API Key (可选)",
        value=DEFAULT_FRED_KEY,
        type="password",
        help="申请免费key后粘贴于此。不提供则GDP/巴菲特指标回退为网页抓取或手动输入。"
    )
    auto_fetch = st.toggle("🔄 启用数据自动获取", value=True,
                           help="关闭后所有指标回退为手动输入")
    if st.button("♻️ 刷新所有数据", help="清除缓存并重新拉取全部数据源"):
        st.cache_data.clear()
        st.rerun()

# --- 宏观数据输入 ---

st.sidebar.markdown("---")

# ============================================================
# 自动获取所有宏观/情绪数据 (若启用)
# ============================================================
# 行情数据始终自动获取(图表基础), auto_fetch 只控制宏观/情绪指标
auto = get_auto_data(ticker_symbol, fred_key_input, proxy_url)
if not auto_fetch:
    # 关闭自动获取时, 清空宏观/情绪项, 但保留行情
    auto = {"market": auto.get("market"), "us10y": auto.get("us10y")}


def _auto_val(key, fallback):
    """取自动值, 失败返回 fallback。返回 (value, source, is_auto)"""
    item = auto.get(key)
    if item and item.get("ok") and item.get("value") is not None:
        return item["value"], item.get("source", "auto"), True
    return fallback, None, False


def _metric_block(title, link_md, key, manual_default, unit, fmt,
                  step, info_md, help_text=""):
    """
    渲染一个'自动获取 + 手动覆盖'的指标配置块。
    返回最终采用的数值 (自动优先, 用户可勾选手动覆盖)。
    """
    st.sidebar.subheader(title)
    st.sidebar.markdown(link_md, unsafe_allow_html=True)

    auto_value, source, is_auto = _auto_val(key, manual_default)

    if is_auto:
        st.sidebar.success(f"✅ 自动获取: **{auto_value:{fmt}}{unit}** ({source})")
    else:
        err = auto.get(key, {}).get("error", "未启用自动获取") if auto else "自动获取已关闭"
        st.sidebar.warning(f"⚠️ 自动获取不可用 ({err[:40]})，请手动输入")

    # 手动覆盖开关
    override = st.sidebar.checkbox(
        f"✏️ 手动校准此指标", key=f"ov_{key}", value=not is_auto,
        help=help_text or "勾选后可手动输入，覆盖自动获取的值"
    )

    if override:
        manual = st.sidebar.number_input(
            f"{title.split('. ', 1)[-1]} 手动值",
            value=float(auto_value), step=step, key=f"manual_{key}"
        )
        final_val = manual
        st.sidebar.caption(f"当前使用: **手动输入 {manual:{fmt}}{unit}**")
    else:
        final_val = auto_value
        st.sidebar.caption(f"当前使用: **自动 {auto_value:{fmt}}{unit}**")

    st.sidebar.info(info_md)
    return final_val


# --- 1. 巴菲特指标 ---
_buffett_info = """
**📊 历史参考阈值:**
* **历史平均 (1950-2023)**: ~100%
* **近10年平均**: ~150% (低利率环境推高)
* **2000年 泡沫峰值**: ~140%
* **2021年 历史峰值**: ~200% (极度高危)
* **当前自动获取**: 见上方 ✅ 数值
"""
buffett_ratio = _metric_block(
    "1. 巴菲特指标 (Buffett Indicator)",
    "[🔗 GuruFocus 实时值](https://www.gurufocus.com/stock-market-valuations.php) | [🔗 FRED](https://fred.stlouisfed.org)",
    "buffett", 180.0, "%", ".1f", 1.0, _buffett_info,
    help_text="巴菲特指标=美股总市值/GDP。自动源: gurufocus(免key) 或 FRED计算(需key)"
)

# --- 2. 席勒市盈率 ---
_shiller_info = """
**📊 历史参考阈值:**
* **历史平均**: ~17.0
* **近10年平均**: ~30.0
* **1929年 大萧条**: 30.0
* **2000年 互联网泡沫**: 44.2 (历史最高)
* **2021年 疫情后**: 38.6
"""
shiller_pe = _metric_block(
    "2. 席勒市盈率 (Shiller PE)",
    "[🔗 Multpl Shiller PE](https://www.multpl.com/shiller-pe)",
    "shiller", 40.0, "", ".1f", 0.1, _shiller_info,
    help_text="CAPE Ratio, 自动抓取自 multpl.com"
)

# --- 3. 收益率曲线 (2Y, 10Y由行情模块自动获取) ---
_yield_info = """
**📊 历史参考阈值:**
* **正常状态**: +0.8% ~ +2.0%
* **倒挂预警 (< 0%)**: 2000, 2007, 2019, 2022 均出现
* **解挂风险 (倒挂后回升至 > 0%)**: 最危险时刻。
"""
user_2y_yield = _metric_block(
    "3. 收益率曲线 (2Y收益率)",
    "[🔗 CNBC US2Y](https://www.cnbc.com/quotes/US2Y) | [🔗 美债收益率](https://cn.investing.com/rates-bonds/usa-government-bonds)",
    "us2y", 4.20, "%", ".2f", 0.01, _yield_info,
    help_text="2年期美债收益率。自动源: CNBC(实时)，系统将自动对比10年期"
)

# --- 4. 信用利差 (v1.3 新增) ---
_credit_info = """
**📊 历史参考阈值 (高收益债利差 HY OAS):**
* **低位 (< 3%)**: 信用市场自满, 警惕与股市高估形成背离
* **正常 (3% ~ 4%)**: 中性区间
* **紧张 (4% ~ 5%)**: 信用风险积聚
* **危险 (> 5%)**: 信用危机, 2008/2020 崩盘前均突破此位

**💡 这是与股市自身指标正交的"聪明钱"信号:** 信用市场由机构定价, 常比股市提前 1-2 个月嗅到危机。
"""
hy_oas_val = _metric_block(
    "4. 信用利差 (高收益债)",
    "[🔗 FRED HY OAS](https://fred.stlouisfed.org/series/BAMLH0A0HYM2)",
    "credit", 3.0, "%", ".2f", 0.05, _credit_info,
    help_text="高收益债信用利差(HY OAS), 自动源: FRED(需key)。崩盘前常领先股市扩大"
)
# 信用利差历史序列 (用于分位数评分)
hy_history = auto.get("credit", {}).get("history") if auto else None

# --- 5. 恐慌与贪婪指数 ---
_fg_info = "**📊 参考:** 极度贪婪 (>80) 往往是短期顶部信号；极度恐慌 (<20) 往往是底部机会。"
fear_greed_auto, fg_source, fg_is_auto = _auto_val("fear_greed", 45)

st.sidebar.subheader("5. 恐慌与贪婪指数")
st.sidebar.markdown("[🔗 CNN Fear & Greed](https://edition.cnn.com/markets/fear-and-greed)",
                    unsafe_allow_html=True)
if fg_is_auto:
    rating = auto.get("fear_greed", {}).get("rating", "")
    st.sidebar.success(f"✅ 自动获取: **{fear_greed_auto}** ({rating}) [CNN]")
else:
    err = auto.get("fear_greed", {}).get("error", "未启用") if auto else "自动获取已关闭"
    st.sidebar.warning(f"⚠️ 自动获取不可用 ({err[:40]})")
fg_override = st.sidebar.checkbox("✏️ 手动校准此指标", key="ov_fg", value=not fg_is_auto)
if fg_override:
    fear_greed = st.sidebar.slider("Fear & Greed Index (0-100)", 0, 100, int(fear_greed_auto))
else:
    fear_greed = fear_greed_auto
st.sidebar.caption(_fg_info)



# ==========================================
# 4. 风险评分模型 (v1.3: 调用 risk_model 六因子分位数模型)
# ==========================================
def calculate_risk_score(current_price, sma_200, us_10y, us_2y, buffett_val,
                         shiller_val, fear_val, weights, hy_oas_val=3.0, hy_history=None):
    """
    适配层: 把 UI 参数打包成 risk_model.calculate_risk 的输入。
    返回 (score, details_v1_format) 以兼容现有 UI 渲染代码。
    details 同时含新模型的 _meta (共振/红线信息)。
    """
    factor_inputs = {
        "buffett": buffett_val, "shiller": shiller_val, "hy_oas": hy_oas_val,
        "us_10y": us_10y, "us_2y": us_2y,
        "price": current_price, "sma200": sma_200, "fear": fear_val,
    }
    score, det = risk_model.calculate_risk(factor_inputs, weights, hy_history=hy_history)

    # 转成 UI 期望的旧格式 (title-case key -> (risk, value, status))
    ui_details = {
        'Buffett':   det['buffett'],
        'Shiller':   det['shiller'],
        'Credit':    det['credit'],
        'Yield':     det['yield'],
        'Technical': det['technical'],
        'Sentiment': det['sentiment'],
        '_meta':     det['_meta'],
    }
    return score, ui_details


# ==========================================
# 5. 历史对比数据 (NEW FEATURE)
# ==========================================
def get_historical_benchmarks():
    """
    返回历史上三次大崩盘前夕的宏观数据快照。
    注意：为了计算方便，这里直接构造模拟的 Price/SMA 使得乖离率符合当时情况。
    """
    benchmarks = {
        "2000 互联网泡沫 (Top)": {
            "desc": "March 2000",
            # 巴菲特~145%, Shiller PE~44, 利差倒挂 -0.4%
            # 信用利差: 泡沫期信用市场温和, HY OAS~4.5% (互联网泡沫主因是股权估值非信用)
            "buffett": 145.0,
            "shiller": 44.2,
            "hy_oas": 4.5,
            "us_10y": 6.2,
            "us_2y": 6.6,  # Spread -0.4
            "fear": 90,  # 极度贪婪
            "mock_price": 115, "mock_sma": 100  # 15% 乖离率
        },
        "2008 次贷危机 (Pre-Crash)": {
            "desc": "Oct 2007",
            # 巴菲特~110%, Shiller PE~27, 利差回正 +0.4% (解挂,最危险信号)
            # 信用利差: 次贷本质是信用危机, HY OAS 已开始从低位扩大 ~3.0%
            "buffett": 110.0,
            "shiller": 27.5,
            "hy_oas": 3.0,
            "us_10y": 4.6,
            "us_2y": 4.2,  # Spread +0.4 (刚刚解挂)
            "fear": 75,  # 贪婪
            "mock_price": 108, "mock_sma": 100  # 8% 乖离率
        },
        "2022 加息熊市 (Top)": {
            "desc": "Jan 2022",
            # 巴菲特~195% (ATH), Shiller PE~38, 利差 +0.8%
            # 信用利差: 加息初期信用市场仍平静, HY OAS~3.1% 低位
            "buffett": 195.0,
            "shiller": 38.3,
            "hy_oas": 3.1,
            "us_10y": 1.6,
            "us_2y": 0.8,  # Spread +0.8
            "fear": 75,
            "mock_price": 112, "mock_sma": 100  # 12% 乖离率
        }
    }
    return benchmarks


# ==========================================
# 6. 主程序逻辑
# ==========================================

# 获取数据: 行情 + 宏观数据统一来自 fetch_all (auto), 只下载一次
mkt = auto.get("market", {})
if mkt and mkt.get("df") is not None:
    df = mkt["df"]
    price = mkt["price"]
    sma200 = mkt["sma200"]
    is_mock = mkt.get("is_mock", False)
else:
    df, price, sma200, is_mock = None, 0.0, 0.0, True

# 10Y 收益率: 来自 fetch_all 降级链 (yfinance/CNBC/akshare/FRED)
us10y_item = auto.get("us10y", {})
if us10y_item.get("value") is not None:
    yield_10y = us10y_item["value"]
    us10y_source = us10y_item.get("source", "auto")
else:
    yield_10y = 4.0
    us10y_source = "默认回退"

# --- UI: 标题区 ---
st.title(f"🚨 Wall Street Quant: {ticker_symbol} 崩盘风险监测仪")

# 数据源状态总览
src_status = []
if auto:
    label_map = [("market", "行情"), ("us10y", "10Y"), ("us2y", "2Y"),
                 ("buffett", "巴菲特"), ("shiller", "Shiller"), ("credit", "信用利差"),
                 ("fear_greed", "恐慌指数")]
    ok_cnt = sum(1 for k, _ in label_map if auto.get(k, {}).get("ok"))
    total = len(label_map)
    for k, name in label_map:
        item = auto.get(k, {})
        mark = "🟢" if item.get("ok") else "🔴"
        src_status.append(f"{mark}{name}")
    st.caption(f"数据源状态 ({ok_cnt}/{total} 自动成功): " + " · ".join(src_status))

if is_mock:
    st.warning("⚠️ **演示模式**：无法连接数据源，当前使用模拟数据。")
else:
    st.success("✅ **实时连接**：行情数据源正常。")

st.markdown(
    f"**当前标的**: {ticker_symbol} | **最新价格**: ${price:.2f} | "
    f"**10年期美债收益率**: {yield_10y:.2f}% ({us10y_source})")
st.markdown("---")

if df is not None:
    # 1. 计算当前风险 (v1.3: 传入信用利差及其历史序列用于分位数)
    final_risk_score, risk_details = calculate_risk_score(
        price, sma200, yield_10y, user_2y_yield,
        buffett_ratio, shiller_pe, fear_greed,
        user_weights, hy_oas_val=hy_oas_val, hy_history=hy_history
    )
    meta = risk_details.get("_meta", {})

    # 记录当日评分到本地历史 (仅实时模式, 用于绘制风险趋势图)
    if not is_mock:
        try:
            dfetch.record_risk_score(ticker_symbol, final_risk_score)
        except Exception:
            pass  # 记录失败不影响主流程

    # 2. 计算历史基准风险 (使用当前用户权重回测历史)
    historical_data = get_historical_benchmarks()
    historical_scores = {}

    for era_name, data in historical_data.items():
        h_score, _ = calculate_risk_score(
            data['mock_price'], data['mock_sma'],
            data['us_10y'], data['us_2y'],
            data['buffett'], data['shiller'], data['fear'],
            user_weights,  # 关键：使用用户设定的权重
            hy_oas_val=data['hy_oas'], hy_history=None  # 历史时点无分位序列, 用绝对阈值
        )
        historical_scores[era_name] = h_score

    # --- 第一行: 仪表盘与建议 ---
    col1, col2 = st.columns([1, 2])
    with col1:
        fig_gauge = go.Figure(go.Indicator(
            mode="gauge+number",
            value=final_risk_score,
            title={'text': f"{ticker_symbol} 崩盘风险指数"},
            gauge={
                'axis': {'range': [0, 100]},
                'bar': {'color': "rgba(0,0,0,0)"},  # 隐藏默认指针，如果你想自定义的话，或者保留
                'steps': [
                    {'range': [0, 40], 'color': '#00cc96'},
                    {'range': [40, 70], 'color': '#ffa15a'},
                    {'range': [70, 100], 'color': '#ef553b'}
                ],
                'threshold': {
                    'line': {'color': "black", 'width': 4},
                    'thickness': 0.75,
                    'value': final_risk_score
                }
            }
        ))

        # 尝试在 Gauge 下方添加简单的历史标注文本
        # 由于Plotly Gauge添加多指针很麻烦，我们在下方用Bar Chart做对比更直观
        fig_gauge.update_layout(height=300, margin=dict(l=20, r=20, t=50, b=20))
        st.plotly_chart(fig_gauge, width="stretch")

    with col2:
        st.subheader("🤖 量化建议")
        if final_risk_score > 80:
            bg_color, title_text = "#ef553b", "极高风险 (Extreme Risk)"
            advice = f"模型显示 {ticker_symbol} 极度过热。建议大幅降低仓位，购买Put对冲，持有现金。"
        elif final_risk_score > 60:
            bg_color, title_text = "#ffa15a", "风险累积 (Elevated Risk)"
            advice = f"风险正在积聚。{ticker_symbol} 波动可能加剧，停止追高，考虑适当对冲，收紧止损线。"
        else:
            bg_color, title_text = "#00cc96", "相对安全 (Safe Zone)"
            advice = "市场处于正常波动范围。维持定投计划，关注长期价值。"

        st.markdown(f"""
        <div style="background-color: {bg_color}; padding: 20px; border-radius: 10px; color: white;">
            <h3 style="margin:0;">{title_text}</h3>
            <p style="margin-top:10px;">{advice}</p>
        </div>
        """, unsafe_allow_html=True)

        # v1.3: 共振警报 + 最大单项红线提示 (非线性风险信号)
        if meta.get("resonance"):
            st.error(f"🔴 **共振警报**: {meta['extreme_count']} 个因子同时进入历史极端区！"
                     f"多指标共振是崩盘的典型前兆，请高度警惕。")
        if meta.get("max_score", 0) >= 80:
            st.warning(f"⚠️ **单因子红线**: 「{meta['max_factor']}」风险分高达 {meta['max_score']:.0f}，"
                       f"已超过安全阈值，是当前最主要的风险来源。")

        # 新增：简易对比文本
        st.markdown("##### 🆚 历史对比参考")
        st.markdown("如果用当前的权重设置，历史大顶的风险分数为：")

        # 简单展示一行小字对比
        hist_text_cols = st.columns(3)
        idx = 0
        for name, score in historical_scores.items():
            year_label = name.split(" ")[0]  # 提取 2000, 2008 等
            with hist_text_cols[idx]:
                st.metric(label=year_label + " 峰值", value=f"{score:.0f}")
            idx += 1

    # --- 第二行: 因子详情 ---
    st.subheader("🔍 风险因子分解 (含自定义权重)")


    def get_label(name, key):
        return f"{name} (权重: {int(user_weights[key] * 100)}%)"

    # 归一化后的实际权重 (用于显示)
    _tw = sum(user_weights.values()) or 1.0

    def get_norm_w(key):
        return int(user_weights.get(key, 0) / _tw * 100)


    def _fval(key):
        """取因子显示值 (新模型返回已格式化字符串)。"""
        return risk_details[key][1]


    def _frisk(key):
        return risk_details[key][0]


    def _fstatus(key):
        return risk_details[key][2] if len(risk_details[key]) > 2 else ""


    m1, m2, m3, m4, m5, m6 = st.columns(6)

    with m1:
        st.metric(label=f"巴菲特指标 ({get_norm_w('buffett')}%)",
                  value=_fval('Buffett'), delta=f"Risk: {_frisk('Buffett')}",
                  delta_color="inverse")
    with m2:
        st.metric(label=f"席勒市盈率 ({get_norm_w('shiller')}%)",
                  value=_fval('Shiller'), delta=f"Risk: {_frisk('Shiller')}",
                  delta_color="inverse")
    with m3:
        st.metric(label=f"信用利差 ({get_norm_w('credit')}%)",
                  value=_fval('Credit'), delta=_fstatus('Credit'),
                  delta_color="off")
    with m4:
        st.metric(label=f"10Y-2Y利差 ({get_norm_w('yield')}%)",
                  value=_fval('Yield'), delta=_fstatus('Yield'),
                  delta_color="off")
    with m5:
        st.metric(label=f"均线乖离 ({get_norm_w('technical')}%)",
                  value=_fval('Technical'), delta=f"Risk: {_frisk('Technical')}",
                  delta_color="inverse")
    with m6:
        st.metric(label=f"恐慌贪婪 ({get_norm_w('sentiment')}%)",
                  value=_fval('Sentiment'), delta=f"Risk: {_frisk('Sentiment')}",
                  delta_color="inverse")

    st.markdown("---")

    # ==========================================
    # 新增模块：历史风险对比图表
    # ==========================================
    st.subheader("⚔️ 跨时代风险大比拼 (Stress Test)")
    st.caption("基于你当前设定的权重，对比**当前市场**与**历史上三次著名崩盘前夜**的风险评分。")

    # 准备绘图数据
    comparison_names = ["当前 (Now)"] + list(historical_scores.keys())
    comparison_scores = [final_risk_score] + list(historical_scores.values())

    # 颜色逻辑：根据分数变色
    bar_colors = []
    for s in comparison_scores:
        if s > 80:
            bar_colors.append('#ef553b')  # Red
        elif s > 60:
            bar_colors.append('#ffa15a')  # Orange
        else:
            bar_colors.append('#00cc96')  # Green

    # 当前选中的高亮边框
    border_colors = ['white'] + ['rgba(0,0,0,0)'] * 3
    border_widths = [2] + [0] * 3

    fig_hist = go.Figure(go.Bar(
        x=comparison_scores,
        y=comparison_names,
        orientation='h',
        text=[f"{s:.1f}" for s in comparison_scores],
        textposition='auto',
        marker=dict(color=bar_colors, line=dict(color=border_colors, width=border_widths))
    ))

    fig_hist.update_layout(
        height=300,
        margin=dict(l=20, r=20, t=20, b=20),
        template="plotly_dark",
        xaxis=dict(range=[0, 100], title="风险评分 (0-100)"),
        yaxis=dict(autorange="reversed")  # 让当前排在最上面
    )

    # 添加参考竖线
    fig_hist.add_vline(x=60, line_width=1, line_dash="dash", line_color="orange", annotation_text="警告线")
    fig_hist.add_vline(x=80, line_width=1, line_dash="dash", line_color="red", annotation_text="崩盘线")

    st.plotly_chart(fig_hist, width="stretch")

    with st.expander("ℹ️ 查看历史数据来源说明"):
        st.markdown("""
        * **2000 互联网泡沫**: 选取 2000年3月 数据。特征是极高的 Shiller PE (44+) 和 倒挂的利差。
        * **2008 次贷危机**: 选取 2007年10月 数据。特征是股市见顶，利差刚从倒挂恢复变正（经典的衰退信号）。
        * **2022 加息熊市**: 选取 2022年1月 数据。特征是巴菲特指标创历史新高 (~200%)。
        * **计算逻辑**: 使用您在侧边栏调整的权重，实时计算这些历史时刻如果套用当前模型会得多少分。
        """)

    st.markdown("---")

    # ==========================================
    # 新增模块: 风险评分趋势 + 因子贡献度
    # ==========================================
    trend_col, contrib_col = st.columns([3, 2])

    # --- 左: 风险评分时间序列 (核心: 看风险在累积还是缓解) ---
    with trend_col:
        st.subheader("📉 风险评分趋势")
        hist_df = dfetch.load_risk_history(ticker_symbol)
        if len(hist_df) >= 2:
            fig_trend = go.Figure()
            # 风险区间底色
            fig_trend.add_hrect(y0=0, y1=40, fillcolor="#00cc96", opacity=0.08, line_width=0)
            fig_trend.add_hrect(y0=40, y1=70, fillcolor="#ffa15a", opacity=0.08, line_width=0)
            fig_trend.add_hrect(y0=70, y1=100, fillcolor="#ef553b", opacity=0.08, line_width=0)
            fig_trend.add_trace(go.Scatter(
                x=hist_df["date"], y=hist_df["score"],
                mode="lines+markers", name="风险评分",
                line=dict(color="#4da6ff", width=2.5),
                fill="tozeroy", fillcolor="rgba(77,166,255,0.1)",
                marker=dict(size=5)
            ))
            fig_trend.add_hline(y=60, line_dash="dash", line_color="orange",
                                annotation_text="警告线", annotation_position="right")
            fig_trend.add_hline(y=80, line_dash="dash", line_color="red",
                                annotation_text="崩盘线", annotation_position="right")
            fig_trend.update_layout(height=320, template="plotly_dark",
                                    margin=dict(l=20, r=20, t=20, b=20),
                                    yaxis=dict(range=[0, 100], title="风险评分"),
                                    xaxis=dict(title=""))
            st.plotly_chart(fig_trend, width="stretch")
        else:
            st.info("📊 风险趋势图需要累积数据。**每次运行会自动记录当日评分**，"
                    "连续使用几天后这里将显示风险随时间的演变曲线。"
                    f"（当前已记录 {len(hist_df)} 天）")

    # --- 右: 因子贡献度 (各因子实际贡献了多少分) ---
    with contrib_col:
        st.subheader("🧩 因子贡献度")
        factor_names = {"Buffett": "巴菲特指标", "Shiller": "席勒市盈率", "Credit": "信用利差",
                        "Yield": "美债利差", "Technical": "均线乖离", "Sentiment": "恐慌贪婪"}
        weight_key = {"Buffett": "buffett", "Shiller": "shiller", "Credit": "credit",
                      "Yield": "yield", "Technical": "technical", "Sentiment": "sentiment"}
        _tw = sum(user_weights.values()) or 1.0
        contrib_names, contrib_vals = [], []
        for en, cn in factor_names.items():
            risk_val = risk_details[en][0]                    # 因子风险分 (0-100)
            w = user_weights[weight_key[en]] / _tw            # 归一化权重
            contrib_names.append(cn)
            contrib_vals.append(round(risk_val * w, 1))       # 实际贡献分

        fig_contrib = go.Figure(go.Bar(
            y=contrib_names, x=contrib_vals, orientation="h",
            text=[f"{v:.1f}" for v in contrib_vals], textposition="auto",
            marker=dict(color=contrib_vals,
                        colorscale=[[0, "#00cc96"], [0.5, "#ffa15a"], [1, "#ef553b"]],
                        cmin=0, cmax=25)
        ))
        fig_contrib.update_layout(height=320, template="plotly_dark",
                                  margin=dict(l=20, r=20, t=20, b=20),
                                  xaxis=dict(title="贡献分数"),
                                  yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig_contrib, width="stretch")
        # 红线托底/共振提示
        if meta.get("redline_floor", 0) > meta.get("weighted", 0):
            st.caption(f"⚠️ 总分已被「{meta['max_factor']}」红线托底 "
                       f"(加权{meta['weighted']} → 托底至{meta['redline_floor']})")
        else:
            st.caption("贡献分 = 因子风险分 × 归一化权重。越长/越红的条 = 当前主要风险来源。")

    st.markdown("---")

    # --- K线图 (含成交量副图 + 50日均线) ---
    from plotly.subplots import make_subplots
    st.subheader(f"📈 {ticker_symbol} 价格走势")

    # 50日均线
    df = df.copy()
    df['SMA_50'] = df['Close'].rolling(window=50).mean()

    fig_chart = make_subplots(rows=2, cols=1, shared_xaxes=True,
                              row_heights=[0.75, 0.25], vertical_spacing=0.03)
    # 主图: K线 + 均线
    fig_chart.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
        name=ticker_symbol, increasing_line_color='#00cc96', decreasing_line_color='#ef553b'
    ), row=1, col=1)
    fig_chart.add_trace(go.Scatter(
        x=df.index, y=df['SMA_50'], mode='lines', name='SMA 50',
        line=dict(color='#4da6ff', width=1.2)
    ), row=1, col=1)
    fig_chart.add_trace(go.Scatter(
        x=df.index, y=df['SMA_200'], mode='lines', name='SMA 200',
        line=dict(color='orange', width=2)
    ), row=1, col=1)
    # 副图: 成交量 (红涨绿跌配色, 美股习惯红跌绿涨 -> 这里用 close>=open 判断)
    if 'Volume' in df.columns:
        vol_colors = ['#00cc96' if c >= o else '#ef553b'
                      for c, o in zip(df['Close'], df['Open'])]
        fig_chart.add_trace(go.Bar(
            x=df.index, y=df['Volume'], name='成交量',
            marker_color=vol_colors, opacity=0.5, showlegend=False
        ), row=2, col=1)

    fig_chart.update_layout(height=520, xaxis_rangeslider_visible=False,
                            template="plotly_dark",
                            margin=dict(l=20, r=20, t=30, b=20),
                            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
    fig_chart.update_yaxes(title_text="价格", row=1, col=1)
    fig_chart.update_yaxes(title_text="成交量", row=2, col=1)
    st.plotly_chart(fig_chart, width="stretch")
