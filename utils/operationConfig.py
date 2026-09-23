#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
统一读取 config/config.ini：钉钉/ TG/代理/各 API Key/报表与底部提示阈值等。
所有路径通过 TestData.data_dir("config", "config.ini") 定位，编码 utf-8-sig 兼容 BOM。
"""
import configparser
import sys

from utils.operationTestdata import TestData


class OperationConfig(object):
    """封装 config.ini 的读取，各 get_* 方法对应不同 [section] 或业务用途。"""

    def __init__(self):
        self.testdata = TestData()

    def get_sendmail_info(self, contents="mail"):
        """读取 [mail] 段：发件人、SMTP 主机、密码等，用于邮件推送。"""
        tmpdict = {}
        config = configparser.ConfigParser()
        config.read(self.testdata.data_dir("config", "config.ini"), encoding="utf-8-sig")
        send_user = config.get(contents, "SEND_USER")
        send_from = config.get(contents, "SEND_FROM")
        host = config.get(contents, "SMTP_HOST")
        login_pwd = config.get(contents, "MAIL_PASS")

        tmpdict['send_user'] = send_user
        tmpdict['send_from'] = send_from
        tmpdict['login_pwd'] = login_pwd
        tmpdict['host'] = host
        return tmpdict

    def get_apiinfo(self, contents="url"):
        """读取 [url] 段：API_FEAR、API_ARH999、API_ARH999NEW 等外部接口地址。"""
        envdic = {}
        config = configparser.ConfigParser()
        config.read(self.testdata.data_dir("config", "config.ini"), encoding="utf-8-sig")
        api_fear = config.get(contents, "API_FEAR")
        api_arh999 = config.get(contents, "API_ARH999")
        api_arh999new = config.get(contents, "API_ARH999NEW")
        api_arh999new_key = config.get(contents, "API_ARH999NEW_KEY")

        envdic['api_fear'] = api_fear
        envdic['api_arh999'] = api_arh999
        envdic['api_arh999new'] = api_arh999new
        envdic['api_arh999new_key'] = api_arh999new_key
        return envdic

    def get_looknode_chart_api_url(self, contents="url"):
        """读取 [url] 下的 LOOKNODE_CHART_API（可选），用于 handle_mvrv 直接请求图表数据。"""
        try:
            config = configparser.ConfigParser()
            config.read(self.testdata.data_dir("config", "config.ini"), encoding="utf-8-sig")
            if config.has_section(contents) and config.has_option(contents, "LOOKNODE_CHART_API"):
                url = config.get(contents, "LOOKNODE_CHART_API").strip()
                return url if url else None
        except Exception:
            pass
        return None

    def get_glassnode_api_key(self, contents="glassnode"):
        """读取 [glassnode] 下的 API_KEY，用于 Balanced Price 等指标。"""
        try:
            config = configparser.ConfigParser()
            config.read(self.testdata.data_dir('config', 'config.ini'), encoding="utf-8-sig")
            if config.has_section(contents) and config.has_option(contents, 'API_KEY'):
                return config.get(contents, 'API_KEY').strip()
        except Exception:
            pass
        return ""

    def get_bmpro_api_key(self, contents="bmpro"):
        """读取 [bmpro] 下的 API_KEY，用于 Bitcoin Magazine Pro API（如 CVDD）。Pro 订阅需付费。"""
        try:
            config = configparser.ConfigParser()
            config.read(self.testdata.data_dir("config", "config.ini"), encoding="utf-8-sig")
            if config.has_section(contents) and config.has_option(contents, "API_KEY"):
                return config.get(contents, "API_KEY").strip()
        except Exception:
            pass
        return ""

    def get_coinglass_api_key(self, contents="coinglass"):
        """读取 [coinglass] 下的 API_KEY，用于 CoinGlass API v4（如 NUPL）。见 https://www.coinglass.com/user"""
        try:
            config = configparser.ConfigParser()
            config.read(self.testdata.data_dir("config", "config.ini"), encoding="utf-8-sig")
            if config.has_section(contents) and config.has_option(contents, "API_KEY"):
                return config.get(contents, "API_KEY").strip()
        except Exception:
            pass
        return ""

    def get_cryptoquant_api_key(self, contents="cryptoquant"):
        """读取 [cryptoquant] 下的 API_KEY，用于 CryptoQuant API（如 NUPL）。见 https://cryptoquant.com/settings/api"""
        try:
            config = configparser.ConfigParser()
            config.read(self.testdata.data_dir("config", "config.ini"), encoding="utf-8-sig")
            if config.has_section(contents) and config.has_option(contents, "API_KEY"):
                return config.get(contents, "API_KEY").strip()
        except Exception:
            pass
        return ""

    def get_counterflow_api_key(self, contents="counterflow"):
        """读取 [counterflow] 下的 API_KEY，用于 Bitcoin CounterFlow API（如 NUPL）。需 Nakamoto Pro 订阅，见 https://bitcoincounterflow.com/api-access/"""
        try:
            config = configparser.ConfigParser()
            config.read(self.testdata.data_dir("config", "config.ini"), encoding="utf-8-sig")
            if config.has_section(contents) and config.has_option(contents, "API_KEY"):
                return config.get(contents, "API_KEY").strip()
        except Exception:
            pass
        return ""

    def get_proxy_config(self, contents="proxy"):
        """
        读取 [proxy] 配置，返回 requests 可用的 proxies 字典，未启用时返回 None。
        返回: None 或 {}（直连）或 {"http": "...", "https": "..."}
        按操作系统：Linux / FreeBSD 返回 {} 强制直连（避免本机未开代理或环境变量代理导致 Connection refused）；
        Windows 使用 config 配置，网络异常时走代理。
        注意：返回 {} 而非 None，以便 requests 明确不走代理、不读环境变量 HTTP_PROXY/HTTPS_PROXY。
        """
        if sys.platform.startswith("linux") or sys.platform.startswith("freebsd"):
            return {}
        try:
            config = configparser.ConfigParser()
            config.read(self.testdata.data_dir("config", "config.ini"), encoding="utf-8-sig")
            if not config.has_section(contents):
                return None
            enabled = config.get(contents, "ENABLED", fallback="0").strip().lower()
            if enabled in ("0", "false", "no", ""):
                return None
            host = config.get(contents, "HOST", fallback="127.0.0.1").strip()
            port_http = config.get(contents, "PORT_HTTP", fallback="7897").strip()
            port_https = config.get(contents, "PORT_HTTPS", fallback="7899").strip()
            return {
                "http": f"http://{host}:{port_http}",
                "https": f"http://{host}:{port_https}",
            }
        except Exception:
            return None

    def get_fuckbtc_report_config(self, contents="fuckbtc_report"):
        """读取 [fuckbtc_report] 下的 ATH_PRICE、ATH_DATE，用于报表「从历史最高到现在」统计。"""
        try:
            config = configparser.ConfigParser()
            config.read(self.testdata.data_dir('config', 'config.ini'), encoding="utf-8-sig")
            if not config.has_section(contents):
                return {"ath_price": 126199, "ath_date": "2025-10-06"}
            ath_price = 126199
            ath_date = "2025-10-06"
            if config.has_option(contents, "ATH_PRICE"):
                ath_price = config.getint(contents, "ATH_PRICE")
            if config.has_option(contents, "ATH_DATE"):
                ath_date = config.get(contents, "ATH_DATE").strip()
            return {"ath_price": ath_price, "ath_date": ath_date}
        except Exception:
            return {"ath_price": 126199, "ath_date": "2025-10-06"}

    def get_bottom_alert_config(self, contents="bottom_alert"):
        """
        读取 [bottom_alert] 下的底部提示阈值，支持多组（逗号分隔）。
        返回: drop_pct_trigger(list), fear_greed_max(list), cbbi_max(list),
              ahr999_buy_zone_max(float), tolerance_pct(float),
              bottom_low_mult, bottom_high_mult, wma_mult(float).
        """
        def _parse_list_float(s, default):
            if not s or not str(s).strip():
                return default
            out = []
            for x in str(s).split(","):
                try:
                    out.append(float(x.strip()))
                except (TypeError, ValueError):
                    continue
            return out if out else default

        def _parse_list_int(s, default):
            if not s or not str(s).strip():
                return default
            out = []
            for x in str(s).split(","):
                try:
                    out.append(int(float(x.strip())))
                except (TypeError, ValueError):
                    continue
            return out if out else default

        def _parse_float(s, default):
            if s is None or str(s).strip() == "":
                return default
            try:
                return float(str(s).strip())
            except (TypeError, ValueError):
                return default

        def _parse_int(s, default):
            if s is None or str(s).strip() == "":
                return default
            try:
                return int(float(str(s).strip()))
            except (TypeError, ValueError):
                return default

        defaults = {
            "bottom_alert_num": 2,
            "drop_pct_trigger": [65, 70, 75, 80],
            "fear_greed_max": [25, 30],
            "cbbi_max": [20, 35],
            "ahr999_buy_zone_max": 0.45,
            "volume_ratio_max": [0.5, 0.55],
            "mvrv_max": [0.95, 1.0],
            "nupl_max": [0, 0.25],
            "supply_in_profit_max": [50, 55],
            "cvdd_price_mult": 1.05,
            "tolerance_pct": 10.0,
            "bottom_low_mult": 0.20,
            "bottom_high_mult": 0.35,
            "wma_mult": 1.05,
        }
        try:
            config = configparser.ConfigParser()
            config.read(self.testdata.data_dir("config", "config.ini"), encoding="utf-8-sig")
            if not config.has_section(contents):
                return defaults
            cfg = {}
            cfg["bottom_alert_num"] = _parse_int(
                config.get(contents, "BOTTOM_ALERT_NUM", fallback=""), defaults["bottom_alert_num"]
            )
            cfg["drop_pct_trigger"] = _parse_list_float(
                config.get(contents, "DROP_PCT_TRIGGER", fallback=""), defaults["drop_pct_trigger"]
            )
            cfg["fear_greed_max"] = _parse_list_int(
                config.get(contents, "FEAR_GREED_MAX", fallback=""), defaults["fear_greed_max"]
            )
            cfg["cbbi_max"] = _parse_list_float(
                config.get(contents, "CBBI_MAX", fallback=""), defaults["cbbi_max"]
            )
            cfg["ahr999_buy_zone_max"] = _parse_float(
                config.get(contents, "AHR999_BUY_ZONE_MAX", fallback=""), defaults["ahr999_buy_zone_max"]
            )
            cfg["volume_ratio_max"] = _parse_list_float(
                config.get(contents, "VOLUME_RATIO_MAX", fallback=""), defaults["volume_ratio_max"]
            )
            if config.has_option(contents, "MVRV_MAX"):
                cfg["mvrv_max"] = _parse_list_float(
                    config.get(contents, "MVRV_MAX", fallback=""), defaults["mvrv_max"]
                )
            else:
                cfg["mvrv_max"] = defaults["mvrv_max"]
            if config.has_option(contents, "NUPL_MAX"):
                cfg["nupl_max"] = _parse_list_float(
                    config.get(contents, "NUPL_MAX", fallback=""), defaults["nupl_max"]
                )
            else:
                cfg["nupl_max"] = defaults["nupl_max"]
            if config.has_option(contents, "SUPPLY_IN_PROFIT_MAX"):
                cfg["supply_in_profit_max"] = _parse_list_float(
                    config.get(contents, "SUPPLY_IN_PROFIT_MAX", fallback=""), defaults["supply_in_profit_max"]
                )
            else:
                cfg["supply_in_profit_max"] = defaults["supply_in_profit_max"]
            if config.has_option(contents, "CVDD_PRICE_MULT"):
                cfg["cvdd_price_mult"] = _parse_float(
                    config.get(contents, "CVDD_PRICE_MULT", fallback=""), defaults["cvdd_price_mult"]
                )
            else:
                cfg["cvdd_price_mult"] = defaults["cvdd_price_mult"]
            cfg["tolerance_pct"] = _parse_float(
                config.get(contents, "TOLERANCE_PCT", fallback=""), defaults["tolerance_pct"]
            )
            cfg["bottom_low_mult"] = _parse_float(
                config.get(contents, "BOTTOM_LOW_MULT", fallback=""), defaults["bottom_low_mult"]
            )
            cfg["bottom_high_mult"] = _parse_float(
                config.get(contents, "BOTTOM_HIGH_MULT", fallback=""), defaults["bottom_high_mult"]
            )
            cfg["wma_mult"] = _parse_float(
                config.get(contents, "WMA_MULT", fallback=""), defaults["wma_mult"]
            )
            return cfg
        except Exception:
            return defaults

    def get_top_alert_config(self, contents="top_alert"):
        """
        读取 [top_alert] 下的顶部提示阈值，支持多组（逗号分隔）。
        返回: drop_pct_max(list), fear_greed_min(list), cbbi_min(list),
              ahr999_danger_min(list), tolerance_pct(float), top_zone_low(float), wma_top_mult(float).
        """
        def _parse_list_float(s, default):
            if not s or not str(s).strip():
                return default
            out = []
            for x in str(s).split(","):
                try:
                    out.append(float(x.strip()))
                except (TypeError, ValueError):
                    continue
            return out if out else default

        def _parse_list_int(s, default):
            if not s or not str(s).strip():
                return default
            out = []
            for x in str(s).split(","):
                try:
                    out.append(int(float(x.strip())))
                except (TypeError, ValueError):
                    continue
            return out if out else default

        def _parse_float(s, default):
            if s is None or str(s).strip() == "":
                return default
            try:
                return float(str(s).strip())
            except (TypeError, ValueError):
                return default

        defaults = {
            "drop_pct_max": [20, 30],
            "fear_greed_min": [75, 80],
            "cbbi_min": [80, 85],
            "ahr999_danger_min": [2, 3],
            "tolerance_pct": 10.0,
            "top_zone_low": 0.80,
            "wma_top_mult": 2.0,
        }
        try:
            config = configparser.ConfigParser()
            config.read(self.testdata.data_dir("config", "config.ini"), encoding="utf-8-sig")
            if not config.has_section(contents):
                return defaults
            cfg = {}
            cfg["drop_pct_max"] = _parse_list_float(
                config.get(contents, "DROP_PCT_MAX", fallback=""), defaults["drop_pct_max"]
            )
            cfg["fear_greed_min"] = _parse_list_int(
                config.get(contents, "FEAR_GREED_MIN", fallback=""), defaults["fear_greed_min"]
            )
            cfg["cbbi_min"] = _parse_list_float(
                config.get(contents, "CBBI_MIN", fallback=""), defaults["cbbi_min"]
            )
            cfg["ahr999_danger_min"] = _parse_list_float(
                config.get(contents, "AHR999_DANGER_MIN", fallback=""), defaults["ahr999_danger_min"]
            )
            cfg["tolerance_pct"] = _parse_float(
                config.get(contents, "TOLERANCE_PCT", fallback=""), defaults["tolerance_pct"]
            )
            cfg["top_zone_low"] = _parse_float(
                config.get(contents, "TOP_ZONE_LOW", fallback=""), defaults["top_zone_low"]
            )
            cfg["wma_top_mult"] = _parse_float(
                config.get(contents, "WMA_TOP_MULT", fallback=""), defaults["wma_top_mult"]
            )
            return cfg
        except Exception:
            return defaults

    def get_testenv_mysql(self, contents="mysql"):
        '''contents config file flag'''
        mysqldic = {}
        config = configparser.ConfigParser()
        config.read(self.testdata.data_dir("config", "config.ini"), encoding="utf-8-sig")
        mysqlhost = config.get(contents, "HOST")
        mysqlport = config.get(contents, "PORT")
        mysqluser = config.get(contents, "USER")
        mysqlpasswd = config.get(contents, "PASSWD")
        mysqldatabases = config.get(contents, "DADABASES")
        mysqlcharset = config.get(contents, "CHARSET")
        mysqldic['host'] = mysqlhost
        mysqldic['port'] = mysqlport
        mysqldic['user'] = mysqluser
        mysqldic['password'] = mysqlpasswd
        mysqldic['databases'] = mysqldatabases
        mysqldic['charsetdb'] = mysqlcharset
        return mysqldic


if __name__ == "__main__":
    a = OperationConfig()
    print(type(a.get_sendmail_info()))
