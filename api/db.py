# -*- coding: utf-8 -*-
"""可选落库层（MySQL / serv00 的 m2573_btc）。

设计前提，改这段代码前先看完：

* **旁路，不是主路**：页面取数与这个文件无关。没装 pymysql、库不通、表没建，都只让
  `/api/db/health` 少一项数据，绝不让 BTC 指标页打不开——所有 `store_*` 一律吞异常只记日志。
  本服务原本是零依赖 stdlib，这里第一次引入第三方包（pymysql），所以它是**可选 import**：
  缺包时连连接都不尝试，更不 import 期报错。
* **口令解析顺序：环境变量 > `local.ini` > `config.ini`**（比 core.apply_config 多一层 local.ini）。
  `config.ini` 是 git 跟踪文件、`deploy_app.sh` 又按 `git ls-files` 打上传包，所以口令优先放
  `local.ini`（已 gitignore）或 `set MYSQL_PASSWD=...`；三处都不给就当没启用。
  本文件任何日志、任何响应体都不出现口令，健康接口连主机名与账号都不回。
* **一天一行、同日覆盖**：页面每 15 分钟自动刷新一次，不做幂等就会把库里塞满同一天的重复行，
  历史曲线直接废掉。所以每个写入都按业务日 UPSERT，并且进程内再挡一层「值没变就不再打库」。
* **报表正文不落库**：`board_report_run` 只存元数据（谁、何时、成没成、多长），持仓金额那些
  私密内容留在页面上按需展开，不进共享数据库。表结构见 `sql/board_schema.sql`。

命令行（在能连到库的那台机器上跑；本机通常连不到 serv00 的 3306）：
  python api/db.py --status            看连接参数来源、缺什么、各表行数（只读）
  python api/db.py --print-sql         把初始化脚本按语句列出来，不连库（本机就能验）
  python api/db.py --init              建表（幂等，可反复跑）并写 board_meta 版本
"""
import configparser
import os
import re
import threading
import traceback
from datetime import date, datetime

from core import CONFIG, ROOT, log

SCHEMA_FILE = os.path.join(ROOT, "sql", "board_schema.sql")
LOCAL_CONFIG = os.path.join(ROOT, "local.ini")
SCHEMA_VERSION = "1"
KEY_PREFIX = "btc:"                 # 指标历史序列的命名空间，与 board_series_daily 注释一致
TABLES = ("board_meta", "board_indicator_daily", "board_series_daily",
          "board_risk_score_daily", "board_run_log", "board_report_run")
ENV = {"HOST": "MYSQL_HOST", "PORT": "MYSQL_PORT", "USER": "MYSQL_USER",
       "PASSWD": "MYSQL_PASSWD", "DADABASES": "MYSQL_DATABASE", "CHARSET": "MYSQL_CHARSET",
       "ENABLE": "MYSQL_ENABLE", "STORE_BTC": "MYSQL_STORE_BTC",
       "STORE_SERIES": "MYSQL_STORE_SERIES", "STORE_RISK": "MYSQL_STORE_RISK",
       "STORE_REPORT": "MYSQL_STORE_REPORT"}
ON = ("1", "true", "yes", "on")

_db_lock = threading.Lock()
_written = {}          # (表, 业务日) → 指纹：同值不重复打库
_conn_for_test = None  # 只给离线自检用的注入点（见 README 的验证段），运行时永远为 None


# ---------------------------------------------------------------- 配置

def _layers():
    """按优先级返回 [(层名, ConfigParser 或 None)]：环境 > local.ini > config.ini。"""
    out = [("环境变量", None)]
    for name, path in (("local.ini", LOCAL_CONFIG), ("config.ini", CONFIG)):
        cp = configparser.ConfigParser(interpolation=None)
        try:
            cp.read(path, encoding="utf-8-sig")
        except OSError:
            continue
        out.append((name, cp))
    return out


def _get(key):
    """[mysql] 单项解析，返回 (值, 来源层名)。空值与不存在的键都算「没有」。"""
    env = ENV.get(key)
    if env and os.environ.get(env, "").strip():
        return os.environ[env].strip(), "环境变量 " + env
    for name, cp in _layers()[1:]:
        if cp is not None:
            v = (cp.get("mysql", key, fallback="") or "").strip()
            if v:
                return v, name
    return "", ""


