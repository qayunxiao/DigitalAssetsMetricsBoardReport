"""Telegram 出站通知：零依赖，只用标准库。

凭据在 `config.ini` 的 `[TG]` 段（2026-09-24 由用户明示以明文提交进这个**公开**仓库，来龙去脉与
后果写在该文件末尾那段注释里）。值经 `api/core.py` 的 `apply_config()` 填成环境变量后由这里读取，
顺序仍是**环境变量 > config.ini**，所以临时换一个机器人不必改文件：`set TG_BOT_TOKEN_QA=…`。

两个机器人（都从 `indicator.ini` 搬过来，那份现在只是出处项目的凭据副本）：
  QA    = my_qacrypto_bot   → TG_BOT_TOKEN_QA    / TG_CHAT_ID_QA
  ALVIN = my_hascrypto_bot  → TG_BOT_TOKEN_ALVIN / TG_CHAT_ID_ALVIN

出口与全站同一条：`core.PROXY`（`[proxy]` 段，非 Windows 不读那一段，服务器上走 `HTTPS_PROXY`）。
Telegram 的 IP 白名单是按**服务器**算的，换出口会让 bot 被拒，别在这里另开一条通路。

命令行（**默认一条都不发**，别把默认改成发）：
  python api/notify.py                                 对两个 bot 各问一次 getMe（只读，问 bot 自己的
                                                       名字，不给任何群发消息），只看配置齐不齐
  python api/notify.py --text "要发的内容"               同上，外加把文本与目标打印出来预览，仍不发
  python api/notify.py --send --bot QA --text "内容"     真发一条，落到 QA 那个群里 —— 这条有副作用
  python api/notify.py --btc                            跑一遍 BTC 极值口径：取数 + 挑命中的卡 + 把正文
                                                       打印出来，并说明会不会被闸门挡；**不发**
  python api/notify.py --btc --send                     真发（给 `[notify] tg_bot` 那个机器人，`--bot` 可覆盖）
  python api/notify.py --btc --send --force             跳过「同一业务日只发一条」和每日额度（手工重发用）
  python api/notify.py --html-alert                     跑一遍指标日报：顶部 [html_alert_top] + 底部
                                                       [html_alert_bottom] **两段都判**（同一次取数，两段的
                                                       条件并成一张表的相邻两列），打出「当前实际值 + 设置的
                                                       条件 + ✓/✗」那张等宽表格 + 说清「真到 cron 那一刻会不会
                                                       被闸门挡」；**不发、不记账**，所以随时可以跑来看数
  python api/notify.py --html-alert-top                 表里只出顶部那一段的条件列（--html-alert-bottom 只出底部）
  python api/notify.py --html-alert --send              真发一条日报（cron 挂这条；**与触不触发无关，每天一条**）
  python api/notify.py --html-alert --send --force      跳过「不早于 ALERT_AT」和「一个日历日只发一条」（手工补发用）
  python api/notify.py --status                          只看本地那几条发送记录 + 两段的生效阈值
                                                        （不打网络，最安全的自检）

BTC → TG 的触发口径（2026-09-24 与用户定下的这一套，改就改下面三个常量与 `[notify]`）：
  · 只看 `BTC_WATCH` 那四张卡（有明确极值档的才是它们：通道 / 恐慌贪婪 / AHR999 / CBBI），
    判据就是卡片自己算好的 `tone`，`green`（底部档）或 `red`（顶部档）算触发 —— **本模块不重算任何阈值**；
  · 一次事件 = 一条消息：命中几张就列几张，不是一张卡发一条；
  · 闸门一「同一业务日只发一条」：去重键是 `(机器人, 业务日)`，业务日取命中项里最新的 `asof`；
  · 闸门二「每日上限」：`[notify] daily_limit`（默认 1），按**日历日**记在 `data/notify_state.json`；
  · 收件人：`[notify] tg_bot`（默认 QA）。
两个闸门都只在 `--send` 时才消费额度，预览跑一百遍也不会把当天的额度吃掉。
`data/notify_state.json` 只留**最近一条**已发记录：同一天换成第二个机器人再发，第一个机器人的「同业务日已发」
就查不到了（日历日额度仍然管着）。真要让两个群各收一条，把 `daily_limit` 调到 2 并知道这是拿去重换的。

`--html-alert` 是**另一条独立链路**（2026-09-24 用户要的功能：每天定点盯那三张卡），与上面那套极值播报互不影响。
它现在的口径是**指标日报**（同一天用户第三次改口径）：**不管有没有触发阈值，每天固定发一条**，
正文是一张等宽表格 —— 一行一张卡，「当前实际值 + 数据日期」一列，两段各自「设置的条件 + ✓/✗」各占一列：
  · `[html_alert_top]`「可能顶部」= AHR999 ≤ `AHR999_MAX`、恐慌贪婪 ≥ `FEAR_GREED_MIN`、2年MA乘数通道的
    **日线收盘** > 同一根上的支撑 730MA；`[html_alert_bottom]`「可能底部」= AHR999 ≤ `AHR999_MAX`、
    恐慌贪婪 ≤ `FEAR_GREED_MAX`、**日线收盘** < 支撑 730MA。每段要求同时命中几项由该段的 `ALERT_HITS` 说
    （默认 3 = 三项共振）。**同一次取数、两段并成一条消息**，头条每段各写一行「命中几/几、要求几 → 触发/未触发」。
    于是 `ALERT_HITS` 从此**只影响正文里那句结论**，不再是「发不发」的开关 —— 两段互相矛盾的那两列现在同表并排，
    读的人一眼看得出「同一个数在两个方向上各是什么判定」，不再需要来回翻两条消息。
  · 阈值与每天的时刻都在根目录 `indicator.ini` 的对应段里 —— 这是全站**唯一**一处判级数值放在 ini 里，
    因为用户明示要「改配置不改代码」；顺序仍是 环境变量（`HTML_ALERT_TOP_*` / `HTML_ALERT_BOTTOM_*`）
    > 该段 > 本模块 `ALERT_SPEC[...]["defaults"]`。那份文件他会手改，要引用这几个数就先重读文件，别照抄代码默认。
  · 取数与页面同源（`btc.summary()`，**永不穿透上游缓存**：cron 每分钟拉起一次，穿透会把上游打爆）；
    本模块只比大小，不重算指标、不补估算值 —— 取不到数的那项**既不算满足、也照样占该段 `ALERT_HITS` 的额**
    （写着 3 就要三项都成立才算触发），表格里那一格是 `—`、末尾单列进「缺口」。改成日报之后缺数不再会让
    整条链哑掉（照发，只是结论是「未触发」），但别在代码里给缺数硬编一个判定。
  · 闸门两条，**都走在取数前面**（`--send` 那条被挡时连上游都不打）：① 不早于各段 `ALERT_AT`（留空 = 不限时刻，
    两段都写时刻时取较晚的那个 —— 早段没到点就整条不发，否则两列里会有一列是旧数）；
    ② 日报一个日历日只发一条 —— 这是日报**唯一**的防刷屏闸门（每天必发，所以闸门只能是「一天一条」）。
    记在 `data/notify_html_state.json` 那**一本**（与 --btc 那份各记各的，互不消耗；两段也共用一本，
    因为它们本来就在同一条消息里）。**预览一条都不记**，
    看一眼配置就把当天该发的日报哑掉，是最坏的一种手滑；真发失败同样不记，下一分钟的 cron 自己再试。
    收件人取 `[notify] tg_bot`（`--bot` 可覆盖），但**不消耗** `[notify] daily_limit`（那条只管 --btc）。
  · 时刻按跑脚本那台机器的本地时区解释，本机与 serv00 不一定同一小时，配置段里写了怎么核对。

为什么把「发」做成显式 `--send`：2026-09-23 有过一次，探针按「接口回 501 就是没实现」的假设去打
持仓报告，结果那功能当天正好落地，三条 Telegram 就这么发出去了。这里的默认值就是为了让那种事
不再发生：**不传 `--send` 时本模块不会向 bot API 发 `sendMessage`**，只发只读的 `getMe`。
"""
import json
import os
import re
import unicodedata
import urllib.parse
import urllib.request
from datetime import date, datetime

