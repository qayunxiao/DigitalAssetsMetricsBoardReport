# -*- coding: utf-8 -*-
# 项目路径与配置路径：基于 utils 所在位置推导工程根目录，供 config、data、log 等使用。
# 任意入口只要先 import utils.handle_path，即可得到统一的 project_path / config_path。
import os

# 工程根目录（utils 的上一级）
project_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
print(project_path)

# 主配置文件，各模块读钉钉/TG/代理等均用此路径
config_path = os.path.join(project_path, 'config', 'config.ini')
print(config_path)

# 数据与日志目录
data_ccxt_path = os.path.join(project_path, 'data', 'ccxt_binance_data')
data_investment_path = os.path.join(project_path,'data','investment')
data_job_path = os.path.join(project_path,'data','job_data')
# print("data_ccxt_path",data_ccxt_path)

# log 目录：不存在则创建，避免 FileHandler 报错
log_path = os.path.join(project_path, r'log')
if not os.path.isdir(log_path):
    os.makedirs(log_path, exist_ok=True)


def get_newlogfile():
    """返回 log 目录下按修改时间排序后的最新一个日志文件路径；目录为空时返回占位路径。"""
    if not os.path.isdir(log_path):
        os.makedirs(log_path, exist_ok=True)
    lists = os.listdir(log_path)
    print("log_path", log_path)
    if not lists:
        file_new = os.path.join(log_path, "crypto_placeholder.log")
        print(file_new)
        return file_new
    lists.sort(key=lambda fn: os.path.getmtime(os.path.join(log_path, fn)))  # 按时间排序，兼容 Windows
    file_new = os.path.join(log_path, lists[-1])                     #获取最新的文件保存到file_new
    print(file_new)
    return file_new

if __name__ == '__main__':
    test=get_newlogfile()
