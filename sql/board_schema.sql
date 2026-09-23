-- ============================================================================
-- 数字资产指标看板 · 落库表结构（MySQL 8.x / serv00 的 m2573_btc）
-- 版本：schema_version = 1（写进 board_meta，api/db.py 启动时核对）
--
-- 怎么跑（本机关着没用，本机既没装 pymysql 也连不到 3306；在能连库的地方跑）：
--   python api/db.py --init          # 读这个文件、逐句执行，幂等，可反复跑
--   python api/db.py --status        # 看连接参数来源与各表行数
--   服务器上：/home/myaibtc/vevns/web3/bin/python api/db.py --init
-- 也可以直接把它喂给客户端：mysql -h mysql11.serv00.com -u m2573_myaibtc -p m2573_btc < sql/board_schema.sql
--
-- 约定（改表前先读，三条都是有意为之）：
--   1. 全部 utf8mb4 / utf8mb4_unicode_ci：verdict、note、error 里会有中文和上下标符号，
--      utf8mb3 存不下 4 字节字符，报 1366 是迟早的事。
--   2. 每天一行、同日覆盖（ON DUPLICATE KEY UPDATE，见 api/db.py），所以「业务日」上有唯一键：
--      看板刷新一次写一次会把库里塞满同一天的重复行，历史曲线就没法画了。
--   3. **只存看板自己的产出**：持仓报表的 stdout 正文（含持仓金额）**不落库**，只存元数据，
--      见 board_report_run 的注释。数据库和这台账号是共享的，别把私密正文写进去。
-- ============================================================================

SET NAMES utf8mb4;