from core import PROXY, ROOT, indicator_get, log, short_err

TG_API = "https://api.telegram.org/bot%s/%s"
TEXT_LIMIT = 4096                                      # sendMessage 的硬上限，超了直接 400
BOTS = {"QA": ("TG_BOT_TOKEN_QA", "TG_CHAT_ID_QA"),
        "ALVIN": ("TG_BOT_TOKEN_ALVIN", "TG_CHAT_ID_ALVIN")}

# BTC 极值播报（口径见模块注释）。这三行是「策略」，不是运行参数，所以写在代码里：
# 换哪张卡进观察名单 = 改这一行并提交，`config.ini` 只管发给谁、一天最多几条。
BTC_WATCH = ("two_year_multiply", "fear", "ahr999", "cbbi")
HOT_TONES = ("green", "red")                           # 卡片自己的极值档；gray=中性，bad=取数失败
STATE_FILE = os.path.join(ROOT, "data", "notify_state.json")
DEFAULT_BOT_ENV = "NOTIFY_TG_BOT"
DAILY_LIMIT_ENV = "NOTIFY_DAILY_LIMIT"


def cfg_bot():
    """`[notify] tg_bot`，没配就回空串（**不猜默认机器人**，见 `bot_cfg`）。"""
    return (os.environ.get(DEFAULT_BOT_ENV) or "").strip().upper()


def daily_limit():
    try:
        return max(1, int(os.environ.get(DAILY_LIMIT_ENV) or 1))
    except ValueError:
        return 1


def fmt_val(item):
    """卡片上那个数就按卡片自己的 `dp` 打，不在这儿另立一套精度或单位口径。

    `unit` 里两种东西混着写：`美元`/`倍` 是量纲（拼在数后面读得通），`0~100` 是**量程**——它跟在数后面
    就成了「710~100」这种读不通的串（恐慌贪婪与 CBBI 两张卡都中招），所以带 `~` 的一律不进正文。"""
    if item.get("text"):
        return str(item["text"])
    v, dp = item.get("value"), item.get("dp")
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return "—" if v is None else str(v)
    num = format(v, ",.%df" % dp) if isinstance(dp, int) and dp >= 0 else str(v)
    unit = item.get("unit") or ""
    return num + (unit if "~" not in unit else "")


def btc_summary(force=False):
    """真取一次数（走 `api/btc.py` 各卡自己的 TTL 与磁盘日缓存）。

    只在 `--btc` 这条路径上 import：`btc` 一进来就会把整条取数链、线程池和落库旁路都带起来，
    而「我只想看配置齐不齐」那次（默认路径）不该顺手打上游。"""
    import btc
    return btc.summary(force=force)


def btc_alerts(items):
    """观察名单里 `tone` 落在极值档的卡，顺序按 `BTC_WATCH`（不是页面顺序，播报要稳定可读）。"""
    by = {i.get("key"): i for i in items or []}
    return [by[k] for k in BTC_WATCH if by.get(k) and by[k].get("tone") in HOT_TONES]


def biz_date(hits):
    """业务日 = 命中项里最新的那个 `asof`（日线指标通常是昨天）；全都没有就退回今天。

    用 asof 而不是用「跑脚本那天」当去重键，是因为上游可能一整天不更新：那样每次刷新都会
    被当成新的一天，同一条极值能在群里刷成一串。"""
    ds = [i.get("asof") for i in hits if i.get("asof")]
    return max(ds) if ds else date.today().isoformat()