def db_config():
    """连接参数 + 各开关。`enabled=False` 时带 `reason`，页面上直接能看懂为什么没入库。"""
    host, _ = _get("HOST")
    user, _ = _get("USER")
    db, _ = _get("DADABASES")
    pw, pw_src = _get("PASSWD")
    port = _get("PORT")[0] or "3306"
    charset = _get("CHARSET")[0] or "utf8mb4"
    enable = (_get("ENABLE")[0] or "1").lower() in ON
    conf = {"host": host, "port": int(re.sub(r"\D", "", port) or 3306), "user": user,
            "password": pw, "database": db, "charset": charset, "password_from": pw_src}
    for k in ("store_btc", "store_series", "store_risk", "store_report"):
        conf[k] = (_get(k.upper())[0] or "1").lower() in ON
    if not enable:
        conf["enabled"] = False
        conf["reason"] = "[mysql] enable=0（显式关掉）"
    elif not (host and user and db):
        conf["enabled"] = False
        conf["reason"] = "[mysql] 缺 HOST/USER/DADABASES（三项齐全才会连库）"
    elif not pw:
        conf["enabled"] = False
        conf["reason"] = "没有口令：set MYSQL_PASSWD=… 或写进 local.ini 的 [mysql] PASSWD"
    else:
        conf["enabled"] = True
    return conf


def _connect(conf, timeout=8):
    """真连接。pymysql 缺失/连不上都抛异常，由调用方决定吞还是报。"""
    if _conn_for_test is not None:
        return _conn_for_test            # 离线自检：桩连接，绝不碰网络
    import pymysql                       # 可选依赖：没装就是没启用，不在 import 期炸
    return pymysql.connect(host=conf["host"], port=conf["port"], user=conf["user"],
                           password=conf["password"], database=conf["database"],
                           charset=conf["charset"], autocommit=True,
                           connect_timeout=timeout, read_timeout=timeout * 4,
                           write_timeout=timeout * 4)


# ---------------------------------------------------------------- 建表脚本

def schema_statements():
    """把 `sql/board_schema.sql` 切成可执行语句：逐行去 `--` 注释，遇行尾 `;` 收尾。

    不引 sqlparse：这文件是我们自己写的，规则就一条——字符串里不出现半角分号（注释里用的是全角），
    切完再断言单引号成对，真出现不配对就是文件写错了，宁可当场报错也不要执行半截语句。
    """
    if not os.path.isfile(SCHEMA_FILE):
        raise IOError("找不到建表脚本 " + SCHEMA_FILE)
    with open(SCHEMA_FILE, encoding="utf-8-sig") as f:
        raw = f.read()
    out, buf = [], []
    for line in raw.splitlines():
        cut = re.split(r"(?<!\\)--", line)[0].rstrip() if line.lstrip().startswith("--") else line
        if not cut.strip():
            continue
        buf.append(cut.strip())
        if cut.rstrip().endswith(";"):
            stmt = "\n".join(buf).rstrip().rstrip(";")
            buf = []
            if stmt.count("'") % 2:
                raise ValueError("建表脚本里有单引号没配对，第一行：%s" % stmt.splitlines()[0][:60])
            out.append(stmt)
    if "".join(buf).strip():
        raise ValueError("建表脚本末尾有没以分号收尾的语句：%s" % "".join(buf)[:60])
    return out


def init_schema(dry=False):
    """跑建表脚本（幂等）。返回 {statements, executed, dry, version}。"""
    stmts = schema_statements()
    if dry:
        return {"ok": True, "dry": True, "statements": len(stmts),
                "kinds": sorted({re.match(r"\s*(\w+)", s).group(1).upper() for s in stmts})}
    conf = db_config()
    if not conf["enabled"]:
        return {"ok": False, "error": conf["reason"]}
    conn = None
    try:
        conn = _connect(conf)
        with conn.cursor() as cur:
            for s in stmts:
                cur.execute(s)
        return {"ok": True, "dry": False, "statements": len(stmts), "database": conf["database"]}
    except Exception as e:
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:200])}
    finally:
        try:
            if conn is not None and _conn_for_test is None:
                conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------- 写入

