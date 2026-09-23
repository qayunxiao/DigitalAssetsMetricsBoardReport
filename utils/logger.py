# -*- coding: utf-8 -*-
# @Time    : 2019/5/8 14:01
# @Author  : alvin
# @File    : logging.py
# @Software: PyCharm


import os
import sys
import time
import logging
from utils.logger_singleton import Singleton

@Singleton
class Logger:
    '''
    '''
    def __init__(self, set_level="INFO",
                 name=os.path.split(os.path.splitext(sys.argv[0])[0])[-1],
                 log_name=time.strftime("%Y-%m-%d.log", time.localtime()),
                 # log_path 使用项目根目录下的 log，与 handle_path 一致，避免在 utils 下创建 log
                 log_path=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "log"),
                 use_console=True):
        """
        :param set_level: 日志级别["NOTSET"|"DEBUG"|"INFO"|"WARNING"|"ERROR"|"CRITICAL"]，默认为INFO
        :param name: 日志中打印的name，默认为运行程序的name
        :param log_name: 日志文件的名字，默认为当前时间（年-月-日.log）
        :param log_path: 日志文件夹的路径，默认为项目根目录下的 log 文件夹
        :param use_console: 是否在控制台打印，默认为True
        """
        if not set_level:
            set_level = self._exec_type()  # 设置set_level为None，自动获取当前运行模式
        self.__logger = logging.getLogger(name)
        self.setLevel(
            getattr(logging, set_level.upper()) if hasattr(logging, set_level.upper()) else logging.INFO)  # 设置日志级别
        if not os.path.exists(log_path):  # 创建日志目录
            os.makedirs(log_path)
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        print("log_path:",log_path)
        handler_list = list()
        handler_list.append(logging.FileHandler(os.path.join(log_path, log_name)))
        if use_console:
            handler_list.append(logging.StreamHandler())
        for handler in handler_list:
            handler.setFormatter(formatter)
            self.addHandler(handler)

    def __getattr__(self, item):
        return getattr(self.logger, item)

    @property
    def logger(self):
        return self.__logger

    @logger.setter
    def logger(self, func):
        self.__logger = func

    def _exec_type(self):
        return "DEBUG" if os.environ.get("IPYTHONENABLE") else "INFO"

log = Logger()

if __name__ == "__main__":
    print(log.info("qqq"))