def btc_text(hits, items, biz):
    """正文：头条是「几张触发」，下面逐张列，末尾一句把没触发的与失败的交代清楚。

    全是卡片已经算好的字段（`name`/`value`/`verdict`/`asof`/`src`），这里不做任何二次计算。"""
    by = {i.get("key"): i for i in items or []}
    lines = ["我爱大饼 · BTC 极值提示 %s（%d 项触发）" % (biz, len(hits))]
    for it in hits:
        lines.append("· %s：%s｜%s（asof %s · %s）"
                     % (it.get("name"), fmt_val(it), it.get("verdict"),
                        it.get("asof") or "—", it.get("src") or "—"))
    flat = [by[k]["name"] for k in BTC_WATCH
            if by.get(k) and by[k].get("ok") and by[k].get("tone") not in HOT_TONES]
    bad = [by[k]["name"] for k in BTC_WATCH if by.get(k) and not by[k].get("ok")]
    lines.append("未触发：%s；取数失败：%s" % ("、".join(flat) or "无", "、".join(bad) or "无"))
    return "\n".join(lines)


def _state(path=None):
    """读那条发送记录；`path` 不给就是极值播报的 `data/notify_state.json`（--html-alert 用自己的那份）。"""
    try:
        with open(path or STATE_FILE, encoding="utf-8") as f:
            j = json.load(f)
        return j if isinstance(j, dict) else {}
    except (OSError, ValueError):
        return {}                                      # 没文件/半截文件 = 今天还没发过


def gate(bot, biz, force=False):
    """→ `(能发, 原因)`。两道闸门：同业务日去重、按日历日计数的每日上限；`--force` 把它们一起跳过。"""
    st = _state()
    today = date.today().isoformat()
    if force:
        return True, "（--force：跳过两道闸门，仍然会记一笔已发）"
    if st.get("bot") == bot and st.get("biz_date") == biz:
        return False, "业务日 %s 已经给 %s 发过一条了（%s，message_id=%s）——要重发加 --force" \
               % (biz, bot, st.get("sent_at"), st.get("message_id"))
    used = (st.get("count") or 0) if st.get("day") == today else 0
    lim = daily_limit()
    if used >= lim:
        return False, "%s 今日额度 %d/%d 已用完（限额见 [notify] daily_limit）" % (bot, used, lim)
    return True, ""


