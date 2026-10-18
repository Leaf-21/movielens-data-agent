#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
迭代二聚类工具的公共件（成员B）

- AnalysisError：带接口扩展规范 §2.1 错误码的异常，
  调度层据此把任务置为 FAILED 并如实写出 code/message/details。
- 校验值 / Git commit / UTC 时间戳：可复现性元数据（数据与实验规范 §一.2）。

只用标准库。
"""

import datetime
import hashlib
import os
import subprocess

# 迭代二接口扩展规范 §2.1/§六 的错误码常量（与文档一致，逐字登记）
INVALID_REQUEST = 'INVALID_REQUEST'
DATA_UNAVAILABLE = 'DATA_UNAVAILABLE'
VERSION_MISMATCH = 'VERSION_MISMATCH'
UNKNOWN_USER = 'UNKNOWN_USER'
UNKNOWN_MOVIE = 'UNKNOWN_MOVIE'
INSUFFICIENT_HISTORY = 'INSUFFICIENT_HISTORY'
MODEL_NOT_FOUND = 'MODEL_NOT_FOUND'
INVALID_PARAMETER = 'INVALID_PARAMETER'
ALGORITHM_ERROR = 'ALGORITHM_ERROR'
INTERNAL_ERROR = 'INTERNAL_ERROR'

ERROR_CODES = (INVALID_REQUEST, DATA_UNAVAILABLE, VERSION_MISMATCH, UNKNOWN_USER,
               UNKNOWN_MOVIE, INSUFFICIENT_HISTORY, MODEL_NOT_FOUND,
               INVALID_PARAMETER, ALGORITHM_ERROR, INTERNAL_ERROR)


class AnalysisError(Exception):
    """分析任务失败：必须携带规范登记的错误码。"""

    def __init__(self, code, message, details=None):
        assert code in ERROR_CODES, '未登记的错误码: %r' % code
        super(AnalysisError, self).__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_error_dict(self):
        d = {'code': self.code, 'message': self.message}
        if self.details:
            d['details'] = self.details
        return d


def sha256_file(path, block=1 << 20):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            b = f.read(block)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def code_version():
    """当前 Git commit（数据与实验规范要求登记）；取不到就明确 unknown。"""
    repo = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    try:
        out = subprocess.run(['git', '-C', repo, 'rev-parse', '--short', 'HEAD'],
                             capture_output=True, text=True, timeout=5)
        if out.returncode == 0:
            return out.stdout.strip() or 'unknown'
    except Exception:
        pass
    return 'unknown'


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        '%Y-%m-%dT%H:%M:%SZ')
