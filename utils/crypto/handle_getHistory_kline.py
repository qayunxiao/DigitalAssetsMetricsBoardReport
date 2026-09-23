# -*- coding: UTF-8 -*-
import csv
import datetime
import os

import ccxt
import pandas as pd
import time

# Python 3.5.3+ 中支持使用 asyncio 和 async/await 的并发异步模式
# import ccxt.async_support as ccxt
from utils.handle_path import project_path, data_ccxt_path
from utils.operationConfig import OperationConfig


def get_data(symbol = 'BTC/USDT'):
    tmp_data_ccxt_path = os.path.join(project_path,'data','ccxt_binance_tmpdata')
    tmp_filename = symbol.split('/')[0]+'_tmp.csv'
    tmp_file_path = os.path.join(tmp_data_ccxt_path,tmp_filename)
    # print("tmp_file_path",tmp_file_path)
    history_ccxt_tmppath = os.path.join(project_path,'data','ccxt_binance_historydata')
    history_filename = symbol.split('/')[0]+'_history.csv'
    history_data_path = os.path.join(history_ccxt_tmppath,history_filename)
    print("history_data_path",history_data_path)

    my_ccxt_tmppath = os.path.join(project_path,'data','ccxt_binance_data')
    my_filename = symbol.split('/')[0]+'.csv'
    my_data_path = os.path.join(my_ccxt_tmppath,my_filename)
    print("my_data_path",my_data_path)

    delay = 3  # seconds
    _proxies = OperationConfig().get_proxy_config()
    binance_exchange = ccxt.binance({
        'timeout': 15000,
        'enableRateLimit': True,
        **({'proxies': _proxies} if _proxies else {}),
    })
    # symbol = 'BTC/USDT'
    print("symbol",symbol)
    # 交易所数据结构
    print('交易所id：', binance_exchange.id,'交易所名称：', binance_exchange.name)
    print('是否支持共有API：', binance_exchange.has['publicAPI'],'是否支持私有API：', binance_exchange.has['privateAPI'])
    print('支持的时间频率：', binance_exchange.timeframes,'交易所当前时间：', binance_exchange.iso8601(binance_exchange.milliseconds()))
    print('最长等待时间(s)：', binance_exchange.timeout / 1000 , '访问频率(s)：', binance_exchange.rateLimit / 1000)
    # 交易所数据结构

    # 加载市场数据
    binance_markets = binance_exchange.load_markets()
    # 支持的交易对
    markets_list=list(binance_markets.keys())

    #获取全部币种盘口信息
    # for all_symbol in binance_exchange.markets:
    #     #print(binance_exchange.fetch_order_book(all_symbol))
    #     time.sleep(delay)


    # 获取指定交易对市场信息
    btc_usdt_market = binance_markets[symbol]
    #     #print("btc_usdt_market",btc_usdt_market)

    # 获取单个交易对ticker数据fetchTickers
    ticker_data = binance_exchange.fetch_ticker(symbol)
    #     #print("ticker_datamarket",ticker_data)
    print('Ticker时刻：', ticker_data['datetime'])
    print('Ticker价格：', ticker_data['last'])

    # 转换UTC时间
    print('Ticker数据开始时间：', binance_exchange.iso8601(ticker_data['info']['openTime']))
    print('Ticker数据结束时间：', binance_exchange.iso8601(ticker_data['info']['closeTime']))

    # 交易委托账本数据获取
    binance_exchange.fetch_order_book(symbol)
    # 获取上一次访问交易所的时间
    #     binance_exchange.last_response_headers['Date']
    orderbook = binance_exchange.fetch_order_book(symbol)
    # 最高买价
    bid = orderbook['bids'][0][0] if len (orderbook['bids']) > 0 else None
    # 最低卖价
    ask = orderbook['asks'][0][0] if len (orderbook['asks']) > 0 else None
    # 价差
    spread = (ask - bid) if (bid and ask) else None
    # 市场行情
    #print ('买价：{:.2f}, 卖价：{:.2f}, 价差：{:.2f}'.format(bid, ask, spread))
    # K线数据数据获取
    binance_exchange.fetch_ohlcv(symbol, timeframe='1d')
    if binance_exchange.has['fetchOHLCV']:
        print(binance_exchange.fetch_ohlcv(symbol, timeframe='1d'))

    #1636473600000  1607529600000
    if ( ((symbol.split('/')[0]) == 'BTC') or ((symbol.split('/')[0]) == 'ETH') ) :
        kline_data = binance_exchange.fetch_ohlcv(symbol, timeframe='1d',since=1672502400000)
    elif (  ((symbol.split('/')[0]) == 'DOT')): #20211104 历史数据含有
        kline_data = binance_exchange.fetch_ohlcv(symbol, timeframe='1d',since=1672502400000)
    elif (  ((symbol.split('/')[0]) == 'LTC')):#20210510 历史数据含有
        kline_data = binance_exchange.fetch_ohlcv(symbol, timeframe='1d',since=1672502400000)
    elif (  ((symbol.split('/')[0]) == 'FIL')):#20210401 历史数据含有
        kline_data = binance_exchange.fetch_ohlcv(symbol, timeframe='1d',since=1672502400000)
    elif (  ((symbol.split('/')[0]) == 'AGIX')): #之前高点数据单独处理
        kline_data = binance_exchange.fetch_ohlcv(symbol, timeframe='1d',since=1672502400000)
    elif ( ((symbol.split('/')[0]) == 'SNX')):#
        kline_data = binance_exchange.fetch_ohlcv(symbol, timeframe='1d',since=1593964800000)
    elif ( ((symbol.split('/')[0]) == 'LINK')):#
        kline_data = binance_exchange.fetch_ohlcv(symbol, timeframe='1d',since=1680019200000)
    else:
        kline_data = binance_exchange.fetch_ohlcv(symbol, timeframe='1d',since=1672502400000)

    #  处理数据格式 时间戳毫秒改日期格式
    kline_df = pd.DataFrame(kline_data,columns = ["time","open","high","low","close","vol"] )
    #to_datetime  将时间戳毫秒转日期 -unit='ms'
    kline_df['date'] = pd.to_datetime(kline_df['time'], unit='ms')
    # kline_df = pd.DataFrame(kline_data)
    print("kline_df_tail",kline_df.tail(2))
    print("kline_df_head",kline_df.head(2))


