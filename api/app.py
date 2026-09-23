# -*- coding: utf-8 -*-
"""服务装配：本地版（main.py）与公网版（../passenger_wsgi.py）共用的唯一一处注册表。

两个入口注册的路由**完全相同**：公网版既不把持仓报告整条摘掉，也不给它加访问凭据
（2026-09-22 用户两次改口径后的最终结论）。PUBLIC 驱动的区别只剩静态扩展名白名单与代理规则。
"""
import core


def build(warm=True):
    """注册四个模块并初始化日志。warm=False 用于 WSGI：Passenger 会起多个进程，
    每进程都在启动时打一轮上游只会重复打源（且拖慢冷启动），交给首个请求按需取数。
    liquidity 与 btc 的 warm 只在本地版跑：前者预热 ccxt 的 load_markets，后者逐项预热各上游（项数看 btc.INDICATORS）。"""
    import liquidity
    import crash
    from api import allocation
    import btc
    import db

    core.register("liquidity", liquidity.ROUTES, liquidity.warm if warm else None)
    core.register("crash", crash.ROUTES)
    core.register("allocation", allocation.ROUTES)
    core.register("btc", btc.ROUTES, btc.warm if warm else None)
    core.register("db", db.ROUTES)       # 可选落库层的只读自述（/api/db/health），不打上游也不写库
    core.setup_logging()
    return core
