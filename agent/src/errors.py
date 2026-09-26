#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent 侧错误定义

错误码与接口规范第 15 节完全一致（8 个），并且与
hadoop/src/pipeline/errors.py 的取值逐字对应 —— 这是三层共用的契约常量。

AgentError 由调度层抛出/捕获，用于把失败写成结构化响应：
接口规范第 23 节要求"错误状态能够正常返回"且"失败时不会生成占位结果"。
"""

INVALID_REQUEST = 'INVALID_REQUEST'
DATA_NOT_FOUND = 'DATA_NOT_FOUND'
INVALID_DATA_VERSION = 'INVALID_DATA_VERSION'
INVALID_RULE_VERSION = 'INVALID_RULE_VERSION'
HADOOP_EXECUTION_ERROR = 'HADOOP_EXECUTION_ERROR'
QUALITY_SCORE_ERROR = 'QUALITY_SCORE_ERROR'
AGENT_EXECUTION_ERROR = 'AGENT_EXECUTION_ERROR'
INTERNAL_ERROR = 'INTERNAL_ERROR'

ERROR_CODES = (
    INVALID_REQUEST,
    DATA_NOT_FOUND,
    INVALID_DATA_VERSION,
    INVALID_RULE_VERSION,
    HADOOP_EXECUTION_ERROR,
    QUALITY_SCORE_ERROR,
    AGENT_EXECUTION_ERROR,
    INTERNAL_ERROR,
)

# 各错误码面向用户的默认说明（与成员A的 DEFAULT_MESSAGES 保持一致的措辞，
# 保证前端无论在哪一层捕获到失败，看到的语言风格统一）
DEFAULT_MESSAGES = {
    INVALID_REQUEST: '请求参数错误',
    DATA_NOT_FOUND: '所需数据不存在',
    INVALID_DATA_VERSION: '数据版本错误',
    INVALID_RULE_VERSION: '清洗规则版本错误',
    HADOOP_EXECUTION_ERROR: 'Hadoop 执行失败',
    QUALITY_SCORE_ERROR: '质量评分执行失败',
    AGENT_EXECUTION_ERROR: 'Agent 执行失败',
    INTERNAL_ERROR: '系统内部错误',
}


class AgentError(Exception):
    """任务执行失败。字段语义与成员A的 StageError 相同。"""

    def __init__(self, stage, code, message, detail=None):
        if code not in ERROR_CODES:
            raise ValueError('未知错误码: %r' % code)
        super(AgentError, self).__init__(message)
        self.stage = stage
        self.code = code
        self.message = message
        self.detail = detail

    def to_dict(self):
        """转为接口规范第 15 节的 error 对象。"""
        d = {'code': self.code, 'message': self.message}
        if self.stage:
            d['stage'] = self.stage
        if self.detail:
            d['detail'] = self.detail
        return d


def build_error_response(task_id, stage, code, message, detail=None):
    """组装统一错误响应（与 hadoop/src/pipeline/errors.py 同构）。"""
    if code not in ERROR_CODES:
        raise ValueError('未知错误码: %r' % code)
    resp = {
        'task_id': task_id,
        'status': 'FAILED',
        'error': {'code': code, 'message': message},
    }
    if stage:
        resp['error']['stage'] = stage
    if detail:
        resp['error']['detail'] = detail
    return resp
