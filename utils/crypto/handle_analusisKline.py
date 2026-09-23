# -*- coding: utf-8 -*-
# @Time    : 2023/2/25 15:10
# @Author  : alvin
# @File    : handle_numpy.py
# @Software: PyCharm
import  numpy as np
# import matplotlib.pyplot as plt
# import matplotlib.finance as mpf

def testReadFile():
    filename= "../np.csv"
    c_price,volumn = np.loadtxt(
        fname=filename,
        delimiter=',',#分割符
        usecols=(4,5),#取那几列，与返回值一致
        unpack=True
    )
    print("c_price",c_price)
    print("volumn",volumn)

def testMaxAndMin():
    filename= "../np.csv"
    h_price,l_price = np.loadtxt(
        fname=filename,
        delimiter=',',
        usecols=(4,5),
        unpack=True
    )
    print(type(h_price))
    print("h_price:{}".format(h_price.max()))
    print("l_price:{}".format(l_price.min()))

def testPtp():
    #极差 自高价的价差
    filename= "../np.csv"
    h_price,l_price = np.loadtxt(
        fname=filename,
        delimiter=',',
        usecols=(2,3),
        unpack=True
    )
    print("max-min of high price:{}".format(np.ptp(h_price)))
    print("max-min of low price:{}".format(np.ptp(l_price)))

def testAvg():
    #平均数
    filename= "../np.csv"
    c_price,v = np.loadtxt(
        fname=filename,
        delimiter=',',
        usecols=(4,5),
        unpack=True
    )
    # print(c_price,v)
    print("avg price:{}".format(np.average(c_price)))
    print("成交量加权平均价:{}".format( np.average(c_price,weights=v) ) )

def testMedian():
    #收盘中位数
    filename= "../np.csv"
    c_price,v = np.loadtxt(
        fname=filename,
        delimiter=',',
        usecols=(4,5),
        unpack=True
    )
    print("c_price",c_price)
    print("median:{}".format(np.median(c_price)))

def testVar():
    #方差
    filename= "../np.csv"
    c_price,v = np.loadtxt(
        fname=filename,
        delimiter=',',
        usecols=(4,5),
        unpack=True
    )
    print("var ={}".format(np.var(c_price)))
    print("var = {}".format(c_price.var()))


def testVolarility():
    #年波段率 月
    filename= "../np.csv"
    c_price,v = np.loadtxt(
        fname=filename,
        delimiter=',',
        usecols=(4,5),
        unpack=True
    )
    log_return = np.diff(np.log(c_price))
    annual_volatility=log_return.std()/log_return.mean() * np.sqrt(250)
    monthly_volatility=log_return.std()/log_return.mean() * np.sqrt(12)
    print("log_return={}".format(log_return))
    print("annual_volatility= {}".format(annual_volatility))
    print("monthly_volatility= {}".format(monthly_volatility))

def testSma():
    #sma 5
    filename= "../np.csv"
    c_price  = np.loadtxt(
        fname=filename,
        delimiter=',',
        usecols=(2),
        unpack=True
    )
    print(c_price)
    N = 5 #5日均线
    weights = np.ones(N) /N
    print(weights)
    sma = np.convolve(weights,c_price)[N-1:-N+1]
    print(sma)
    plt.plot(sma,linewidth=5)
    plt.show()


def testExp():
    x=np.arange(5)
    y = np.arange(10)
    print("x",x)
    print("y",y)
    print("Exp x:{}".format(np.exp(x)))
    print("Exp y:{}".format(np.exp(y)))
    print("Linespace :{}".format(np.linspace(-1,0,5)))

def testEma():
    #sma 5
    filename= "../np.csv"
    c_price  = np.loadtxt(
        fname=filename,
        delimiter=',',
        usecols=(2),
        unpack=True
    )
    print(c_price)
    N = 5 #5日均线
    weights = np.exp(np.linspace(-1,0,N))
    weights =weights/ weights.sum()
    print(weights)
    ema = np.convolve(weights,c_price)[N-1:N+1]
    print(ema)
    t = np.arange(N-1,len(c_price))
    plt.plot(t,c_price[N-1:],lw=1.0)
    plt.plot(t,ema,lw=2.0)
    plt.show()

def testBi():
    #sma 5
    filename= "../../data/investment/hasbtc.csv"
    price,count,cost  = np.loadtxt(
        fname=filename,
        delimiter=',',
        usecols=(0,1,2),
        unpack=True
    )
    print(price,count,cost)
    N = 2#5日均线
    weights = np.ones(N) /N
    print(weights)
    sma = np.convolve(weights,price)[N-1:-N+1]
    print(sma,type(sma))
    plt.plot(sma,linewidth=5)
    # plt.plot(cost,linewidth=2)
    plt.show()

def testBiprice(filename="./btcbak.csv"):
    #sma 5

    price,count,cost  = np.loadtxt(
        fname=filename,
        delimiter=',',
        usecols=(0,1,2),
        unpack=True
    )
    print("testBiprice cost total  is :{}".format(np.sum(cost)))
    print("testBiprice count total is :{}".format(np.sum(count)))
    # print("testBiprice avg total is :{}".format( (np.sum(cost)/np.sum(count)) ))
    plt.ylim(14000, 25000) # 设置y轴刻度范围
    plt.plot(count,price,  color='green', marker='o', linestyle='solid')
    plt.title('btc')
    plt.xlabel('count')
    plt.ylabel('Price')
    plt.show()


def testBijihuaprice(filename="./btcbak.csv"):
    #sma 5

    price,count  = np.loadtxt(
        fname=filename,
        delimiter=',',
        usecols=(0,1),
        unpack=True
    )
    # print("testBijihuaprice price total  is :{}".format(np.sum(price)))
    print("数量count total is :{}".format(np.sum(count)))
    print("资金cost is :{}".format( np.sum(price*count)))#80000
    print("平均价 avg total is :{}".format( ((np.sum(price*count))/np.sum(count)) ))
    # plt.ylim(14000, 25000) # 设置y轴刻度范围
    # plt.plot(count,price,  color='green', marker='o', linestyle='solid')
    # plt.title('btc')
    # plt.xlabel('count')
    # plt.ylabel('Price')
    # plt.show()


if __name__ == '__main__':
    # testReadFile()
    path = "../../data/investment/jihua_eth.csv"
    testBijihuaprice(path)