-- ---------------------------------------------------------------------------
-- board_meta：键值元表，只放「这套库自己」的状态（schema_version、init 时间…）。
-- 初始化脚本靠它判断版本，将来加列要按版本号写迁移，不要靠人记住改过什么。
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS board_meta (
  k           VARCHAR(32)  NOT NULL COMMENT '键，如 schema_version / initialized_at',
  v           VARCHAR(255) NOT NULL COMMENT '值，一律字符串',
  updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '本行最后写入时刻',
  PRIMARY KEY (k)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='库内元信息：schema 版本与初始化痕迹';

-- ---------------------------------------------------------------------------
-- board_indicator_daily：所有「一天一个读数」的指标，长表（一个指标一行，不给每个指标建表）。
-- 加一个指标 = 加一个 metric_key，不动表结构；页面 12 张卡里带「入库」标的都落这里，
-- 取数失败的卡也落（value 为 NULL + error 有值），否则「哪天哪个源断了」这种事后最想查的东西没地方查。
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS board_indicator_daily (
  id           BIGINT       NOT NULL AUTO_INCREMENT COMMENT '代理键',
  metric_key   VARCHAR(32)  NOT NULL COMMENT '指标键，与 /api/btc/one?k= 同一个白名单：fear ahr999 cbbi cvdd ema ema_new kdj litb macd mvrv nupl sopr；跨模块新键要带命名空间前缀，如 fred:WALCL',
  metric_name  VARCHAR(64)  NOT NULL DEFAULT '' COMMENT '页面显示名，如「AHR999 定投指数」',
  unit         VARCHAR(16)  NOT NULL DEFAULT '' COMMENT '单位：倍 / % / 美元 / 空串（无量纲）',
  `date`       DATE         NOT NULL COMMENT '指标自身的作为日（上游 asof，UTC），不是抓取时刻——上游晚上更新时这两个会差一天',
  value        DECIMAL(18,6)         COMMENT '读数；取数失败时为 NULL',
  tone         VARCHAR(8)   NOT NULL DEFAULT 'gray' COMMENT '判级：red 顶部/过热、green 底部/多头、gray 中性、bad 取不到',
  verdict      VARCHAR(128) NOT NULL DEFAULT '' COMMENT '判定文案（页面同一句），如「底部区域（<0.44）」',
  src          VARCHAR(64)  NOT NULL DEFAULT '' COMMENT '本轮实际用的上游，如 looknode.com / Kraken OHLC',
  hist_points  SMALLINT     NOT NULL DEFAULT 0 COMMENT '该轮迷你图点数（HIST_POINTS 是抽样目标，实到点数会多，这里存实到）',
  extras_json  TEXT                  COMMENT '明细行（extras）原样 JSON，只作回溯，不当结构化数据查询',
  error        VARCHAR(255) NOT NULL DEFAULT '' COMMENT '取数失败原因（含上游逐条死因），成功时为空串',
  run_id       BIGINT       NOT NULL DEFAULT 0 COMMENT '指向 board_run_log.id，0 = 未知来源轮次',
  created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '首次入库时刻',
  updated_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '同日覆盖时刻',
  PRIMARY KEY (id),
  UNIQUE KEY uk_metric_date (metric_key, `date`) COMMENT '一天一键、同日覆盖的落点',
  KEY idx_date (`date`),
  KEY idx_tone_date (tone, `date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='指标读数（日频，长表）：12 项 BTC 日线指标 + 后续任何「一天一个数」的指标';

-- ---------------------------------------------------------------------------
-- board_series_daily：所有「按日期的数值序列」，同样是长表。
-- 放大图/迷你图的历史、FRED 官方序列、日线收盘价都进这里，键带命名空间：
--   btc:fear / btc:mvrv / …          指标卡的 hist[]（页面放大图就是它）
--   price:daily                      日线收盘（哪个所看 kline_src 列/运行日志）
--   fred:WALCL / fred:SOFR / …       流动性页的官方序列（FRED 序列 ID 原样大写）
-- 一个点一行，不存 JSON 数组：想按日期区间查、想把上游整段历史重放成库里的曲线，数组做不到。
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS board_series_daily (
  series_key  VARCHAR(64)   NOT NULL COMMENT '命名空间:名字，见文件头注释',
  `date`      DATE          NOT NULL COMMENT '该点的日期（上游给什么就是什么，UTC）',
  value       DECIMAL(24,8) NOT NULL COMMENT '点的数值（DECIMAL 不用 FLOAT：价格与指数都要精确，别拿近似值入库）',
  updated_at  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '同日覆盖时刻',
  PRIMARY KEY (series_key, `date`),
  KEY idx_date (`date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='日频数值序列（指标历史 / 价格 / FRED），一点一行';

-- ---------------------------------------------------------------------------
-- board_risk_score_daily：美股崩盘监测页的当日评分。页面里那份是前端按权重算完 POST 回来的，
-- 现在 CSV 与库里各存一份：data/risk_history.csv 继续写（换机迁移要带它），库这一份用来跨端查历史。
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS board_risk_score_daily (
  `date`        DATE         NOT NULL COMMENT '评分日（本地日期，与 CSV 同一口径）',
  ticker        VARCHAR(8)   NOT NULL COMMENT '标的：VOO / QQQ',
  score         DECIMAL(5,1) NOT NULL COMMENT '综合分 0~100，与 CSV 里那一列同值',
  factors_json  TEXT                  COMMENT '六个因子的分项值（前端算出来一并回传时才有），可空',
  updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '同日覆盖时刻',
  PRIMARY KEY (`date`, ticker)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='崩盘监测页每日评分（risk_history.csv 的库内镜像）';

-- ---------------------------------------------------------------------------
-- board_run_log：每轮取数留一行「这轮通了几项、用的哪个日线源、缺的是谁」。
-- 上游断供是事后才知道的事，页面标注只有当下看得见，所以留痕必须在库里。
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS board_run_log (
  id           BIGINT      NOT NULL AUTO_INCREMENT COMMENT '代理键，board_indicator_daily.run_id 指它',
  ts           DATETIME    NOT NULL COMMENT '本轮开始时刻（服务器本地）',
  module       VARCHAR(16) NOT NULL DEFAULT 'btc' COMMENT '哪个模块的轮次：btc / crash / liquidity / allocation',
  ok_count     SMALLINT    NOT NULL DEFAULT 0 COMMENT '本轮有数的项数',
  total_count  SMALLINT    NOT NULL DEFAULT 0 COMMENT '本轮总项数',
  elapsed_ms   INT         NOT NULL DEFAULT 0 COMMENT '整轮耗时（毫秒）',
  spot         DECIMAL(18,2)       COMMENT '本轮的 BTC 现价，可空',
  kline_src    VARCHAR(32) NOT NULL DEFAULT '' COMMENT '本轮实际生效的日线源（多家时任选）',
  failed_keys  VARCHAR(255) NOT NULL DEFAULT '' COMMENT '缺位指标键，逗号分隔，全有数时空串',
  note         VARCHAR(255) NOT NULL DEFAULT '' COMMENT '备注，如「DB 刚启用」「上游大面积超时」',
  PRIMARY KEY (id),
  KEY idx_module_ts (module, ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='取数轮次健康记录';

-- ---------------------------------------------------------------------------
-- board_report_run：点一次持仓报告按钮留一行。⚠ 这张表**故意不存 stdout 正文**——
-- 报表正文里是持仓明细与金额，而这套库和账号是共享环境，写进来等于把私密数据多放一份。
-- 只存元数据：谁、什么时候、哪个 kind、成没成、多快、多少字符、当天第几次。
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS board_report_run (
  id            BIGINT      NOT NULL AUTO_INCREMENT COMMENT '代理键',
  ts            DATETIME    NOT NULL COMMENT '执行时刻（服务器本地）',
  kind          VARCHAR(8)  NOT NULL COMMENT 'crypto / us（与 /api/allocation/report?kind= 同一取值）',
  ok            TINYINT(1)  NOT NULL DEFAULT 0 COMMENT '脚本退出码 0 且没有异常 = 1',
  rc            SMALLINT    NOT NULL DEFAULT 0 COMMENT '子进程退出码',
  duration_ms   INT         NOT NULL DEFAULT 0 COMMENT '执行耗时（毫秒）',
  stdout_chars  INT         NOT NULL DEFAULT 0 COMMENT 'stdout 字符数（只记长度，不记内容）',
  quota_used    SMALLINT    NOT NULL DEFAULT 0 COMMENT '这是当天第几次（含本次），对应 [report] daily_limit',
  err_snippet   VARCHAR(255) NOT NULL DEFAULT '' COMMENT '失败原因首行（截断），成功时空串',
  PRIMARY KEY (id),
  KEY idx_kind_ts (kind, ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='持仓报告执行留痕（不存报表正文）';

-- ============================================================================
-- 版本戳：api/db.py 初始化成功后写；换 schema 时把上面的 DDL 改成幂等迁移、这里的值 +1。
-- ============================================================================
INSERT INTO board_meta (k, v) VALUES ('schema_version', '1')
  ON DUPLICATE KEY UPDATE v = VALUES(v);
INSERT INTO board_meta (k, v) VALUES ('schema_file', 'sql/board_schema.sql')
  ON DUPLICATE KEY UPDATE v = VALUES(v);
