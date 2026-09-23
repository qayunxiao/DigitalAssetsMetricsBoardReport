# -*- coding: utf-8 -*-
# 项目统一日志：单例 log 写入 log/crypto_YYYYMMDD_HHMM.log；flag=True 写文件，False 仅控制台。
import datetime
import os
import logging


def logger(flag=True, name=__name__):
    """
    创建或返回 Logger。flag=True 时输出到当日时分命名的 log 文件，False 时仅 StreamHandler 控制台。
    """
    project_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    print("project_path", project_path)
    log_path = os.path.join(project_path, 'log')
    if not os.path.isdir(log_path):
        os.makedirs(log_path, exist_ok=True)
    logDir = os.path.join(log_path, ("{}_{}.log".format('crypto', datetime.datetime.now().strftime('%Y%m%d_%H%M'))))
    logObject = logging.getLogger(name)
    logObject.setLevel(logging.INFO)
    fmt = '%(asctime)s - %(levelname)s - %(filename)s[%(lineno)d]:%(message)s'
    format = logging.Formatter(fmt)

    print("logDir", logDir)
    if flag:
        #设置日志渠道-文件方式
        handle = logging.FileHandler(logDir,encoding='utf-8')
        #日志内容渠道绑定
        handle.setFormatter(format)
        #日志对象跟渠道绑定
        logObject.addHandler(handle)
    else:
        #设置日志渠道-控制台方式
        handle = logging.StreamHandler()
        #日志内容渠道绑定
        handle.setFormatter(format)
        #日志对象跟渠道绑定
        logObject.addHandler(handle)

    return logObject

#单例模式，对象有，不重复创建
log = logger()

if __name__ == '__main__':
    # print(os.path.join(log_path,("{}.log".format(datetime.datetime.now().strftime('%Y%m%d%H%M')))))
    log.info("qatest")