def _consume(bot, biz, message_id, path=None, fired=True):
    """记一笔已发。**只在真发成功之后写**，失败不计数，否则一次网络抖动就把当天的额度白白烧掉。

    `fired=False` 是给日报那条链的「各段阈值全被停用、今天没东西可报」用的：同样占掉当天，cron 每分钟拉起时
    一天只会打上游一次。`message_id` 那格在没发时写空，读记录的人一眼看得出是没发而不是发了没记上。"""
    p = path or STATE_FILE
    st = _state(p)
    today = date.today().isoformat()
    rec = {"day": today,
           "count": ((st.get("count") or 0) if st.get("day") == today else 0) + (1 if fired else 0),
           "bot": bot, "biz_date": biz, "message_id": message_id if fired else None,
           "sent": bool(fired), "sent_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False)
    os.replace(tmp, p)                                 # 原子替换，与 report_quota.json 同一写法


def run_btc(do_send=False, bot=None, force=False):
    """BTC 极值播报的完整一条链：取数 → 挑卡 → 组正文 → 过闸门 → （可选）发。返回退出码。

    形参叫 `do_send` 不叫 `send`：模块级那个 `send()` 是真发信的函数，同名形参会把它盖掉。"""
    bot = (bot or cfg_bot() or "").strip().upper()
    out = btc_summary(force=force)
    if not out.get("ok"):
        print("BTC 取数全部失败，没什么可播的：%s" % (out.get("error") or out.get("failed")))
        return 1
    hits = btc_alerts(out.get("items"))
    print("观察名单 %s，取数 %d/%d 项有数，用时 %sms"
          % (" / ".join(BTC_WATCH), out["count"]["ok"], out["count"]["total"], out.get("elapsed_ms")))
    by = {i.get("key"): i for i in out.get("items") or []}
    for k in BTC_WATCH:
        i = by.get(k) or {}
        print("  %-18s %-6s %-14s %s" % (k, i.get("tone"), fmt_val(i),
                                          i.get("verdict") or i.get("error") or ""))
    if not hits:
        print("\n没有一项落在极值档 —— 按口径就是「不播」，不发任何消息（宁可不发，也不把中性区刷成日常播报）。")
        return 0
    biz = biz_date(hits)
    text = btc_text(hits, out.get("items"), biz)
    print("\n触发 %d 项（业务日 %s），正文 %d 字：\n%s\n" % (len(hits), biz, len(text), text))
    if not bot:
        print("没配发给谁：--bot QA 指定，或在 config.ini 的 [notify] tg_bot 写死。一条都没发。")
        return 2
    ok, why = gate(bot, biz, force)
    if not ok:
        print("闸门：%s（没发）。" % why)
        return 0
    if why:
        print(why)
    if not do_send:
        print("预览模式，**一条都没发**（要发到 %s 加 --send）。" % bot)
        return 0
    r = send(text, bot)
    if r.get("ok"):
        _consume(bot, biz, r.get("message_id"))
        print("已发送 bot=%s chat=%s message_id=%s" % (bot, bot_cfg(bot)[2], r.get("message_id")))
    else:
        print("发送失败 bot=%s：%s（这次不计入额度）" % (bot, r.get("error")))
    return 0 if r.get("ok") else 1


# ============================== 页面指标日报（--html-alert）==============================
# 阈值住在根目录 `indicator.ini` 的 `[html_alert_top]` / `[html_alert_bottom]` 两段（2026-09-24 用户明示：
# 这几档要能改配置不改代码，连每天几点跑也一样；同一天第二次改口径：顶部底部拆成两段各自判、各自发；
# 同一天第三次改口径：**不管触没触发，每天固定发一条「当前值 + 各段阈值」的合并日报**，见 `alert_report`）。
# 这是全站**唯一**一处判级数值放在 ini 里的地方——其余口径仍在代码常量，见 Qoder.md。
# 判定读的是 `api/btc.py` 那三张卡自己的头条值（与 staic/btc.html 上看到的一模一样），本模块只比大小、不重算指标。

ALERT_SECTS = ("top", "bottom")
# 每段 = 一份 indicator.ini 配置节 + 一个 env 前缀 + 一组判定项（日报是**一条链一本账**，见 `ALERT_STATE`）。
# `items` 四元组 = (ini 里的键, api/btc.py 的卡 key, 正文里的标签, 判定方向)：
#   `<=` / `>=` 比数值阈值；`above` / `below` 比「日线收盘 vs 同一根上的支撑 730MA」（这项没有数值阈值，1=启用/留空=停用）。
# 两段顺序、条数必须一致（日报的表格按位置把两段并到同一行），改一段就两段一起改。
ALERT_SPEC = {
    "top": {
        "sect": "html_alert_top", "env": "HTML_ALERT_TOP", "title": "可能顶部",
        "items": (("AHR999_MAX", "ahr999", "AHR999 定投指数", "<="),
                  ("FEAR_GREED_MIN", "fear", "恐慌贪婪指数", ">="),
                  ("TWM_CLOSE_ABOVE_SUPPORT", "two_year_multiply", "2年MA乘数通道", "above")),
        "defaults": {"ALERT_AT": "08:10", "ALERT_HITS": "3", "AHR999_MAX": "0.57",
                     "FEAR_GREED_MIN": "70", "TWM_CLOSE_ABOVE_SUPPORT": "1"},
    },
    "bottom": {
        "sect": "html_alert_bottom", "env": "HTML_ALERT_BOTTOM", "title": "可能底部",
        "items": (("AHR999_MAX", "ahr999", "AHR999 定投指数", "<="),
                  ("FEAR_GREED_MAX", "fear", "恐慌贪婪指数", "<="),
                  ("TWM_CLOSE_BELOW_SUPPORT", "two_year_multiply", "2年MA乘数通道", "below")),
        "defaults": {"ALERT_AT": "08:10", "ALERT_HITS": "3", "AHR999_MAX": "0.4",
                     "FEAR_GREED_MAX": "25", "TWM_CLOSE_BELOW_SUPPORT": "1"},
    },
}
# 日报当天的那本账：一条消息两列判定，所以只有一本（不再各段各记，否则「顶部评过」会把底部一起挡在门外，
# 而现在两段本来就在同一条消息里）。旧的 `notify_html_top_state.json` / `..._bottom_state.json` 就此停用。
ALERT_STATE = os.path.join(ROOT, "data", "notify_html_state.json")
ALERT_MARK = {"hit": "✓", "miss": "✗", "gap": "—", "off": "·"}


def _alert_env(which, key):
    """该段某个键对应的环境变量名：`ALERT_AT` → `HTML_ALERT_TOP_AT`（时刻那条不带键名，读起来像人话，
    也是 `alert_cron.sh` 与 indicator.ini 注释里写死的那两个名字），其余键 → `HTML_ALERT_TOP_<键>`。
    改这一行的口径必须同时改 `alert_cron.sh` 那两条 export —— 对不上就是「脚本设空了个没人读的变量，
    ini 里的时刻照样生效」，2026-09-24 离线自检抓到的正是这个形状。"""
    p = ALERT_SPEC[which]["env"]
    return "%s_AT" % p if key == "ALERT_AT" else "%s_%s" % (p, key)


def alert_cfg(which):
    """该段各键的生效值：**环境变量 > indicator.ini 的那一段 > `ALERT_SPEC[which]["defaults"]`**。

    env 名见 `_alert_env`（`HTML_ALERT_TOP_AHR999_MAX` / `HTML_ALERT_BOTTOM_FEAR_GREED_MAX`…），
    两段共用同名键（`AHR999_MAX`、`ALERT_HITS`、`ALERT_AT`）靠前缀区分，不再用以前那个不带段的 `HTML_ALERT_*`。
    值为空串原样返回（那是他显式停用本项），不会被默认值顶回来；只有键根本不存在才落默认。
    env 那一侧默认按「设了但设空 = 没设」处理，与 `apply_config()` 同一规矩 —— **只有 `ALERT_AT` 例外**：
    它在 ini 里留空的语义本来就是「不设时刻」（见 `alert_gate`），所以设空也照这个语义走。
    `alert_cron.sh` 靠这个口子把「几点跑」整个交给 crontab 那五个字段，脚本自己不再判时刻。"""
    sp = ALERT_SPEC[which]
    out = {}
    for k in ("ALERT_AT", "ALERT_HITS") + tuple(i[0] for i in sp["items"]):
        ev = os.environ.get(_alert_env(which, k))
        if k == "ALERT_AT" and ev is not None:
            out[k] = ev.strip()                      # 显式设空 = 不设时刻；有值则覆盖 ini
            continue
        ev = (ev or "").strip()
        out[k] = ev if ev else indicator_get(sp["sect"], k, sp["defaults"][k])
    return out


def _fnum(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _fthr(s):
    """阈值字符串 → float。空串或写坏一律回 None，调用方按「本项停用」处理（并在输出里说清楚）。"""
    try:
        return float(str(s).strip())
    except (TypeError, ValueError):
        return None


def _hhmm(s):
    """`hh:mm` → `(时, 分)`；不是这个格式或超出 0~23 / 0~59 回 None（**不猜**，宁可不发）。"""
    m = re.match(r"^(\d{1,2}):(\d{2})$", str(s or "").strip())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    return (h, mi) if h < 24 and mi < 60 else None


def alert_band_last(item):
    """通道卡 `bands` 里最后一根「收盘与支撑同时有数」的 → `(asof, 收盘, 支撑)`；整列都不齐回三个 None。

    往前找到第一根齐的为止：Yahoo 的收盘序列会缺根（实测缺过 2026-09-23），末行偶发 `px=None` 时退到
    最近一根齐的来比是安全的（两条价本来就取在**同一天**，缺的只是那一天本身），但绝不跨过去外推或估算，
    整列都不齐就是缺数据。正文里会带上这一根的日期，读的人知道比的是哪天。"""
    for r in reversed(item.get("bands") or []):
        px, lo = _fnum(r.get("px")), _fnum(r.get("lo"))
        if px is not None and lo is not None:
            return r.get("d"), px, lo
    return None, None, None


def alert_checks(cfg, items, which):
    """该段的逐项判定 → `(checks, needed)`。每项 `{key,label,cur,thr,asof,state[,why]}`，
    `state` 取 hit（满足）/ miss（不满足）/ gap（取不到数，**既不算满足也不算不满足**）/ off（本项停用）；
    `needed` = 要求命中的项数，只在「启用」的项里算——**gap 仍然占额**：写着 3 就要三项都成立才算这一段触发
    （宁缺不估）。日报本身照发（缺的那一项在表里是 `—`，缺口单列一行），所以缺数不会把当天整条哑掉，
    只会让那一段的结论是「未触发」。"""
    by = {i.get("key"): i for i in items or []}

    def num_item(key, label, thr_s, op):
        thr = _fthr(thr_s)
        if thr is None:
            return {"key": key, "label": label, "cur": "—", "thr": "—（本项停用：值为空或写坏）",
                    "asof": None, "state": "off"}
        cond = "%s %s" % (op, format(thr, "g"))
        it = by.get(key) or {}
        if not it:
            return {"key": key, "label": label, "cur": "—", "thr": cond, "asof": None,
                    "state": "gap", "why": "响应里没有这张卡"}
        if not it.get("ok"):
            return {"key": key, "label": label, "cur": "取不到", "thr": cond, "asof": None,
                    "state": "gap", "why": str(it.get("error") or "该卡取数失败")[:90]}
        v = _fnum(it.get("value"))
        if v is None:
            return {"key": key, "label": label, "cur": str(it.get("value"))[:20], "thr": cond,
                    "asof": it.get("asof"), "state": "gap", "why": "头条值不是数"}
        return {"key": key, "label": label, "cur": fmt_val(it), "thr": cond, "asof": it.get("asof"),
                "state": "hit" if (v <= thr if op == "<=" else v >= thr) else "miss"}

    def band_item(on_s, direction, label="2年MA乘数通道"):
        key = "two_year_multiply"
        sw = _fthr(on_s)
        if sw is None or sw <= 0:
            return {"key": key, "label": label, "cur": "—",
                    "thr": "—（本项停用：TWM_CLOSE_%s_SUPPORT 非 1）" % ("ABOVE" if direction == "above" else "BELOW"),
                    "asof": None, "state": "off"}
        it = by.get(key) or {}
        cond = "收盘 %s 支撑730MA" % (">" if direction == "above" else "<")
        if not it:
            return {"key": key, "label": label, "cur": "—", "thr": cond, "asof": None,
                    "state": "gap", "why": "响应里没有这张卡"}
        if not it.get("ok"):
            return {"key": key, "label": label, "cur": "取不到", "thr": cond, "asof": None,
                    "state": "gap", "why": str(it.get("error") or "该卡取数失败")[:90]}
        d, px, lo = alert_band_last(it)
        if px is None:
            return {"key": key, "label": label, "cur": "—", "thr": cond, "asof": None, "state": "gap",
                    "why": "bands 里没有一根同时有收盘与支撑（Yahoo 收盘或 looknode 通道缺数）"}
        return {"key": key, "label": label,
                "cur": "收盘$%s｜支撑$%s" % (format(px, ",.0f"), format(lo, ",.0f")),
                "thr": cond, "asof": d, "state": "hit" if (px > lo) == (direction == "above") else "miss"}

    checks = []
    for k, card, label, op in ALERT_SPEC[which]["items"]:
        checks.append(band_item(cfg[k], op, label) if op in ("above", "below")
                      else num_item(card, label, cfg[k], op))
    on = [c for c in checks if c["state"] != "off"]
    want = _fthr(cfg["ALERT_HITS"])
    needed = len(on) if want is None else max(1, min(int(want), max(1, len(on))))
    return checks, needed


def _dwidth(s):
    """显示宽度：东亚全角字符在 Telegram 的等宽代码块里占两列，按字符数对齐会歪。"""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in str(s))


def _pad(s, w):
    s = str(s)
    return s + " " * max(0, w - _dwidth(s))


def alert_tally(checks, needed):
    """一段的计数 → `(命中数, 启用数, 有数可判数, 算不算触发)`。

    口径与拆两段时一致：`ALERT_HITS` 只在**启用**的项里算，取不到数（`gap`）既不算命中也照样占额。
    2026-09-24 起这条链每天必发一条日报，所以这里的「触发」只写进正文当结论，**不再决定发不发**。"""
    on = [c for c in checks if c["state"] != "off"]
    got = [c for c in on if c["state"] in ("hit", "miss")]
    hits = [c for c in on if c["state"] == "hit"]
    return len(hits), len(on), len(got), bool(on) and len(got) >= needed and len(hits) >= needed


def alert_report(sects, checks, biz):
    """把各段的判定并成**一条等宽日报表格**（Telegram 侧靠代码块渲染才对齐；见 `send(mono=True)`）。

    一行一张卡：「当前值 / 数据日期」只有一列（三段读的是同一批数，各段重复列只会把表撑宽），
    各段自己的「条件 + ✓/✗」各占一列 —— 所以顶部底部对同一个数各说各话时（AHR999 两段同方向就是这种），
    一行里看得清清楚楚，不必像两条独立消息那样来回翻。

    无论触没触发都发（2026-09-24 用户改的口径），所以头条必须自己讲清楚结论：每段一行「命中 n/m、要求 k → 触发/未触发」。
    列宽按实际内容现算，不写死：标签里既有「AHR999 定投指数」也有「恐慌贪婪指数」，写死一定歪；
    停用的项（`·`）也照样列出来，读消息的人一眼看得出「这项当时是没配还是配了没中」。"""
    head = ["我爱大饼 · 指标日报 %s（业务日 %s · 每天一条，与是否触发无关）"
            % (date.today().isoformat(), biz)]
    for w in sects:
        cs, needed = checks[w]
        hits, on_n, got_n, fired = alert_tally(cs, needed)
        head.append("%s：%d/%d 项命中（有数 %d 项 · 要求 %d 项）→ %s"
                    % (ALERT_SPEC[w]["title"], hits, on_n, got_n, needed, "触发" if fired else "未触发"))

    rows = []
    for i in range(len(ALERT_SPEC[sects[0]]["items"])):
        cs = [checks[w][0][i] for w in sects]
        # 当前值取「这段里真拿到了数的那一行」：一段停用（`off` 的 cur 是破折号）不该把另一段的真值盖掉。
        best = next((c for c in cs if c["state"] in ("hit", "miss")), None) \
            or next((c for c in cs if c["state"] == "gap"), None) or cs[0]
        rows.append([best["label"], best["cur"], best["asof"] or "—"]
                    + ["%s %s" % (ALERT_MARK[c["state"]], c["thr"]) for c in cs])
    cols = ["指标", "当前值", "数据日期"] + [ALERT_SPEC[w]["title"] for w in sects]
    ws = [max(_dwidth(cols[i]), max(_dwidth(r[i]) for r in rows)) for i in range(len(cols))]
    lines = ["\n".join(head), ""]
    lines.append("  ".join(_pad(c, ws[i]) for i, c in enumerate(cols)).rstrip())
    lines.append("  ".join("-" * w for w in ws))
    for r in rows:
        lines.append("  ".join(_pad(v, ws[i]) for i, v in enumerate(r)).rstrip())
    gaps = []
    for w in sects:
        for c in checks[w][0]:
            if c["state"] == "gap" and (c["label"], c.get("why")) not in gaps:
                gaps.append((c["label"], c.get("why")))
    lines.append("\n缺口：%s" % ("；".join("%s：%s" % g for g in gaps) or "无"))
    return "\n".join(lines)


def alert_gate(cfgs, now=None, force=False):
    """→ `(能发, 原因)`。两条闸门：① 本次涉及的每一段都不早于自己的 `ALERT_AT`；② 日报一个日历日只发一条。

    **这一关在取数之前**（cron 每分钟拉起一次，没到点／当天已发过时连上游都不打，直接退出）。
    ①判的是「现在 >= 目标时刻」而不是「正好等于那一分钟」：到点后第一次发、发过之后当天不再发；
    万一 08:10 那分钟机器没起来，08:11 之后仍会补上，不会整天空过。`ALERT_AT` 留空 = 不设时刻
    （这时本闸门只剩②，等于「服务一起来就发一次」）。合并成一条日报之后，两段各写各的时刻时取**较晚**的那个：
    早段还没到点就整条不发，否则「一条消息里两列判定」会有一列是上一小时的旧数。
    ②是**一本账**（`ALERT_STATE`）：一条消息两列判定，没有「顶部评过但底部没评过」这种中间态。
    时刻格式不对一律**不发**并说清原因——每分钟一次的 cron 会把「猜错时刻」放大成刷屏。
    本路径**不读** `[notify] daily_limit`（那是 --btc 的额度），②自己就封顶了。"""
    if force:
        return True, "（--force：跳过时刻与当日一条的限制，仍然会记一笔已发）"
    now = now or datetime.now()
    for w, cfg in cfgs.items():
        at = (cfg.get("ALERT_AT") or "").strip()
        if not at:
            continue
        t = _hhmm(at)
        if not t:
            return False, "[%s] ALERT_AT=%r 不是 hh:mm，没发（改对，或整行留空表示不设时刻）" % (w, at)
        if now.hour * 60 + now.minute < t[0] * 60 + t[1]:
            return False, "还没到 [%s] 的 %s（现在 %02d:%02d），没发" % (w, at, now.hour, now.minute)
    st = _state(ALERT_STATE)
    if st.get("day") == now.date().isoformat():
        return False, "%s 今天的日报已经发过了（%s，bot=%s，message_id=%s）——要重发加 --force" \
               % (st["day"], st.get("sent_at"), st.get("bot"), st.get("message_id"))
    return True, ""


def alert_compare(which, checks):
    """一行紧凑对照「查询值（设置阈值）判定」，**只进运行输出 / `logs/notify_cron.log`**（TG 正文是
    `alert_report` 那张表，表要等宽对齐，一行流水串塞进去会把代码块撑歪，两条用途不一样）。

    分隔用 ` ; ` 而不是 `｜`：通道那一项的当前值本身就带 `｜`（收盘$… ｜支撑$…），
    再用它当分隔就切不开。停用的项也照样列出来 —— 日志里看一眼就知道「没中」还是「没配」。"""
    return "对照 [%s] %s" % (which, " ; ".join(
        "%s: %s (%s) %s" % (c["key"], c["cur"], c["thr"], ALERT_MARK[c["state"]]) for c in checks))


def run_html_alert(do_send=False, bot=None, force=False, now=None, which=None):
    """指标日报的完整一条链：过闸门 → **一次取数** → 两段各自判定 → 并成一条表格 → 发 → 记当天的账。

    2026-09-24 用户改口径：**不论有没有触发阈值，每天固定一条**，正文就是「当前实际值 + 各段设置的条件」那张表
    （两段的判定并排放在同一行的两列里，不再各发一条）。所以本函数里已经没有「够数才发」这个分支了，
    `ALERT_HITS` 只写进正文的结论行；唯一还能让今天一条都不发的是：闸门（当天已发过／没到点）、
    取数全挂、各段阈值全被停用、没配收件人。

    与 `run_btc` 同一套规矩：不传 `--send` 一律不发；形参叫 `do_send` 不叫 `send`（别盖掉模块级那个发信函数）；
    `now` 只是给自检/测试留的假时钟，取数**永远不穿透上游缓存**（cron 每分钟一次，穿透会把上游打爆）。

    两列共用一次 `btc_summary()`：那三张卡本来就在同一次响应里，两段只是拿同一批数比不同方向的条件。
    记账只有**一本**（`ALERT_STATE`）：预览（不带 `--send`）从不记账，跑一百遍也不会把当天那条真日报哑掉；
    真发失败同样不记账，下一分钟的 cron 自己会再试；只有「阈值全停用」这种发了也没得比的情况会记一笔「没发」，
    为的是别让每分钟一次的 cron 反复打上游。`--btc` 那条则是失败不消耗额度、成功后按日历日计数。

    `which` 留 `--html-alert-top` / `--html-alert-bottom` 两个入口：表里只出那一段的条件列（当前值那几列照旧）。
    注意账本是共用的——单独跑过一段，当天那条完整日报也就一并算发过了。"""
    sects = ALERT_SECTS if which is None else (which,)
    bot = (bot or cfg_bot() or "").strip().upper()
    cfgs = {w: alert_cfg(w) for w in sects}
    for w in sects:
        cfg = cfgs[w]
        print("[%s] 生效阈值（环境变量 > indicator.ini > 代码默认）：%s"
              % (w, "  ".join("%s=%s" % (k, cfg[k] or "(空)")
                              for k in ("ALERT_AT", "ALERT_HITS") + tuple(i[0] for i in ALERT_SPEC[w]["items"]))))
    ok, why = alert_gate(cfgs, now, force)
    if do_send:
        if not ok:
            print("闸门：%s（**没取数、没发**）" % why)
            return 0
        if why:
            print(why)
    else:
        # 预览不设闸：看一眼「现在各段是什么状态」是本功能最常用的用法，
        # 而闸门在预览这条路上挡不出任何后果（它从不发信），只会挡得你看不到数。
        print("预览：闸门不参与（这条路径永远不发信、不记账），真到 cron 那一刻的判定是 %s"
              % ("放行" if ok else "「%s」" % why))
    out = btc_summary()
    if not out.get("ok"):
        print("BTC 取数全部失败，没数可报，一条都不发：%s" % (out.get("error") or out.get("failed")))
        return 1                                        # 整条链挂了不记账：下一分钟重试
    print("取数 %d/%d 项有数，用时 %sms（各段共用这一次取数）"
          % (out["count"]["ok"], out["count"]["total"], out.get("elapsed_ms")))
    checks = {w: alert_checks(cfgs[w], out.get("items"), w) for w in sects}
    biz = biz_date([c for w in sects for c in checks[w][0] if c["asof"]])
    if not any(c["state"] != "off" for w in sects for c in checks[w][0]):
        print("各段判定项全被停用了 —— 没条件可比，今天不发（要么把阈值填上，要么整条链别挂 cron）。")
        if do_send:
            _consume(bot, biz, None, ALERT_STATE, fired=False)
            print("已记「%s 评估过（没发）」——今天不再打上游；手工重评加 --force。" % biz)
        return 0
    table = alert_report(sects, checks, biz)
    print(table)
    for w in sects:
        print(alert_compare(w, checks[w][0]))
    if not do_send:
        print("预览模式，**一条都没发**，也**不记账**（要发到 %s 加 --send；正文就是上面这张表）。"
              % (bot or "没配的机器人——config.ini 的 [notify] tg_bot 或 --bot"))
        return 0
    if not bot:
        print("没配发给谁：--bot QA 指定，或在 config.ini 的 [notify] tg_bot 写死。一条都没发。")
        return 2
    r = send(table, bot, mono=True)
    if r.get("ok"):
        _consume(bot, biz, r.get("message_id"), ALERT_STATE)
        print("已发送 bot=%s chat=%s message_id=%s" % (bot, bot_cfg(bot)[2], r.get("message_id")))
        return 0
    print("发送失败 bot=%s：%s（没记账，下一次 cron 还会自己试）" % (bot, r.get("error")))
    return 1


def bot_cfg(name=None):
    """取一个机器人的 `(名字, token, chat_id, 缺配置的原因)`。

    缺值就返回空串 + 原因，**不猜默认机器人**：发错群比不发难查得多。"""
    key = (name or "QA").strip().upper()
    if key not in BOTS:
        return key, "", "", "未知机器人 %s（可选 %s）" % (key, " / ".join(sorted(BOTS)))
    token_env, chat_env = BOTS[key]
    token = (os.environ.get(token_env) or "").strip()
    chat = (os.environ.get(chat_env) or "").strip()
    if not token or not chat:
        return key, "", "", "缺少 %s / %s（config.ini 的 [TG] 或同名环境变量）" % (token_env, chat_env)
    return key, token, chat, ""


def _api(method, token, params=None, ms=15000):
    """向 bot API 发一次只带方法名的请求，返回 `{ok, result|error}`（与全站取数同一形状）。

    日志与错误串里**都不出现 token**：URL 只在局部变量里活一次，`short_err` 本身会去掉 URL，
    所以异常路径也带不出去；成功路径根本不记 URL。"""
    url = TG_API % (token, method + ("?" + urllib.parse.urlencode(params) if params else ""))
    handlers = [urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})] if PROXY else []
    try:
        with urllib.request.build_opener(*handlers).open(url, timeout=ms / 1000.0) as r:
            body = r.read().decode("utf-8", "replace")
    except Exception as e:
        return {"ok": False, "error": "Telegram %s 请求失败：%s" % (method, short_err(e))}
    try:
        j = json.loads(body)
    except ValueError:
        return {"ok": False, "error": "Telegram %s 返回非 JSON：%s" % (method, body[:120])}
    if not j.get("ok"):
        return {"ok": False, "error": "Telegram %s：%s" % (method, j.get("description") or body[:120])}
    return {"ok": True, "result": j.get("result")}


