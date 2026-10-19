#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分类工具的公共常量、错误码与结果封装。

字段命名以《迭代二接口扩展规范》第三节为准：
- ``predicted_class`` 取 ``HIGH_RATING`` / ``LOW_RATING``；
- ``positive_probability`` 只在算法真实支持时填写，否则为 ``null`` 并给出原因；
- 失败返回结构化错误，不返回占位结果。

错误码与迭代一 ``agent/src/errors.py`` 的 8 个码不完全重合（迭代一没有
``UNKNOWN_USER`` 等分析类错误）。本模块保留迭代二的细分码，同时提供
``to_legacy_error`` 把细分码映射回迭代一契约，供 Agent 层按需选择。
"""

TASK_TYPE = 'classification'

HIGH_RATING = 'HIGH_RATING'
LOW_RATING = 'LOW_RATING'

ALGORITHM_SLUGS = ('gnb', 'cart')

ALGORITHM_NAMES = {
    'gnb': 'Gaussian Naive Bayes',
    'cart': 'Decision Tree (entropy / ID3-C4.5 style split)',
}

FEATURE_VERSION = 'feat-v1'
SPLIT_VERSION = 'split-v1'

# 迭代二接口扩展规范 §2.1 / §六
INVALID_REQUEST = 'INVALID_REQUEST'
INVALID_PARAMETER = 'INVALID_PARAMETER'
DATA_UNAVAILABLE = 'DATA_UNAVAILABLE'
VERSION_MISMATCH = 'VERSION_MISMATCH'
UNKNOWN_USER = 'UNKNOWN_USER'
UNKNOWN_MOVIE = 'UNKNOWN_MOVIE'
INSUFFICIENT_HISTORY = 'INSUFFICIENT_HISTORY'
MODEL_NOT_FOUND = 'MODEL_NOT_FOUND'
ALGORITHM_ERROR = 'ALGORITHM_ERROR'
INTERNAL_ERROR = 'INTERNAL_ERROR'

# 细分码 -> 迭代一错误码（agent/src/errors.py 的 8 个码）
LEGACY_MAP = {
    INVALID_REQUEST: 'INVALID_REQUEST',
    INVALID_PARAMETER: 'INVALID_REQUEST',
    DATA_UNAVAILABLE: 'DATA_NOT_FOUND',
    VERSION_MISMATCH: 'INVALID_DATA_VERSION',
    UNKNOWN_USER: 'INVALID_REQUEST',
    UNKNOWN_MOVIE: 'INVALID_REQUEST',
    INSUFFICIENT_HISTORY: 'INVALID_REQUEST',
    MODEL_NOT_FOUND: 'DATA_NOT_FOUND',
    ALGORITHM_ERROR: 'AGENT_EXECUTION_ERROR',
    INTERNAL_ERROR: 'INTERNAL_ERROR',
}

DEFAULT_MESSAGES = {
    INVALID_REQUEST: '请求参数错误',
    INVALID_PARAMETER: '参数超出允许范围',
    DATA_UNAVAILABLE: '数据不可用',
    VERSION_MISMATCH: '数据或特征版本不匹配',
    UNKNOWN_USER: '未知用户',
    UNKNOWN_MOVIE: '未知电影',
    INSUFFICIENT_HISTORY: '历史行为不足',
    MODEL_NOT_FOUND: '模型不存在',
    ALGORITHM_ERROR: '算法执行失败',
    INTERNAL_ERROR: '内部错误',
}


class ToolError(Exception):
    """分类工具的结构化失败。调用方应转成接口扩展规范 §六 的错误响应。"""

    def __init__(self, code, message=None, detail=None):
        if code not in DEFAULT_MESSAGES:
            raise ValueError('未知错误码: %r' % (code,))
        self.code = code
        self.message = message or DEFAULT_MESSAGES[code]
        self.detail = detail or {}
        super(ToolError, self).__init__(self.message)

    def to_dict(self):
        err = {'code': self.code, 'message': self.message}
        if self.detail:
            err['details'] = self.detail
        return {'status': 'FAILED', 'error': err}

    def to_legacy_error(self, stage):
        """转成迭代一接口规范 §15 的 error 对象（保留细分码在 detail 中）。"""
        detail = dict(self.detail)
        detail['sub_code'] = self.code
        return {
            'code': LEGACY_MAP[self.code],
            'message': self.message,
            'stage': stage,
            'detail': detail,
        }


def prediction_result(algorithm, model_version, predicted_class, positive_probability,
                      decision_score, parameters, metrics, limitations,
                      score_type, features_used=None, explain=None,
                      prediction_time_basis=None):
    """组装单个算法的分类结果（接口扩展规范 §3.2 的 results[] 元素）。"""
    item = {
        'algorithm': algorithm,
        'algorithm_slug': algorithm_slug_of(algorithm),
        'model_version': model_version,
        'predicted_class': predicted_class,
        'positive_probability': positive_probability,
        'decision_score': decision_score,
        'score_type': score_type,
        'parameters': parameters or {},
        'metrics': metrics or {},
        'limitations': list(limitations or []),
    }
    if features_used is not None:
        item['features_used'] = features_used
    if explain is not None:
        item['explain'] = explain
    if prediction_time_basis is not None:
        item['prediction_time_basis'] = prediction_time_basis
    return item


def algorithm_slug_of(name):
    for slug, algo in ALGORITHM_NAMES.items():
        if name == algo or name == slug:
            return slug
    return name
