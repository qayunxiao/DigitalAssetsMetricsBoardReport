# -*- coding: utf-8 -*-
"""
EMA 指标 - 使用 APIBase 示例
展示如何利用基类简化代码
"""
from __future__ import annotations
import os
import sys
from typing import List, Optional

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from utils.api_base import APIBase

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"


class EMAIndicator(APIBase):
    """EMA 指标处理器"""
    
    DEFAULT_FAST = 5
    DEFAULT_SLOW = 10
    
    def __init__(self):
        super().__init__("EMA")
    
    def fetch_klines(
        self,
        symbol: str = "BTCUSDT",
        interval: str = "1d",
        limit: int = 500,
        end_time_ms: Optional[int] = None,
    ) -> List[List]:
        """从 Binance 拉取 K 线"""
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        if end_time_ms is not None:
            params["endTime"] = end_time_ms
            
        result = self.request_get(
            BINANCE_KLINES_URL, 
            params=params,
            timeout=30,
            delay=0.5
        )
        
        return result if isinstance(result, list) else []
    
    def calculate_ema(self, close: List[float], period: int) -> List[float]:
        """计算 EMA"""
        if not close:
            return []
            
        ema_values = []
        multiplier = 2 / (period + 1)
        
        # 使用 SMA 作为初始值
        sma = sum(close[:period]) / period
        ema_values.extend([None] * (period - 1))
        ema_values.append(sma)
        
        # 计算后续 EMA
        for i in range(period, len(close)):
            ema = (close[i] - ema_values[-1]) * multiplier + ema_values[-1]
            ema_values.append(ema)
            
        return ema_values
    
    def get_cross_signals(
        self,
        symbol: str = "BTCUSDT",
        fast: int = None,
        slow: int = None,
    ) -> dict:
        """获取金叉/死叉信号"""
        fast = fast or self.DEFAULT_FAST
        slow = slow or self.DEFAULT_SLOW
        
        klines = self.fetch_klines(symbol)
        if not klines:
            return {"error": "获取数据失败"}
        
        closes = [float(k[4]) for k in klines]
        ema_fast = self.calculate_ema(closes, fast)
        ema_slow = self.calculate_ema(closes, slow)
        
        if not ema_fast or not ema_slow:
            return {"error": "计算失败"}
        
        # 获取最近的金叉/死叉
        current_fast = ema_fast[-1]
        current_slow = ema_slow[-1]
        prev_fast = ema_fast[-2]
        prev_slow = ema_slow[-2]
        
        signal = "holding"
        if prev_fast <= prev_slow and current_fast > current_slow:
            signal = "golden_cross"  # 金叉买入
        elif prev_fast >= prev_slow and current_fast < current_slow:
            signal = "death_cross"  # 死叉卖出
            
        return {
            "symbol": symbol,
            "signal": signal,
            "ema_fast": current_fast,
            "ema_slow": current_slow,
            "price": closes[-1],
        }


# 便捷函数
def fetch_ema(symbol: str = "BTCUSDT", fast: int = 5, slow: int = 10) -> dict:
    """快速获取 EMA 信号"""
    indicator = EMAIndicator()
    return indicator.get_cross_signals(symbol, fast, slow)


if __name__ == "__main__":
    # 测试
    result = fetch_ema("BTCUSDT")
    print(result)
