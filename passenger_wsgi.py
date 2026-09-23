# -*- coding: utf-8 -*-
"""serv00 / Passenger 入口：公网版看板。放在**项目根目录**（`api/` 的同级）。

面板 Website type = python 时，Passenger 用「Interpreter path」那个解释器 import 本文件，取模块级
`application` 处理请求。它不监听端口、不起 HTTP 服务（那是本地版 main.py 的事），所以面板里的
「Ports / 15888」这条链路和本站点无关，见 README 第 7.2 节。

启动流程刻意做成「布局无关 + 失败可诊断」：

1. `_find_root()` 从本文件所在目录向上四层、再向下探 `public`/`public_python`/`public_html`/`www`，
   第一个「其下有 `api/app.py`」的目录就是项目根（serv00 把 app root 设成哪一层都认）。可用环境
   变量 `BOARD_ROOT` 强制指定。
2. 找不到根，或者导入／装配阶段抛异常，都不让 Passenger 端出现「空白 500／nginx 默认页」——
   `application` 换成 `_broken()`，把实际 `__file__`、cwd、解释器、试过的路径和目录清单用纯文本
   回给浏览器，照着它搬文件即可。

与本地版的差异有两处（见 api/core.py 的 _static/dispatch）：
1. 静态文件只放 .html/.css/.js/.svg/.ico，config.ini、api/*.py、logs/、data/ 顺着 URL 也拿不到；
2. 清空代理：config.ini 的 [proxy] 是本机 127.0.0.1:3067，服务器上不存在那个出口，留着只会全部取数
   失败。如果哪天服务器自己有了出口代理，删掉上面两行赋值即可。
持仓报告两个按钮本机版／公网版行为一致：点就跑 cryptoTrader 脚本（每日次数上限见 config.ini
[report] daily_limit），不设访问凭据——2026-09-22 用户定的口径。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SUBDIRS = ("public", "public_python", "public_html", "www")
TRIED = []                                  # _find_root() 依次试过的候选根，诊断页要打印


def _find_root():
    """返回第一个其下有 api/app.py 的目录；找不到返回 None。"""
    del TRIED[:]
    cands = [os.environ.get("BOARD_ROOT") or "", HERE]
    p = HERE
    for _ in range(4):                      # Passenger 可能把 app root 设在外层
        p = os.path.dirname(p)
        cands.append(p)
    for base in list(cands):                # 也可能设在内层的 docroot
        if base:
            cands.extend(os.path.join(base, sub) for sub in SUBDIRS)
    for c in cands:
        if c and c not in TRIED:
            TRIED.append(c)
            if os.path.isfile(os.path.join(c, "api", "app.py")):
                return c
    return None


ERR = None
ROOT = _find_root()

os.environ["PUBLIC"] = "1"
os.environ["HTTPS_PROXY"] = ""
os.environ["HTTP_PROXY"] = ""
# 上传到服务器的 config.ini 里 [report] 那台 Windows 解释器路径在公网版用不到（report 路由没注册）；
# [log] dir 若是 Windows 绝对路径只会让日志目录创建失败，core 会降级为仅控制台，不影响取数。

if ROOT:
    try:
        # 两条都要：api/ 让 `import app`/`import core` 找得到模块（api/*.py 之间是平铺互相 import），
        # ROOT 让 `from api import xxx` 这种包路径找得到——本地版由解释器自动把项目根塞进 sys.path[0]
        # 所以感觉不到，Passenger 的 app root 常在 public_python 那层，少了这里就是 ModuleNotFoundError: api。
        # 根这一条排到最后而不是插到 0：站点根上还有 utils/、main.py 这些同名目录/文件，抢到最前会去遮掉第三方包。
        if ROOT not in sys.path:
            sys.path.append(ROOT)
        sys.path.insert(0, os.path.join(ROOT, "api"))
        import app                                          # noqa: E402
        import core                                         # noqa: E402
        app.build(warm=False)     # 每进程都预热 = 重复打上游，交给首个请求按需取
        application = core.wsgi_app                          # Passenger 认的固定名字
    except Exception as exc:                                 # noqa: BLE001
        ERR = "%s: %s（来自 %s:%s）" % (
            exc.__class__.__name__, exc,
            os.path.basename(getattr(exc, "filename", "") or "?"),
            getattr(exc, "lineno", "?"))
        ROOT = None

if not ROOT:
    def _listing(d):
        try:
            names = sorted(os.listdir(d))
        except OSError as exc:
            return "读不了（%s）" % exc.__class__.__name__
        shown = names[:30]
        tail = "" if len(names) <= 30 else " … 另有 %d 项" % (len(names) - 30)
        return "%d 项：%s%s" % (len(names), ", ".join(shown), tail)

    def application(environ, start_response):                # noqa: N802
        """部署位置不对／装配失败时的兜底响应：把布局事实用纯文本回出来。"""
        out = ["数字资产指标看板 · 公网版未启动（这是部署问题，不是取数失败）", ""]
        if ERR:
            out += ["装配时报错：%s" % ERR, ""]
        out += [
            "本文件实际位置 : %s" % __file__,
            "Passenger cwd  : %s" % os.getcwd(),
            "解释器         : %s (api %s)" % (sys.executable, sys.version.split()[0]),
            "",
            "判据：下面任一层里要有 api/app.py 这个文件：",
        ]
        out += ["  %s" % c for c in TRIED]
        out += ["", "%s 的内容：%s" % (HERE, _listing(HERE))]
        parent = os.path.dirname(HERE)
        out += ["%s 的内容：%s" % (parent, _listing(parent))]
        out += ["", "修法：把整个包（含 api/、staic/、config.ini、passenger_wsgi.py）解到上面某一层，",
                "或把面板的 Directory 指向真正的项目根；然后 touch ~/domains/<域名>/tmp/restart.txt。"]
        body = ("\n".join(out) + "\n").encode("utf-8")
        start_response("200 OK", [("Content-Type", "text/plain; charset=utf-8"),
                                  ("Content-Length", str(len(body)))])
        return [body]
