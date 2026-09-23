# -*- coding: utf-8 -*-
# @Time    : 2019/5/8 9:42
# @Author  : alvin
# @File    : qatestdb.py
# @Software: PyCharm
import  time
import  pymysql
from utils.operationConfig import OperationConfig
from utils.logger import Logger
pymysql.install_as_MySQLdb()

class MySQLAction:

    def __init__(self, dbname=None, dbhost=None):
        self._config = OperationConfig()
        self._logger = Logger()
        if dbhost is None:
            self._host = self._config.getMysqlConfig().get("host")
        else:
            self._host = "HOST"

        self._port = self._config.getMysqlConfig().get("port")
        self._user = self._config.getMysqlConfig().get("user")
        self._passwd = self._config.getMysqlConfig().get("password")
        self._charset = self._config.getMysqlConfig().get("charsetdb")

        if dbname is None:
            self._dbname=self._config.getMysqlConfig().get("databases")
        else:
            self._dbname = "DBNAME"

        self._conn = self._connectMySQL()
        if (self._conn):
            self._cursor = self._conn.cursor()

    def _connectMySQL(self):
        conn = False
        try:
            conn = pymysql.Connect(host=self._host ,port=int(self._port),
                                   user=self._user ,passwd=self._passwd,
                                   db=self._dbname ,charset=self._charset)
            # port 需要int
        except :
            print("conn mysql is error!")
        return conn



    def exec_insert(self,insertsql,data):
        '''
        插入多条数据
        :param insert ql語句
        :param data: 執行的數據values
        :return: 成功True
        '''
        res=False
        if(self._conn):
            try:
                self._cursor.executemany(insertsql,data)
                self._conn.commit()
                res = True
            except Exception :
                res=False
                self._logger.warn("insert sql database exception")
                self._conn.close()
                self._cursor.close()
            return res

    def exec_del(self,delsql ):
        res = False
        if(self._conn):
            try:
                self._cursor.execute(delsql)
                self._conn.commit()
                # print('成功删除', self._cursor.rowcount, '条数据')
                res =True
            except Exception  :
                res = False
                self._logger.warn("del database exception")
                self._conn.close()
                self._cursor.close()
            return res
    def exec_updata(self,sql):
        '''
        修改数据
        :param sql:
        :return:True False
        '''
        res=''
        if (self._conn):
            try:
                self._cursor.execute(sql)
                self._conn.commit()
                res = True
            except Exception as e:
                self._conn.rollback()
                raise  e
                res = False
            finally:
                self._conn.close()
                self._cursor.close()
            return res

    def exec_search(self,sql):
        res = ''
        if(self._conn):
            try:
                self._cursor.execute(sql)
                res = self._cursor.fetchall()
            except Exception  :
                res = False
                self._logger.warn("query database exception")
                self._conn.close()
                self._cursor.close()
            return res

# if __name__ == "__main__":
#
#     sql = "insert into bc_uv_detail (c_date, app_name, company, channel_code, uv_num, create_time, package_name) " \
#           "values (%s, %s, %s, %s, %s, %s, %s )"
#     paramslist = [(
#             1554048000,'腾讯动漫','上海米节信息科技有限公司',
#             "qudao",1554083419,"package"),]
#     a = MySQLAction()
#     res = a.exec_updata(sql, paramslist)
#     print(res)