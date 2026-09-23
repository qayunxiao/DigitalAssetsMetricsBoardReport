# -*- coding: UTF-8 -*-
"""
恐慌贪婪指数（Alternative.me）：拉取历史数据落盘 FEAR.csv，并统计极度恐慌(≤24)/极度贪婪(≥75)天数占比。
配置：config.ini [url] API_FEAR 为接口地址。策略参考：别人恐慌我贪婪（抄底）、别人贪婪我恐慌（减仓）。
"""
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

# 英文月份缩写 -> 数字（用于解析 API 返回日期）
MONTH_MAP = {
    'Jan': '1', 'Feb': '2', 'Mar': '3', 'Apr': '4', 'May': '5', 'Jun': '6',
    'Jul': '7', 'Aug': '8', 'Sep': '9', 'Oct': '10', 'Nov': '11', 'Dec': '12'
}
REQUEST_TIMEOUT = 15


class get_api_fear():
    """获取并处理恐慌贪婪指数（alternative.me），支持写 CSV 与按起止日统计。"""

    def __init__(self):
        self.confdata = OperationConfig().get_apiinfo()
        self.current_fear_value = []
        self.filepath = os.path.join(data_ccxt_path, "FEAR.csv")
        self.url = self.confdata['api_fear']
        self.headers = {
            "authority":"alternative.me",
            "method":"POST",
            "path":"/api/crypto/fear-and-greed-index/history",
            "scheme":"https",
            "accept":"gzip, deflate, br",
            "accept-encoding":"zh-CN,zh;q=0.9",
            "content-length":"11",
            "content-type": "application/json",
            "cookie":'i18n_redirected=zh; _ga=GA1.1.913694702.1691644431; kindTips=true; _ga_BDEPVNN1SX=GS1.1.1692844410.3.1.1692844526.0.0.0',
            "origin":"https://alternative.me",
            "referer": self.url,
            "sec-ch-ua":"?0",
            "sec-fetch-dest":"empty",
            "sec-fetch-site":" same-origin",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.88 Safari/537.36",
        }

    def count_days(self):
        """计算从 2017-12-10 到今天的自然日天数，供 API 的 days 参数使用。"""
        firstDay = datetime(2017, 12, 10)
        endDay = datetime(datetime.now().year, datetime.now().month, datetime.now().day)
        days = rrule.rrule(freq=rrule.DAILY, dtstart=firstDay, until=endDay)
        return days.count()

    def get_fear(self):
        """请求 alternative.me 接口，返回 (恐惧值列表, 日期标签列表)。"""
        self.day_count = self.count_days()
        data = {"days": self.day_count}
        res = requests.post(url=self.url, json=data, timeout=REQUEST_TIMEOUT)
        res.raise_for_status()
        # API 返回 data.datasets[0].data（数值序列）与 data.labels（日期字符串）
        data_fear = res.json()['data']['datasets'][0]['data']
        data_date = res.json()['data']['labels']
        return data_fear, data_date

    def write_fear_data(self):
        """拉取恐慌指数并写入 CSV：列 date(时间戳)、fear值、日期。日期格式为 API 返回的英文月名，需转成 dd-mm-yyyy 再转时间戳。"""
        data_fear, data_date = self.get_fear()
        if os.path.exists(self.filepath):
            os.remove(self.filepath)
        with open(self.filepath, "w", newline='', encoding='utf-8') as csv_f:
            fieldnames = ['date', 'fear值', '日期']
            writer = csv.DictWriter(csv_f, fieldnames=fieldnames)
            writer.writeheader()
            for i in range(len(data_fear)):
                fear = data_fear[i]
                date_d = data_date[i].split(",")
                date_d = date_d[0] + date_d[1].replace(' ', '-')
                for en, num in MONTH_MAP.items():
                    date_d = date_d.replace(en, num)
                time_array = time.strptime(date_d, '%d-%m-%Y')
                timestamp = int(time.mktime(time_array))
                dict_tmp = {"date": str(timestamp), "fear值": fear, "日期": str(date_d)}
                writer.writerow(dict_tmp)

    def get_current_fear_value(self):
        """返回最近一次 deal_fear_data_all 填充的当日/前一日恐慌值列表。"""
        if self.current_fear_value:
            return self.current_fear_value
        return None

    def deal_fear_data_all(self, skipdays):
        """
        从 CSV 按 skiprows 加载恐惧指数，统计极度恐慌/极度贪婪占比，并更新 self.current_fear_value。
        :param skipdays: '2017-12-17' 表示从 2018-02-01 起算（skiprows=1），否则从 2021-11-10 起算（skiprows=1377）
        """
        log.info("恐慌指数说明:0-24极度恐慌,25-29恐惧,50-74贪婪,75-100极度贪婪，最好策略别人恐慌我贪婪，牛转熊注意，别人贪婪我恐慌")
        skiprows = 1 if skipdays == '2017-12-17' else 1377
        fear_list = []
        # CSV 列：date(时间戳), fear值；skiprows 控制从哪次牛市/起点开始统计
        dates, fear = np.loadtxt(
            fname=self.filepath,
            delimiter=',',
            skiprows=skiprows,
            usecols=(0, 1),
            unpack=True,
            encoding='utf-8',
        )
        count_min = 0
        count_max = 0
        count_total = 0
        for i in fear:
            count_total = count_total + 1
            fear_list.append(i)
            if i <= 24:
                count_min = count_min + 1
            if i >= 75:
                count_max = count_max + 1
        if len(self.current_fear_value) == 0:
            # print("f",self.current_fear_value)
            # print(fear_list[-1],fear_list[-2])
            self.current_fear_value.append(fear_list[-1])
            self.current_fear_value.append(fear_list[-2])
        if fear_list[-1] < 24:
            log.warning("今日恐慌指数:{},请结合AHR999分析是否抄底".format(fear_list[-1]))
            print("今日恐慌指数:{},请结合AHR999分析是否抄底".format(fear_list[-1]))
        if skipdays == '2017-12-17':
            print( "恐慌指数:从2018年2月1日到今天最高点计算,极度恐慌:{},平均恐慌情绪:{},极度贪婪:{},今日恐慌指数:{}".format(fear.min(),( round(np.average(fear),2)  ),(fear.max()),(fear_list[-1]) )    )
            print( "恐慌指数:从2018年2月1日开始到今天,数据总数:{},其中低于24的极度恐慌次数:{},占比:{}%,其中高于75的极度贪婪次数:{},占比:{}%".format(count_total,count_min,((Decimal((count_min/count_total)).quantize(Decimal('0.00')))*100),count_max,((Decimal((count_max/count_total)).quantize(Decimal('0.00')))*100) ))
            log.info( "恐慌指数:从2018年2月1日到今天最高点计算,极度恐慌:{},平均恐慌情绪:{},极度贪婪:{},今日恐慌指数:{}".format(fear.min(),( round(np.average(fear),2)  ),(fear.max()),(fear_list[-1]) )    )
            log.warning("恐慌指数:从2018年2月1日开始到今天,数据总数:{},其中低于24的极度恐慌次数:{},占比:{}%,其中高于75的极度贪婪次数:{},占比:{}%".format(count_total,count_min,((Decimal((count_min/count_total)).quantize(Decimal('0.00')))*100),count_max,((Decimal((count_max/count_total)).quantize(Decimal('0.00')))*100) ))
        else:
            print( "恐慌指数:从2021年11月10日到今天最高点计算,极度恐慌:{},平均恐慌情绪:{},极度贪婪:{},今日恐慌指数:{}".format(fear.min(),( round(np.average(fear),2)),(fear.max()),(fear_list[-1]) )    )
            print( "恐慌指数:从2021年11月10日开始到今天,数据总数:{},其中低于24的极度恐慌次数:{},占比:{}%,其中高于75的极度贪婪次数:{},占比:{}%".format(count_total,count_min,((Decimal((count_min/count_total)).quantize(Decimal('0.00')))*100),count_max,((Decimal((count_max/count_total)).quantize(Decimal('0.00')))*100) ))
            log.info( "恐慌指数:从2021年11月10日到今天最高点计算,极度恐慌:{},平均恐慌情绪:{},极度贪婪:{},今日恐慌指数:{}".format(fear.min(),( round(np.average(fear),2)  ),(fear.max()),(fear_list[-1]) )    )
            log.error( "恐慌指数:从2021年11月10日开始到今天,数据总数:{},其中低于24的极度恐慌次数:{},占比:{}%,其中高于75的极度贪婪次数:{},占比:{}%".format(count_total,count_min,((Decimal((count_min/count_total)).quantize(Decimal('0.00')))*100),count_max,((Decimal((count_max/count_total)).quantize(Decimal('0.00')))*100) ))


if __name__ == '__main__':
    resapi = get_api_fear()
    # resapi.count_days() startDay='2017-12-17'
    resapi.write_fear_data()
    startDay='2017-12-17'
    resapi.deal_fear_data_all(skipdays=startDay)
    startDay='2021-11-10'
    resapi.deal_fear_data_all(skipdays=startDay)
    fear_value=resapi.get_current_fear_value()

