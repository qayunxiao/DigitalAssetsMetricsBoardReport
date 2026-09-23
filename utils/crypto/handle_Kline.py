# -*- coding: UTF-8 -*-
# @Time    : 2023/2/25 15:10
# @Author  : alvin
# @File    : handle_numpy.py
# @Software: PyCharm
import os
import time
from decimal import Decimal

import  numpy as np
# import matplotlib.pyplot as plt
# import matplotlib.finance as mpf
from utils.handle_log import log
from utils.handle_path import data_ccxt_path, project_path


class dealdata():

    def __init__(self,filename='BTC_ALL.csv'):
        self.token = filename.split('.')[0]
        self.filename = os.path.join(data_ccxt_path,filename)
        self.low_list = []
        self.low_price_info=[]
        self.date_str=time.strftime('%Y年%m月%d日')
        # print("filename is {}".format(self.filename))

    def testReadFile(self):
        id,time,open,high,low,close,vol = np.loadtxt(
            fname=self.filename,
            delimiter=',',#分割符
            skiprows = 1, #跳过指定的行
            usecols=(0,1,2,3,4,5,6),#取那几列，与返回值一致,从0开始
            unpack=True
        )
        # print(id,time,open,high,low,close,vol)
        for i in low:
            self.low_list.append(i)
        print(self.low_list[-1])

    #获取最新报价数据
    def getLowDay(self):
        time,open,high,low,close,vol = np.loadtxt(
            fname=self.filename,
            delimiter=',',#分割符
            skiprows = 1, #跳过指定的行
            usecols=(1,2,3,4,5,6),#取那几列，与返回值一致,从0开始
            unpack=True
        )
        #把价格加入到list中，取最后一个数据即可
        for i in low:
            self.low_list.append(i)
        return self.low_list[-1]

    #获取成交量数据
    def getvoldata(self):
        times,open,high,low,close,vol = np.loadtxt(
            fname=self.filename,
            delimiter=',',#分割符
            skiprows = 1, #跳过指定的行
            usecols=(1,2,3,4,5,6),#取那几列，与返回值一致,从0开始
            unpack=True
        )
        print("目前为止平均成交量:{}".format(Decimal(np.average(vol)).quantize(Decimal("0.00"))))
        # log.info("目前为止平均成交量:{}".format(Decimal(np.average(vol)).quantize(Decimal("0.00"))))
        # print("median成交量:{}".format(np.median(vol[0])))
        max_list_time=[]
        max_list_high=[]
        max_list_close=[]
        # print("最高成交量:{}".format(np.max(vol)))
        re = np.where( vol == np.max(vol) )
        # print(re[0][0],type(re[0][0]))
        lines=int(re[0][0])
        # print(time[362,:])
        for i in times:
            # print("i",i)
            max_list_time.append(i)
        for h in high:
            # print("h",h)
            max_list_high.append(h)
        for c in close:
            # print("c",c)
            max_list_close.append(c)
        date_vales=str((str(max_list_time[lines])).split(".")[0])
        timeStamp = int(date_vales[0:10])
        timeArray = time.localtime((timeStamp ))
        # print("timeArray",timeArray)
        max_date = time.strftime("%Y年%m月%d日", timeArray)
        print("成交量最高时间:{},最高价:{},收盘价:{},最高成交量:{}个,累计平均成交量:{}个".format(max_date,max_list_high[lines],max_list_close[lines],(Decimal(np.max(vol)).quantize(Decimal("0.00"))),(Decimal(np.average(vol)).quantize(Decimal("0.00"))) ))
        log.info("成交量最高时间:{},最高价:{},收盘价:{},最高成交量:{}个,累计平均成交量:{}个".format(max_date,max_list_high[lines],max_list_close[lines],(Decimal(np.max(vol)).quantize(Decimal("0.00"))),(Decimal(np.average(vol)).quantize(Decimal("0.00"))) ))