def whoami(name=None):
    """`getMe`：只问 bot 自己是谁，不碰任何聊天。用来验证 token 通不通、出口对不对。"""
    key, token, chat, why = bot_cfg(name)
    if why:
        return {"ok": False, "bot": key, "error": why}
    r = _api("getMe", token)
    if not r.get("ok"):
        return {"ok": False, "bot": key, "error": r.get("error")}
    u = r["result"] or {}
    return {"ok": True, "bot": key, "username": "@" + str(u.get("username") or ""),
            "name": u.get("first_name"), "chat_id": chat}


def send(text, name=None, mono=False):
    """真发一条文本到该机器人的默认 chat_id。返回 `{ok, bot, message_id|error}`。

    默认**没有** `parse_mode`：Markdown/HTML 里一个裸 `_` 或 `<` 就整条 400，指标播报里到处是这种字符，
    纯文本比「为了好看而多一套转义」值当。过长按 Telegram 的上限截断并标注，不让它整条失败。

    `mono=True` 是给「等宽表格」用的唯一例外（`alert_report` 那条正文）：Telegram 的普通消息里空格会被
    折叠、 proportional 字体也不对齐，表格会变成一坨。所以整条包进 ``` 代码块 + `parse_mode=Markdown`
    ——进了代码块的内容不再被解析，正文里那些 `_`/`<` 反而安全了。代价：正文一旦出现三个连续反引号，
    代码块会提前闭合，所以这里在包之前先把它换掉（表格本身不产反引号，属于兜底）。"""
    key, token, chat, why = bot_cfg(name)
    if why:
        return {"ok": False, "bot": key, "error": why}
    body = (text or "").strip()
    if not body:
        return {"ok": False, "bot": key, "error": "空文本，没发"}
    cap = TEXT_LIMIT - (12 if mono else 0)               # 代码块的围栏与换行也占那 4096
    if len(body) > cap:
        body = body[:cap - 20] + "…（已截断，原长 %d）" % len(body)
    params = {"chat_id": chat, "text": body, "disable_web_page_preview": "true"}
    if mono:
        params["text"] = "```\n%s\n```" % body.replace("```", "` ` `")
        params["parse_mode"] = "Markdown"
    r = _api("sendMessage", token, params)
    if not r.get("ok"):
        log.warning("[notify] TG 发送失败 bot=%s：%s", key, r.get("error"))
        return {"ok": False, "bot": key, "error": r.get("error")}
    mid = (r["result"] or {}).get("message_id")
    log.info("[notify] TG 已发送 bot=%s chat=%s message_id=%s（%d 字）", key, chat, mid, len(body))
    return {"ok": True, "bot": key, "message_id": mid}


