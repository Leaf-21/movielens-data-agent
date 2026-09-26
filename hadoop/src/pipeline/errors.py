#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
错误响应模块

职责：按 docs/接口规范文档.md 第 15 节生成统一的错误响应。

接口规范第 15 节规定，所有接口发生错误时统一返回：

    {
      "task_id": "task_20260926_0001",
      "status": "FAILED",
      "error": {
        "code": "HADOOP_EXECUTION_ERROR",
        "message": "Hadoop 数据清洗执行失败"
      }
    }

并给出 8 个错误码。第 15 节同时强调：
"执行失败时必须返回实际错误，不允许使用默认评分或虚假结果替代。"

设计说明
--------
为什么需要专门的模块：
  Agent（成员B）需要按 error.code 分类处理失败——例如
  DATA_NOT_FOUND 提示用户检查数据、HADOOP_EXECUTION_ERROR 提示重试，
  两者对用户的提示与后续动作不同。如果只往 stderr 打文本，
  Agent 无法结构化判断，只能笼统报"失败了"。
"""

import json
import sys

# ---------------------------------------------------------------------------
# 错误码（与接口规范第 15 节完全一致）
# ---------------------------------------------------------------------------

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

# 各错误码的默认说明（供未指定 message 时使用）
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


class StageError(Exception):
    """
    阶段执行失败。

    stage  出错的阶段（BEFORE_SCORE / CLEANING / AFTER_SCORE / ...）
    code   接口规范第 15 节的错误码
    message 面向用户的说明（应说明失败环节与原因）
    detail 可选的技术细节，供排查使用（不替代 message）
    """

    def __init__(self, stage, code, message, detail=None):
        if code not in ERROR_CODES:
            raise ValueError('未知错误码: %r（必须是 %r 之一）' % (code, list(ERROR_CODES)))
        super(StageError, self).__init__(message)
        self.stage = stage
        self.code = code
        self.message = message
        self.detail = detail


def build_error_response(task_id, stage, code, message, detail=None):
    """
    组装错误响应。

    严格遵循接口规范第 15 节：只包含 task_id / status / error 三部分。
    额外附加的 stage 与 detail 用于帮助定位问题，
    属于本项目的补充信息，不影响契约字段。
    """
    if code not in ERROR_CODES:
        raise ValueError('未知错误码: %r' % code)

    resp = {
        'task_id': task_id,
        'status': 'FAILED',
        'error': {
            'code': code,
            'message': message,
        },
    }
    # 补充信息：说明失败环节，便于按接口规范第 6 节向用户交代"失败环节和原因"
    if stage:
        resp['error']['stage'] = stage
    if detail:
        resp['error']['detail'] = detail
    return resp


def emit_error(task_id, stage, code, message, detail=None, stream=None):
    """
    把错误响应以 JSON 形式写到 stdout。

    写 stdout 而非 stderr 的原因：Agent 通过标准输出读取接口响应，
    错误响应也是响应的一部分。同时便于人工直接查看。
    """
    resp = build_error_response(task_id, stage, code, message, detail)
    out = stream or sys.stdout
    out.write(json.dumps(resp, ensure_ascii=False, indent=2))
    out.write('\n')
    return resp
