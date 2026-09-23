# -*- coding: utf-8 -*-
"""
日志清理工具 - 自动清理 N 天前的日志文件
用法: python clean_logs.py [days]
默认清理 7 天前的日志
"""
import os
import sys
import glob
from datetime import datetime, timedelta

def clean_logs(log_dir, days=7):
    """清理指定目录中 N 天前的日志文件"""
    if not os.path.isdir(log_dir):
        print(f"目录不存在: {log_dir}")
        return 0
    
    cutoff = datetime.now() - timedelta(days=days)
    count = 0
    
    # 匹配 *.log 文件
    pattern = os.path.join(log_dir, "*.log")
    for log_file in glob.glob(pattern):
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(log_file))
            if mtime < cutoff:
                os.remove(log_file)
                count += 1
                print(f"已删除: {log_file}")
        except Exception as e:
            print(f"删除失败 {log_file}: {e}")
    
    return count

if __name__ == '__main__':
    # 默认清理 7 天前的日志
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    
    # 当前目录的 log/
    base_dir = os.path.dirname(os.path.abspath(__file__))
    # 从 utils/ 回退到项目根目录
    project_dir = os.path.dirname(base_dir)
    log_dir = os.path.join(project_dir, 'log')
    
    print(f"开始清理 {days} 天前的日志文件...")
    count = clean_logs(log_dir, days)
    print(f"共清理 {count} 个日志文件")