#存储数据 判断tmp文件是否存在，如果存在就删除
    if os.path.exists(tmp_file_path):  # 判断文件是否存在
        os.remove(tmp_file_path)
        # print("tmp file exists is:",os.path.exists(tmp_file_path))
        time.sleep(1)
        kline_df.to_csv (tmp_file_path, mode="a" ,index = False, header=True,encoding='utf-8')
    else:
        # print("not exists")
        kline_df.to_csv (tmp_file_path, mode="a" ,index = False, header=True,encoding='utf-8')
    # print("获取tmp文件:{}成功".format(tmp_file_path))
    #获取orderbook
    order_book= binance_exchange.fetch_order_book(symbol)
#     #print("order_book",order_book['bids'])

    df1 = pd.read_csv(tmp_file_path)
    # df1["来自文件"] = "tmp"
    df2 = pd.read_csv(history_data_path)
    # df2["来自文件"] = "history"
    df = pd.concat([df2,df1])
    df.drop_duplicates()  #数据去重
    df.to_csv(my_data_path,encoding='utf-8') #合并历史与tmp文件
    # fr1 = open(history_data_path,'r',encoding='utf-8').read()
    # fr2 = open(tmp_file_path,'r',encoding='utf-8').read()
    # with open(my_data_path,'a',encoding='utf-8') as f:
    #     f.write(fr1)
    #     f.write('\n')
    #     f.write(fr2)
    print("concat_csv {} over ".format(my_data_path))


if __name__ == '__main__':
    symbol = 'LINK/USDT'
    get_data(symbol)
    # concat_csv()