def _fingerprint(tbl, tag, vals):
    """同值不重复打库的键：值一变就会换指纹（上游一天只更新一次，所以一天通常只写一遍）。"""
    k = (tbl, tag)
    fp = repr(vals)
    if _written.get(k) == fp:
        return True
    _written[k] = fp
    return False


def _rows(cur, sql, params):
    cur.execute(sql, params)
    return cur.fetchall()


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v != v else v


def _as_date(s, fallback=None):
    """上游 asof 有三种长相：2025-10-06、2025/10/06、带时间的 ISO。取不到就用 fallback。"""
    s = str(s or "")
    m = re.match(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
    if m:
        return "%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3)))
    return fallback or date.today().isoformat()


def _write(conf, fn):
    """统一的「打库一次」外壳：串行锁 + 用完就关 + 任何异常只记日志。"""
    if not conf.get("enabled"):
        return False
    conn = None
    try:
        with _db_lock:
            conn = _connect(conf)
            with conn.cursor() as cur:
                fn(cur)
        return True
    except ImportError:
        log.warning("[db] 没装 pymysql，本轮跳过入库（页面不受影响；服务器上 venv 里有）")
    except Exception as e:
        log.warning("[db] 入库失败（页面不受影响）：%s: %s", type(e).__name__, str(e)[:160])
    finally:
        try:
            if conn is not None and _conn_for_test is None:
                conn.close()
        except Exception:
            pass
    return False


SQL_RUN_LOG = ("INSERT INTO board_run_log (ts, module, ok_count, total_count, elapsed_ms,"
               " spot, kline_src, failed_keys, note) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)")
SQL_IND = ("INSERT INTO board_indicator_daily (metric_key, metric_name, unit, `date`, value,"
           " tone, verdict, src, hist_points, extras_json, error, run_id)"
           " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
           " ON DUPLICATE KEY UPDATE metric_name=VALUES(metric_name), unit=VALUES(unit),"
           " value=VALUES(value), tone=VALUES(tone), verdict=VALUES(verdict), src=VALUES(src),"
           " hist_points=VALUES(hist_points), extras_json=VALUES(extras_json),"
           " error=VALUES(error), run_id=VALUES(run_id)")
SQL_SER = ("INSERT INTO board_series_daily (series_key, `date`, value) VALUES (%s,%s,%s)"
           " ON DUPLICATE KEY UPDATE value=VALUES(value)")


def store_btc(out):
    """一轮 /api/btc/summary 的产出：一条 run_log + 12 行读数 +（开关开时）各卡 hist[] 序列。

    run_log 先插，因为读数行要指它作 run_id；`-- 一次连接` 里全做完，不是一行一连。
    """
    conf = db_config()
    if not (conf["enabled"] and conf["store_btc"] and out and out.get("items")):
        return False
    import json
    today = date.today().isoformat()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    failed = "、".join(x.get("key", "") for x in out.get("failed") or [])[:250]
    if _fingerprint("run_log", today, [out.get("count"), out.get("spot"), failed]):
        return False
    c = {"n": 0, "rows": 0, "run_id": 0}

    def body(cur):
        cur.execute(SQL_RUN_LOG, (ts, "btc", (out.get("count") or {}).get("ok", 0),
                                  (out.get("count") or {}).get("total", 0),
                                  int(_num(out.get("elapsed_ms")) or 0),
                                  _num(out.get("spot")), out.get("kline_from") or "",
                                  failed, ""))
        c["run_id"] = cur.lastrowid or 0
        for it in out["items"]:
            d = _as_date(it.get("asof"), today)
            extras = json.dumps(it.get("extras") or [], ensure_ascii=False)
            cur.execute(SQL_IND, (it["key"][:32], (it.get("name") or "")[:64],
                                  (it.get("unit") or "")[:16], d, _num(it.get("value")),
                                  (it.get("tone") or "gray")[:8], (it.get("verdict") or "")[:128],
                                  (it.get("src") or "")[:64], len(it.get("hist") or []),
                                  extras[:60000], (it.get("error") or "")[:250], c["run_id"]))
            c["rows"] += 1
            if conf["store_series"] and "hist" in (it.get("store") or "") and it.get("hist"):
                pts = [(KEY_PREFIX + it["key"], _as_date(r.get("d")), _num(r.get("v")))
                       for r in it["hist"] if _num(r.get("v")) is not None]
                if pts and not _fingerprint("series", it["key"], len(pts)):
                    cur.executemany(SQL_SER, pts)
                    c["rows"] += len(pts)
    ok = _write(conf, body)
    if ok:
        log.info("[db] BTC 一轮已入库：run_id=%s，读数 %d 行", c["run_id"], c["rows"])
    return ok


def store_risk(d, ticker, score, factors=None):
    """崩盘监测页的当日评分：CSV 已经写了，这里是库内镜像（同日覆盖，与 CSV 同一规则）。"""
    import json
    conf = db_config()
    if not (conf["enabled"] and conf["store_risk"]):
        return False
    d = _as_date(d)
    if _fingerprint("risk", (d, ticker), score):
        return False
    sql = ("INSERT INTO board_risk_score_daily (`date`, ticker, score, factors_json)"
           " VALUES (%s,%s,%s,%s) ON DUPLICATE KEY UPDATE score=VALUES(score),"
           " factors_json=VALUES(factors_json)")
    return _write(conf, lambda cur: cur.execute(sql, (d, str(ticker)[:8], float(score),
                                                      json.dumps(factors, ensure_ascii=False)
                                                      if factors else None)))


def store_report(kind, ok, sec=0, chars=0, quota_used=0, err=""):
    """报表执行留痕。**故意不存 stdout**——正文里是持仓明细与金额，共享库里不放。"""
    conf = db_config()
    if not (conf["enabled"] and conf["store_report"]):
        return False
    sql = ("INSERT INTO board_report_run (ts, kind, ok, rc, duration_ms, stdout_chars,"
           " quota_used, err_snippet) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)")
    return _write(conf, lambda cur: cur.execute(
        sql, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), str(kind)[:8], 1 if ok else 0,
              0 if ok else 1, int(float(sec) * 1000), int(chars), int(quota_used),
              re.sub(r"\s+", " ", str(err or ""))[:250])))


