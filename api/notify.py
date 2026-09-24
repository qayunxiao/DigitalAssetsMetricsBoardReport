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
  python api/notify.py --html-alert                     跑一遍 [html_alert] 那三项定时监测：取数 + 三项判定 +
                                                       组正文 + 顺带说清「真到 cron 那一刻会不会被闸门挡」；
                                                       **不发、不记账**，所以随时可以跑来看数
  python api/notify.py --html-alert --send              真发一条（cron 挂这条；时刻与阈值都在 indicator.ini）
  python api/notify.py --html-alert --send --force      跳过「不早于 ALERT_AT」和「一个日历日只评一次」（手工补发用）
  python api/notify.py --status                          只看本地那两条发送记录 + [html_alert] 生效阈值
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

`--html-alert` 是**另一条独立链路**（2026-09-24 用户要的功能：每天定点盯那三张卡），与上面那套极值播报互不影响：
  · 三项监测 = AHR999 ≤ `AHR999_MAX`、恐慌贪婪 ≥ `FEAR_GREED_MIN`、2年MA乘数通道的**日线收盘** > 同一根上的支撑 730MA；
    要求同时命中几项由 `ALERT_HITS` 说（默认 3 = 三项共振）。
  · 阈值与每天的时刻都在根目录 `indicator.ini` 的 `[html_alert]` 段 —— 这是全站**唯一**一处判级数值放在 ini 里，
    因为用户明示要「改配置不改代码」；顺序仍是 环境变量 `HTML_ALERT_*` > 该段 > 本模块 `ALERT_DEFAULTS`。
    那份文件他会手改，要引用这几个数就先重读文件，别照抄代码默认。
  · 取数与页面同源（`btc.summary()`，**永不穿透上游缓存**：cron 每分钟拉起一次，穿透会把上游打爆）；
    本模块只比大小，不重算指标、不补估算值 —— 取不到数的那项**既不算满足、也照样占 `ALERT_HITS` 的额**
    （写着 3 就要三项都成立，缺一项当天就是不发，正文里单列进「缺口」）。代价：某项长期挂掉会让本条长期
    沉默，所以缺口一定要打印出来；宁可把 `ALERT_HITS` 调小，也别在代码里给缺数硬编一个判定。
  · 闸门两条，**都走在取数前面**（`--send` 那条被挡时连上游都不打）：① 不早于 `ALERT_AT`（留空 = 不限时刻）；
    ② 一个日历日只评一次 —— 触发发了要记，没触发也要记「今天评过了」，这样 cron 每分钟拉起一天也只打一次上游。
    记在 `data/notify_html_state.json`（与 --btc 那份各记各的，互不消耗）。**预览一条都不记**，
    看一眼配置就把当天该发的提示哑掉，是最坏的一种手滑；真发失败同样不记，下一分钟的 cron 自己再试。
    收件人取 `[notify] tg_bot`（`--bot` 可覆盖），但**不消耗** `[notify] daily_limit`（那条只管 --btc）。
  · 时刻按跑脚本那台机器的本地时区解释，本机与 serv00 不一定同一小时，配置段里写了怎么核对。

