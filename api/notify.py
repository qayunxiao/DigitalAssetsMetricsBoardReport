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
  python api/notify.py --status                          只看本地那条发送记录与今日限额（不打网络，最安全的自检）

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

为什么把「发」做成显式 `--send`：2026-09-23 有过一次，探针按「接口回 501 就是没实现」的假设去打
持仓报告，结果那功能当天正好落地，三条 Telegram 就这么发出去了。这里的默认值就是为了让那种事
不再发生：**不传 `--send` 时本模块不会向 bot API 发 `sendMessage`**，只发只读的 `getMe`。
"""
import json
import os
import urllib.parse
import urllib.request
from datetime import date, datetime

from core import PROXY, ROOT, log, short_err

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


def _state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
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


def _consume(bot, biz, message_id):
    """记一笔已发。**只在真发成功之后写**，失败不计数，否则一次网络抖动就把当天的额度白白烧掉。"""
    st = _state()
    today = date.today().isoformat()
    rec = {"day": today,
           "count": ((st.get("count") or 0) if st.get("day") == today else 0) + 1,
           "bot": bot, "biz_date": biz, "message_id": message_id,
           "sent_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False)
    os.replace(tmp, STATE_FILE)                         # 原子替换，与 report_quota.json 同一写法


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
    if "--status" in argv:                            # 纯本地：读那条发送记录，不打上游、不打 bot API
        st = _state()
        print("发送记录：%s" % (json.dumps(st, ensure_ascii=False) if st
                                else "空（`data/notify_state.json` 还没有，说明这台机器没真发过）"))
        print("今日限额 %d 条（`[notify] daily_limit`）；默认机器人 %s（`[notify] tg_bot`）"
              % (daily_limit(), cfg_bot() or "未配置"))
        return 0
    if "--btc" in argv:
        return run_btc(send_it, name, force="--force" in argv)
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
