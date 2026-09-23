# -*- coding: utf-8 -*-
# AHR999 指标：从 config.ini [url] API_ARH999NEW 拉取 coinsoto getAhr999Table 表格数据，落盘 AHR.csv。
# 代理使用 [proxy]；API key 为 API_ARH999NEW_KEY。用于抄底/定投区间参考（如 <0.45 抄底）。
import json
import os
from decimal import Decimal

import numpy as np
from dateutil import rrule
from datetime import datetime

import time
import csv

import requests

from utils.handle_path import data_ccxt_path
from utils.handle_log import log
from utils.operationConfig import OperationConfig

REQUEST_TIMEOUT = 15


class get_api_ahr999new():
    """AHR999 新版 API：从 https://coinsoto.com/zh/indexdata/ahrIndex 获取 AHR999 表格数据。"""

    def __init__(self):
        self.proxies = OperationConfig().get_proxy_config()
        self.confdata = OperationConfig().get_apiinfo()
        self.ahr999_count = {}
        self.ahr999_datadict = {}
        self.filepath = os.path.join(data_ccxt_path, "AHR.csv")
        self.url = self.confdata['api_arh999new']
        self.key = self.confdata['api_arh999new_key']
        self.headers = {
            "authority": "coinsoto.com",
            "method": "GET",
            "path": "/indicatorapi/getAhr999Table",
            "scheme": "https",
            "accept-encoding": "gzip, deflate, br",
            "content-type": "application/json",
            "cookie": "i18n_redirected=zh; _ga=GA1.1.913694702.1691644431; kindTips=true; _ga_BDEPVNN1SX=GS1.1.1692844410.3.0.1692844419.0.0.0",
            "user-agent": 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.198 Safari/537.36'
        }

    def get_ahr_table(self):
        """请求 getAhr999Table 接口，返回完整 JSON；非 200 时返回 None。"""
        res = requests.get(url=self.url, proxies=self.proxies, headers=self.headers, timeout=REQUEST_TIMEOUT)
        if res.status_code == 200:
            return res.json()
        log.warning("get_ahr_table 请求异常: status=%s, url=%s", res.status_code, self.url)
        return None


if __name__ == '__main__':
    a = get_api_ahr999new()
    data = a.get_ahr_table()
    if data and 'data' in data:
        print(data['data'])
    else:
        print("get_ahr_table 返回为空或异常")