#获取最低价格一组数据
    def getLowPricInfo(self):
        time,open,high,low,close,vol = np.loadtxt(
            fname=self.filename,
            delimiter=',',#分割符
            skiprows = 1, #跳过指定的行
            usecols=(1,2,3,4,5,6),#取那几列，与返回值一致,从0开始
            unpack=True
        )
        print("历史最低价:{}".format(low.min(-1)))


    def testMaxAndMin(self):
        high,low = np.loadtxt(
            fname=self.filename,
            delimiter=',',
            skiprows = 1, #跳过指定的行
            usecols=(3,4),
            unpack=True
        )
        low_day= self.getLowDay()
        # print("low_day",low_day)
        # print("历史最高价:{}".format(high.max()))
        # print("历史最低价:{}".format(low.min()))
        # print("历史最大跌幅:{}".format( round((high.max()-low.min()) / high.max(),2)  ))
        # print("当前价格:{},历史最高到当前跌幅:{}".format( low_day,round( ((high.max()-low_day) / high.max()) ,2) )  )
        log.info("历史最高价:{},历史最低价:{},历史最大跌幅:{}%".format(high.max(),low.min(), (round((high.max()-low.min()) / high.max(),4)*100)  ))
        dvalue=(high.max()-low_day) / high.max()
        log.info("当前价格:{},历史最高到当前跌幅:{}%".format( low_day,(Decimal(dvalue).quantize(Decimal("0.00")))*100) )
        # log.info("最高价极差:%.2f" %(np.ptp(h_price))) Decimal(dvalue).quantize(Decimal("0.0000"))

    def testPtp(self):
        #极差 自高价的价差
        h_price,l_price = np.loadtxt(
            fname=self.filename,
            delimiter=',',
            usecols=(3,4),
            skiprows = 1, #跳过指定的行
            unpack=True
        )
        # print("最高价极差:","%.2f" %(np.ptp(h_price)))
        log.info( "最高价极差:%.2f" %(np.ptp(h_price)) +" 最低价极差:%.2f" %(np.ptp(l_price)) )
        print("最高价极差:%.2f" %(np.ptp(h_price)) +" 最低价极差:%.2f" %(np.ptp(l_price)))
        # print("最低价极差:","%.2f" %(np.ptp(h_price)))
        # log.info("最低价极差:%.2f" %(np.ptp(l_price)))
        # print("最低价极差:{}".format(np.ptp(l_price)))
        # print("成交量加权平均价:","%.2f" %np.average(close,weights=vol) )



    def testAvg(self):
        #平均数
        close,vol = np.loadtxt(
            fname=self.filename,
            delimiter=',',
            skiprows = 1, #跳过指定的行
            usecols=(5,6),
            unpack=True
        )
        # print(c_price,v)
        # print("avg price:{}".format(np.average(c_price)))
        # print("成交量加权平均价:{}".format( np.average(close,weights=vol) ) )
        # print("成交量加权平均价:","%.2f" %np.average(close,weights=vol) )
        log.info("成交量加权平均价:%.2f" %np.average(close,weights=vol) )

    def testMedian(self):
        #收盘中位数
        # print("testMedian filename",self.filename)
        c_price,v = np.loadtxt(
            fname=self.filename,
            delimiter=',',
            skiprows = 1, #跳过指定的行
            usecols=(5,6),
            unpack=True
        )
        # print("type",type(np.median(c_price)))
        # print("收盘中位数:{}".format(np.median(c_price)))
        # print("token",self.token)
        if (self.token == 'BTC') :
            # print("{}:2021年11月10日最高点69000，到今天".format(self.token))
            log.info( "币安 {}:2021年11月10日最高点69000,到今天{}".format(self.token,self.date_str) )
        elif (self.token== 'ETH') :
            # print("{}:2021年11月10日最高点4868，到今天".format(self.token))
            log.info( "币安 {}:2021年11月10日最高点4868,到今天{}".format(self.token,self.date_str ))
        elif (self.token == 'DOT') :
            # print("{}:2021年11月04日最高点55，到今天".format(self.token))
            log.info( "币安 {}:2021年11月04日最高点55,到今天:{}".format(self.token,self.date_str) )
        elif (self.token == 'LTC') :
            # print("{}:2021年05月10日最高点413，到今天".format( self.token ))
            log.info( "币安 {}:2021年05月10日最高点413,到今天{}".format(self.token,self.date_str) )
        elif (self.token == 'AGIX') :
            # print("{}:2023年03月01日最高点0.56，到今天".format(self.token ))
            log.info( "币安 {}:2023年03月01日最高点0.56,到今天{}".format(self.token,self.date_str) )
        elif (self.token == 'SNX') :
            log.info( "币安 {}:2020年07月09日币安上线,到今天{}".format(self.token,self.date_str) )
        elif (self.token == 'LINK') :
            log.info( "币安 {}:2021年05月10日最高点52.9,到今天{}".format(self.token,self.date_str) )
        elif (self.token == 'UNI') :
            log.info( "币安 {}:2021年05月03日最高点45,到今天{}".format(self.token,self.date_str) )
        elif (self.token == 'ICP') :
            log.info( "币安 {}:2021年05月10日最高点776,到今天{}".format(self.token,self.date_str) )
        else:
            log.info( "币安 {}: 到今天{}".format(self.token,self.date_str) )
        # print("收盘中位数:","%.2f" %np.median(c_price))
        log.info("收盘中位数:%.2f" %np.median(c_price) +"  成交量加权平均价:%.2f" %np.average(c_price,weights=v))
        print("收盘中位数:%.2f" %np.median(c_price) +"  成交量加权平均价:%.2f" %np.average(c_price,weights=v))

    def testVar(self):
        #方差
        c_price,v = np.loadtxt(
            fname=self.filename,
            delimiter=',',
            skiprows = 1, #跳过指定的行
            usecols=(4,5),
            unpack=True
        )
        #
        print("var ={}".format(np.var(c_price)))
        print("var ={}".format(c_price.var()))


    def testVolarility(self):
        #年波段率 月
        c_price,v = np.loadtxt(
            fname=self.filename,
            delimiter=',',
            usecols=(4,5),
            skiprows = 1, #跳过指定的行
            unpack=True
        )
        log_return = np.diff(np.log(c_price))
        annual_volatility=log_return.std()/log_return.mean() * np.sqrt(250)
        monthly_volatility=log_return.std()/log_return.mean() * np.sqrt(12)
        print("log_return={}".format(log_return))
        print("annual_volatility= {}".format(annual_volatility))
        print("monthly_volatility= {}".format(monthly_volatility))

    def testSma(self):
        c_price  = np.loadtxt(
            fname=self.filename,
            delimiter=',',
            skiprows = 1, #跳过指定的行
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


    def testExp(self):
        x=np.arange(5)
        y = np.arange(10)
        print("x",x)
        print("y",y)
        print("Exp x:{}".format(np.exp(x)))
        print("Exp y:{}".format(np.exp(y)))
        print("Linespace :{}".format(np.linspace(-1,0,5)))

    def testEma(self):
        c_price  = np.loadtxt(
            fname=self.filename,
            delimiter=',',
            usecols=(2),
            skiprows = 1, #跳过指定的行
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

    def testBi(self):
        #sma 5
        price,count,cost  = np.loadtxt(
            fname=self.filename,
            delimiter=',',
            usecols=(0,1,2),
            skiprows = 1, #跳过指定的行
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

    def testBiprice(self):
        time,open,high,low,close,vol = np.loadtxt(
            fname=self.filename,
            delimiter=',',#分割符
            skiprows = 1, #跳过指定的行
            usecols=(1,2,3,4,5,6),#取那几列，与返回值一致,从0开始
            unpack=True
        )
        # print("testBiprice cost total  is :{}".format(np.sum(cost)))
        # print("testBiprice count total is :{}".format(np.sum(count)))
        # print("testBiprice avg total is :{}".format( (np.sum(cost)/np.sum(count)) ))
        # plt.ylim(14000, 70000) # 设置y轴刻度范围
        plt.plot(vol,close,  color='green', marker='o', linestyle='solid')
        plt.title('btc')
        plt.xlabel('vol')
        plt.ylabel('close')
        plt.show()


if __name__ == '__main__':
    my_ccxt_tmppath = os.path.join(project_path,'data','ccxt_binance_data')
    my_filename = 'BTC.csv'
    my_data_path = os.path.join(my_ccxt_tmppath,my_filename)
    dealdatatest = dealdata( filename=my_data_path )
    # dealdatatest.getLowPricInfo()
    # dealdatatest.testMedian()
    # dealdatatest.testAvg()
    # dealdatatest.testPtp()
    # dealdatatest.testMaxAndMin()
    dealdatatest.testBi()