def health():
    """给 /api/health 之类用的自述：**只报有没有配齐，不回 token**。"""
    out = {}
    for k in sorted(BOTS):
        _, _, _, why = bot_cfg(k)
        out[k] = "ok" if not why else why
    return {"bots": out, "proxy": bool(PROXY)}


def _arg(argv, flag):
    """取 `--bot QA` 这种「开关 + 值」的值；只给了开关没给值就当没给（别抛 IndexError）。"""
    i = argv.index(flag) + 1 if flag in argv else -1
    return argv[i] if 0 <= i < len(argv) and not argv[i].startswith("--") else None


def main(argv):
    """命令行：默认只探活 + 预览，`--send` 才真发（见模块注释里那条教训）。"""
    send_it = "--send" in argv
    name = _arg(argv, "--bot")
    if "--status" in argv:                            # 纯本地：读那几条发送记录 + 回显生效阈值，不打上游、不打 bot API
        st = _state()
        print("极值播报（--btc）发送记录：%s" % (json.dumps(st, ensure_ascii=False) if st
                                                else "空（`data/notify_state.json` 还没有，说明这台机器没真发过）"))
        print("今日限额 %d 条（`[notify] daily_limit`）；默认机器人 %s（`[notify] tg_bot`）"
              % (daily_limit(), cfg_bot() or "未配置"))
        hs = _state(ALERT_STATE)
        print("\n指标日报（--html-alert）当天记录：%s"
              % (("%s %s（bot=%s，业务日 %s）" % (hs["day"],
                                                  "已发 message_id=%s" % hs.get("message_id")
                                                  if hs.get("sent") else "评过但没发（各段阈值全停用）",
                                                  hs.get("bot"), hs.get("biz_date")))
                 if hs else "空（`data/notify_html_state.json` 还没有，说明这台机器没跑过 --send）"))
        for w in ALERT_SECTS:
            ac = alert_cfg(w)
            print("\n[%s]（%s）生效阈值（环境变量 > indicator.ini > 代码默认）：%s"
                  % (ALERT_SPEC[w]["sect"], ALERT_SPEC[w]["title"], json.dumps(ac, ensure_ascii=False)))
            print("  时刻 %s ｜ 结论按「命中 %s 项」写进正文（留空=有几项算几项全中）；**触发与否每天都发一条**，"
                  "这一路径不吃 daily_limit，一个日历日只发一条"
                  % (ac["ALERT_AT"] or "不限（不设时间闸门）", ac["ALERT_HITS"] or "全部"))
        return 0
    if "--btc" in argv:
        return run_btc(send_it, name, force="--force" in argv)
    if "--html-alert-top" in argv:
        return run_html_alert(send_it, name, force="--force" in argv, which="top")
    if "--html-alert-bottom" in argv:
        return run_html_alert(send_it, name, force="--force" in argv, which="bottom")
    if "--html-alert" in argv:
        return run_html_alert(send_it, name, force="--force" in argv)
    text = _arg(argv, "--text") or ""
    for t in ([name] if name else sorted(BOTS)):
        w = whoami(t)
        if w.get("ok"):
            print("  %-6s %s（%s） chat_id=%s  出口=%s"
                  % (w["bot"], w["username"], w["name"], w["chat_id"], "代理" if PROXY else "直连"))
        else:
            print("  %-6s 不可用：%s" % (t, w.get("error")))
    if not text:
        print("\n没有 --text，只做了 getMe 探活（没发任何消息）。要发：--send --bot QA --text \"内容\"")
        print("要跑 BTC 极值播报（同样默认不发）：--btc；真发：--btc --send")
        return 0
    print("\n将要发送（%d 字）：\n%s\n" % (len(text), text))
    if not send_it:
        print("预览模式，**一条都没发**。确认无误后加 --send 才会真的发到群里。")
        return 0
    if not name:                                  # 不带 --bot 就同时发两个群，那是最容易误伤的一种手滑
        print("--send 还必须带 --bot（QA / ALVIN），免得一条消息同时落到两个群里。")
        return 2
    r = send(text, name)
    print("发送结果 bot=%s ok=%s %s" % (r.get("bot"), r.get("ok"), r.get("message_id") or r.get("error") or ""))
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