# ---------------------------------------------------------------- 自检 / 状态

def status(quiet=True):
    """连接参数来源 + 各表行数。只读，且**不回显 host/user/口令**（公网版也挂着这个接口）。"""
    conf = db_config()
    out = {"ok": False, "module": "db", "enabled": conf["enabled"],
           "password_from": conf["password_from"] or "(无)",
           "reason": conf.get("reason", ""), "schema_file": os.path.relpath(SCHEMA_FILE, ROOT).replace("\\", "/"),
           "schema_present": os.path.isfile(SCHEMA_FILE),
           "statements": len(schema_statements()) if os.path.isfile(SCHEMA_FILE) else 0,
           "switches": {k: conf[k] for k in ("store_btc", "store_series", "store_risk", "store_report")},
           "tables": {}, "meta": {}}
    if not conf["enabled"]:
        return out
    conn = None
    try:
        conn = _connect(conf)
        with conn.cursor() as cur:
            have = {r[0] for r in _rows(cur, "SHOW TABLES", ())}
            for t in TABLES:
                out["tables"][t] = (_rows(cur, "SELECT COUNT(*) FROM `%s`" % t, ()))[0][0] if t in have else None
            if "board_meta" in have:
                out["meta"] = {r[0]: r[1] for r in _rows(cur, "SELECT k, v FROM board_meta", ())}
            out["version_ok"] = out["meta"].get("schema_version") == SCHEMA_VERSION
        out["ok"] = True
    except Exception as e:
        out["error"] = "%s: %s" % (type(e).__name__, str(e)[:180])
        if not quiet:
            out["trace"] = traceback.format_exc(limit=1)
    finally:
        try:
            if conn is not None and _conn_for_test is None:
                conn.close()
        except Exception:
            pass
    return out


def r_health(q):
    d = status()
    return 200, d


ROUTES = {"health": r_health}


def _cli(argv):
    if "--print-sql" in argv:
        for i, s in enumerate(schema_statements(), 1):
            print("-- [%d] %s" % (i, s.splitlines()[0][:78]))
        return 0
    if "--init" in argv:
        r = init_schema()
        print(r)
        return 0 if r.get("ok") else 1
    if "--status" in argv:
        s = status(quiet=False)
        for k, v in s.items():
            print("%-14s %s" % (k, v))
        return 0 if s.get("ok") else 1
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli(__import__("sys").argv[1:]))
