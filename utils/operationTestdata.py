# -*- coding: utf-8 -*-
# @Time    : 2019/9/3 15:36
# @Author  : alvin
# @File    : operationTestdata.py
# @Software: PyCharm
import os
import types
import json
import ast
from utils.logger import  Logger

class TestData(object):

	def __init__(self):
		self.log = Logger()

	def data_dir(self,data='data', fileName=None):
		'''查找文件的路径'''
		# print(os.path.join(os.path.dirname(os.path.dirname(__file__)), data, fileName))
		return os.path.join(os.path.dirname(os.path.dirname(__file__)), data, fileName)


	def write_cpachannel_testdata(self, content):
		'''把cpa_channel_add写到文件中'''
		with open( TestData().data_dir( fileName='cpa_channel_add.json' ), 'w' ) as f:
			f.write( content )


	def get_cpachannel_testdata(self):
		with open( TestData().data_dir( fileName='cpa_channel_add.json' ), 'r' ) as f:
			# print("get_cpatestdata",json.loads( f.readline() ))
			return json.loads( f.readline() )


	def get_cpachannel_testdata_ast(self):
		'''
		字符串返序列化成字典，readlines是列表
		:return:
		'''
		with open( TestData().data_dir( fileName='cpa_channel_add.json' ), 'r' ) as f:
			# print("get_cpatestdata_ast",data)
			# self.log.info( ( ast.literal_eval( data ) ) )
			return ast.literal_eval( f.readline() )

	def write_cpamaterial_testdata(self, content):
		'''把cpa_channel_add写到文件中'''
		with open( TestData().data_dir( fileName='cpa_material_add.json' ), 'w' ) as f:
			f.write( content )

	def get_cpamaterial_testdata_ast(self):
		'''
		字符串返序列化成字典，readlines是列表
		:return:
		'''
		with open( TestData().data_dir( fileName='cpa_material_add.json' ), 'r' ) as f:
			data = f.readline()
			return ast.literal_eval( data )
	#
	# dicttest={"result":{"code":"110002","msg":"设备设备序列号或验证码错误"}}
	# ret=dict_get(dicttest, 'msg', None)
	# print(ret)