# -*- coding: utf-8 -*-
"""
牛市峰值信号指标：从 coinank 页面抓取「牛市峰值信号」表格，用于辅助判断牛顶风险。
"""
import requests
from bs4 import BeautifulSoup
import pandas as pd

# 请求超时（秒）
REQUEST_TIMEOUT = 10


def get_bull_market_indicators():
    """从 coinank 获取牛市峰值信号表格，解析为 DataFrame；失败返回 None。"""
    url = "https://coinank.com/zh/BullMarketPeakSignals"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3",
        "Connection": "keep-alive"
    }

    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        # 表格选择器需随站点结构变化调整（当前为 class='table'）
        table = soup.find('table', class_='table')

        if not table:
            print("未找到指标表格，请检查页面结构是否有变化")
            return None

        # 提取表头
        col_headers = [th.get_text(strip=True) for th in table.find_all("th")]

        # 提取表格数据
        data = []
        for row in table.find_all("tr")[1:]:
            row_data = [td.get_text(strip=True) for td in row.find_all("td")]
            if row_data:
                data.append(row_data)

        df = pd.DataFrame(data, columns=col_headers)
        return df

    except requests.exceptions.RequestException as e:
        print(f"请求发生错误: {e}")
        return None
    except Exception as e:
        print(f"处理数据时发生错误: {e}")
        return None


if __name__ == "__main__":
    # 获取指标数据
    indicators_df = get_bull_market_indicators()
    print("start ....")
    if indicators_df is not None:
        print("成功获取牛市峰值信号指标数据：")
        print(indicators_df)

        # 可选：保存为CSV文件
        indicators_df.to_csv('bull_market_indicators.csv', index=False, encoding='utf-8-sig')
        print("数据已保存到 bull_market_indicators.csv 文件")