为什么把「发」做成显式 `--send`：2026-09-23 有过一次，探针按「接口回 501 就是没实现」的假设去打
持仓报告，结果那功能当天正好落地，三条 Telegram 就这么发出去了。这里的默认值就是为了让那种事
不再发生：**不传 `--send` 时本模块不会向 bot API 发 `sendMessage`**，只发只读的 `getMe`。
"""
import json
import os
import re
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

    `fired=False` 是给 `--html-alert` 用的「今天评过了但没触发」：同样占掉当天，cron 每分钟拉起时
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


# ============================== 页面指标定时播报（--html-alert）==============================
# 阈值住在根目录 `indicator.ini` 的 `[html_alert]` 段（2026-09-24 用户明示：这几档要能改配置不改代码，
# 连每天几点跑也一样）。这是全站**唯一**一处判级数值放在 ini 里的地方——其余口径仍在代码常量，见 Qoder.md。
# 判定读的是 `api/btc.py` 那三张卡自己的头条值（与 staic/btc.html 上看到的一模一样），本模块只比大小、不重算指标。

ALERT_SECT = "html_alert"
ALERT_ENV = {"ALERT_AT": "HTML_ALERT_AT", "ALERT_HITS": "HTML_ALERT_HITS",
             "AHR999_MAX": "HTML_ALERT_AHR999_MAX", "FEAR_GREED_MIN": "HTML_ALERT_FEAR_GREED_MIN",
             "TWM_CLOSE_ABOVE_SUPPORT": "HTML_ALERT_TWM_ABOVE"}
# 代码默认 = 用户 2026-09-24 口头给的那一组（08:10 / 三项全中 / AHR999≤0.57 / 恐慌≥70 / 收盘>730MA）。
# 它只在 `[html_alert]` 整段缺失或那份文件解析不了时兜底；平时生效的是文件里的值，而那文件他会手改——
# **要引用这几个数，先重读 indicator.ini，别照抄这里**。
ALERT_DEFAULTS = {"ALERT_AT": "08:10", "ALERT_HITS": "3", "AHR999_MAX": "0.57",
                  "FEAR_GREED_MIN": "70", "TWM_CLOSE_ABOVE_SUPPORT": "1"}
HTML_STATE_FILE = os.path.join(ROOT, "data", "notify_html_state.json")
ALERT_MARK = {"hit": "✓", "miss": "✗", "gap": "—", "off": "·"}


def alert_cfg():
    """五个键的生效值：**环境变量 > indicator.ini `[html_alert]` > `ALERT_DEFAULTS`**。

    值为空串原样返回（那是他显式停用本项），不会被默认值顶回来；只有键根本不存在才落默认。
    env 那一侧默认按「设了但设空 = 没设」处理，与 `apply_config()` 同一规矩 —— **只有 `ALERT_AT` 例外**：
    它在 ini 里留空的语义本来就是「不设时刻」（见 `html_gate`），所以 `HTML_ALERT_AT=""` 也照这个语义走。
    `alert_cron.sh` 靠这个口子把「几点跑」整个交给 crontab 那五个字段，脚本自己不再判时刻。"""
    out = {}
    for k, dv in ALERT_DEFAULTS.items():
        ev = os.environ.get(ALERT_ENV[k])
        if k == "ALERT_AT" and ev is not None:
            out[k] = ev.strip()                      # 显式设空 = 不设时刻；有值则覆盖 ini
            continue
        ev = (ev or "").strip()
        out[k] = ev if ev else indicator_get(ALERT_SECT, k, dv)
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


def alert_checks(cfg, items):
    """三项判定 → `(checks, needed)`。每项 `{key,label,cur,thr,asof,state[,why]}`，
    `state` 取 hit（满足）/ miss（不满足）/ gap（取不到数，**既不算满足也不算不满足**）/ off（本项停用）；
    `needed` = 要求命中的项数，只在「启用」的项里算——**gap 仍然占额**：写着 3 就是三项都要成立，
    有一项没数就当天不发（宁缺不估）。代价是一条链长期挂着会让播报静默哑掉，
    所以缺口必须打印出来、要接受缺数就把 `ALERT_HITS` 调小，别改判定代码。"""
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

    def band_item(on_s):
        key, label = "two_year_multiply", "2年MA乘数通道"
        sw = _fthr(on_s)
        if sw is None or sw <= 0:
            return {"key": key, "label": label, "cur": "—",
                    "thr": "—（本项停用：TWM_CLOSE_ABOVE_SUPPORT 非 1）", "asof": None, "state": "off"}
        it = by.get(key) or {}
        cond = "日线收盘 > 支撑 730MA"
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
                "cur": "$%s（收盘）vs $%s（支撑）" % (format(px, ",.0f"), format(lo, ",.0f")),
                "thr": cond, "asof": d, "state": "hit" if px > lo else "miss"}

    checks = [num_item("ahr999", "AHR999 定投指数", cfg["AHR999_MAX"], "<="),
              num_item("fear", "恐慌贪婪指数", cfg["FEAR_GREED_MIN"], ">="),
              band_item(cfg["TWM_CLOSE_ABOVE_SUPPORT"])]
    on = [c for c in checks if c["state"] != "off"]
    want = _fthr(cfg["ALERT_HITS"])
    needed = len(on) if want is None else max(1, min(int(want), max(1, len(on))))
    return checks, needed


def alert_text(checks, needed, biz):
    """正文：头条一句「命中几/几、要求几」，下面把**三项全列**（含没命中的与缺的），末尾一句缺口。

    停用项也列，标 `·`，这样从消息本身就能看出当时那五个阈值是什么状态，不必去翻服务器上的 ini。"""
    hits = [c for c in checks if c["state"] == "hit"]
    on = [c for c in checks if c["state"] != "off"]
    lines = ["我爱大饼 · 指标提示 %s（业务日 %s · 命中 %d/%d 项，要求 %d 项）"
             % (date.today().isoformat(), biz, len(hits), len(on), needed)]
    for c in checks:
        lines.append("%s %s：%s｜%s%s" % (ALERT_MARK[c["state"]], c["label"], c["cur"], c["thr"],
                                          "（asof %s）" % c["asof"] if c["asof"] else ""))
    gaps = "；".join("%s：%s" % (c["label"], c["why"]) for c in checks if c["state"] == "gap")
    lines.append("缺口：%s" % (gaps or "无"))
    return "\n".join(lines)


def html_gate(cfg, now=None, force=False):
    """→ `(能发, 原因)`。两条闸门：① 不早于 `ALERT_AT`；② 一个日历日只评估一次。

    **这一关在取数之前**（cron 每分钟拉起一次，没到点／当天已评过时连上游都不打，直接退出）。
    ①判的是「现在 >= 目标时刻」而不是「正好等于那一分钟」：到点后第一次评、评过之后当天不再评；
    万一 08:10 那分钟机器没起来，08:11 之后仍会补上，不会整天空过。
    `ALERT_AT` 留空 = 不设时刻（这时本闸门只剩②，等于「服务一起来就评一次」）。
    时刻格式不对一律**不发**并说清原因——每分钟一次的 cron 会把「猜错时刻」放大成刷屏。
    本路径**不读** `[notify] daily_limit`（那是 --btc 的额度），②自己就封顶了。"""
    if force:
        return True, "（--force：跳过时刻与当日一条的限制，仍然会记一笔已发）"
    now = now or datetime.now()
    at = (cfg.get("ALERT_AT") or "").strip()
    if at:
        t = _hhmm(at)
        if not t:
            return False, "ALERT_AT=%r 不是 hh:mm，没发（改对，或整行留空表示不设时刻）" % at
        if now.hour * 60 + now.minute < t[0] * 60 + t[1]:
            return False, "还没到 %s（现在 %02d:%02d），没发" % (at, now.hour, now.minute)
    st = _state(HTML_STATE_FILE)
    if st.get("day") == now.date().isoformat():
        done = ("已经发过一条（%s，bot=%s，message_id=%s）" % (st.get("sent_at"), st.get("bot"), st.get("message_id"))
                if st.get("sent") else "已经评估过一次（%s，bot=%s，当时没到触发条件）"
                                       % (st.get("sent_at"), st.get("bot")))
        return False, ("%s %s——要重发加 --force" % (st["day"], done))
    return True, ""


def run_html_alert(do_send=False, bot=None, force=False, now=None):
    """定时播报的完整一条链：过闸门 → 取数（与页面同源）→ 三项判定 → 够数才发 → 记「今天评过了」。

    与 `run_btc` 同一套规矩：不传 `--send` 一律不发；形参叫 `do_send` 不叫 `send`（别盖掉模块级那个发信函数）；
    `now` 只是给自检/测试留的假时钟，取数**永远不穿透上游缓存**（cron 每分钟一次，穿透会把上游打爆）。

    「评过就记账」只发生在 `--send` 那条路上：预览跑一百遍也不会把当天的真播报哑掉——
    手滑看一眼配置，结果那天该发的提示没了，比多看一眼日志糟得多。真发但**失败**同样不记账，
    下一分钟的 cron 自己会再试；`--btc` 那条则是失败不消耗额度、成功后按日历日计数。"""
    cfg = alert_cfg()
    bot = (bot or cfg_bot() or "").strip().upper()
    print("[html_alert] 生效阈值（环境变量 > indicator.ini > 代码默认）：" +
          "  ".join("%s=%s" % (k, cfg[k] or "(空)") for k in ALERT_DEFAULTS))
    if do_send:
        # 只有 cron 那条（带 --send）让闸门把**取数**一起挡掉：没到点／当天已评过时一分钟一次也不打上游。
        ok, why = html_gate(cfg, now, force)
        if not ok:
            print("闸门：%s（**没取数、没发**）" % why)
            return 0
        if why:
            print(why)
    else:
        # 预览不设闸：看一眼「现在这三项各是什么状态」是本功能最常用的用法，
        # 而闸门在预览这条路上挡不出任何后果（它从不发信），只会挡得你看不到数。
        g_ok, g_why = html_gate(cfg, now, force)
        print("预览：闸门不参与（这条路径永远不发信），真到 cron 那一刻的判定是 %s"
              % ("放行" if g_ok else "「%s」" % g_why))
    out = btc_summary()
    if not out.get("ok"):
        print("BTC 取数全部失败，三项都没数，一条都不发：%s" % (out.get("error") or out.get("failed")))
        return 1                                        # 整条链挂了不记账：下一分钟重试
    checks, needed = alert_checks(cfg, out.get("items"))
    print("取数 %d/%d 项有数，用时 %sms" % (out["count"]["ok"], out["count"]["total"], out.get("elapsed_ms")))
    for c in checks:
        print("  %s %-18s %-34s %-16s %s"
              % (ALERT_MARK[c["state"]], c["label"], c["cur"], c["thr"], c.get("why") or "asof " + str(c["asof"] or "—")))
    on = [c for c in checks if c["state"] != "off"]
    hits = [c for c in on if c["state"] == "hit"]
    got = [c for c in on if c["state"] in ("hit", "miss")]
    biz = biz_date([c for c in on if c["asof"]])
    if not on:
        print("\n三项在 [html_alert] 里全被停用了 —— 没东西可判。")
    else:
        print("\n命中 %d/%d 项，要求 %d 项（有数可判 %d 项）" % (len(hits), len(on), needed, len(got)))
    text = alert_text(checks, needed, biz) if hits else ""
    enough = bool(on) and len(got) >= needed and len(hits) >= needed
    if not enough:
        if on and len(got) < needed:
            print("有数的项不够要求数（还差 %d 项）—— 按「宁缺不估」不发。"
                  "某项长期取不到数会让本条长期沉默：要么修源，要么把 ALERT_HITS 调小。" % (needed - len(got)))
        elif on:
            print("没到触发条件 —— 不发。这是「不播」的正常结果，别为了有点动静去放阈值。")
        if do_send and on:                              # 评过了就记一笔，当天不再打上游
            _consume(bot or cfg_bot(), biz, None, HTML_STATE_FILE, fired=False)
            print("已记「%s 评估过（未触发）」——今天这一条链不会再打上游；要手工重评加 --force。" % biz)
        elif not do_send and on:
            print("预览模式，**一条都没发**，也**不记账**（今天该评的还会照常被 cron 评一次）。")
        return 0
    print("\n触发 %d 项（业务日 %s），正文 %d 字：\n%s\n" % (len(hits), biz, len(text), text))
    if not bot:
        print("没配发给谁：--bot QA 指定，或在 config.ini 的 [notify] tg_bot 写死。一条都没发。")
        return 2                                        # 装错了不该把当天的播报一起吞掉：不记账
    if not do_send:
        print("预览模式，**一条都没发**（要发到 %s 加 --send）。" % bot)
        return 0
    r = send(text, bot)
    if r.get("ok"):
        _consume(bot, biz, r.get("message_id"), HTML_STATE_FILE)
        print("已发送 bot=%s chat=%s message_id=%s" % (bot, bot_cfg(bot)[2], r.get("message_id")))
    else:
        print("发送失败 bot=%s：%s（没记账，下一次 cron 还会自己试）" % (bot, r.get("error")))
    return 0 if r.get("ok") else 1


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


def send(text, name=None):
    """真发一条文本到该机器人的默认 chat_id。返回 `{ok, bot, message_id|error}`。

    没有 `parse_mode`：Markdown/HTML 里一个裸 `_` 或 `<` 就整条 400，指标播报里到处是这种字符，
    纯文本比「为了好看而多一套转义」值当。过长按 Telegram 的上限截断并标注，不让它整条失败。"""
    key, token, chat, why = bot_cfg(name)
    if why:
        return {"ok": False, "bot": key, "error": why}
    body = (text or "").strip()
    if not body:
        return {"ok": False, "bot": key, "error": "空文本，没发"}
    if len(body) > TEXT_LIMIT:
        body = body[:TEXT_LIMIT - 20] + "…（已截断，原长 %d）" % len(body)
    r = _api("sendMessage", token, {"chat_id": chat, "text": body, "disable_web_page_preview": "true"})
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
    if "--status" in argv:                            # 纯本地：读那两条发送记录 + 回显生效阈值，不打上游、不打 bot API
        st = _state()
        print("极值播报（--btc）发送记录：%s" % (json.dumps(st, ensure_ascii=False) if st
                                                else "空（`data/notify_state.json` 还没有，说明这台机器没真发过）"))
        print("今日限额 %d 条（`[notify] daily_limit`）；默认机器人 %s（`[notify] tg_bot`）"
              % (daily_limit(), cfg_bot() or "未配置"))
        hs = _state(HTML_STATE_FILE)
        print("定时播报（--html-alert）当天记录：%s"
              % (("%s %s（bot=%s，业务日 %s）" % (hs["day"], "已发 message_id=%s" % hs.get("message_id")
                                                 if hs.get("sent") else "已评估过、当时未触发",
                                                 hs.get("bot"), hs.get("biz_date")))
                 if hs else "空（`data/notify_html_state.json` 还没有，说明这台机器没跑过 --send）"))
        ac = alert_cfg()
        print("[html_alert] 生效阈值（环境变量 > indicator.ini > 代码默认）：%s"
              % json.dumps(ac, ensure_ascii=False))
        print("  时刻 %s ｜ 要求命中 %s 项（留空=有几项算几项全中）；这一路径不吃 daily_limit，"
              "一个日历日只评一次（没触发的日子也算评过）"
              % (ac["ALERT_AT"] or "不限（不设时间闸门）", ac["ALERT_HITS"] or "全部"))
        return 0
    if "--btc" in argv:
        return run_btc(send_it, name, force="--force" in argv)
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
