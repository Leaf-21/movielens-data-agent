#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hadoop Tool 封装接口（对应 docs/接口规范文档.md 第 8 节）

Agent 不直接触碰 Hadoop 作业细节；本模块把成员A提供的三个 HTTP 端点
（接口规范第 9-11 节）封装为三个工具函数：

    quality_score_before()  ->  POST /hadoop/quality-score/before
    clean_dataset()         ->  POST /hadoop/clean
    quality_score_after()   ->  POST /hadoop/quality-score/after

设计要点
--------
1. 只使用标准库 urllib，与成员A服务层的约定一致：零第三方依赖，
   任何一台能跑 Hadoop 服务的机器拉下代码即可运行。
2. 错误翻译：成员A把"业务失败"也返回 HTTP 200，以
   {status:"FAILED", error:{code,message,stage,detail}} 表达
   （见 hadoop/src/server.py 的 _send_error_response 注释）。
   本模块统一把这种响应翻译成 HadoopToolError 异常，
   调度层只需处理异常，不必在每个调用点重复判断 status 字段。
3. 结果追溯：组装接口规范第 13 节的完整结果需要原始 metrics，
   而 HTTP 响应只含最小契约字段（五维得分 / 清洗统计）。
   成员A已将完整中间结果写入任务状态交接文件
   reports/quality-report/{task_id}.json；本模块以【只读】方式读取。
   ⚠️ Agent 绝不写这个文件，避免与 Hadoop 服务并发写冲突。
4. 真实结果红线（接口规范第 2.2 节）：本模块不生成、不修改、
   不补全任何数值，只做请求转发、响应校验与错误翻译。
"""

import json
import os
import re
import urllib.error
import urllib.request

# ---------------------------------------------------------------------------
# 路径与默认配置
# ---------------------------------------------------------------------------

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))      # agent/tools
AGENT_DIR = os.path.dirname(TOOLS_DIR)                        # agent
REPO_DIR = os.path.dirname(AGENT_DIR)                         # 仓库根

# 任务状态交接文件目录（成员A写入，Agent 只读）
STATE_DIR = os.path.join(REPO_DIR, 'reports', 'quality-report')

# Hadoop 服务地址：接口规范未指定端口，成员A服务层默认 8080。
# 联调时若成员A改了端口，用环境变量覆盖即可，不必改代码。
DEFAULT_BASE_URL = os.environ.get('ML_HADOOP_URL', 'http://127.0.0.1:8080')

# 评分/清洗作业在 Hadoop 上可能运行数分钟，超时给足；
# local 模式（开发调试）同样适用。
DEFAULT_TIMEOUT = float(os.environ.get('ML_HADOOP_TIMEOUT', '900'))

# 五维字段名（接口规范第 12 节）
DIMENSIONS = ('accurate', 'complete', 'unique', 'up_to_date', 'consistent')

# task_id 白名单：防止拼接路径时穿越目录（read_state 用到）
TASK_ID_RE = re.compile(r'^[A-Za-z0-9_.\-]{1,64}$')

# ---------------------------------------------------------------------------
# 错误码字面量：与接口规范第 15 节、hadoop/src/pipeline/errors.py 保持一致。
# 此处独立定义而不是 import 成员A的模块：Agent 与 Hadoop 是两个进程，
# 错误码是契约常量的复制（共 5 个字面量），不会漂移出行为差异。
# ---------------------------------------------------------------------------

INVALID_REQUEST = 'INVALID_REQUEST'
DATA_NOT_FOUND = 'DATA_NOT_FOUND'
HADOOP_EXECUTION_ERROR = 'HADOOP_EXECUTION_ERROR'
QUALITY_SCORE_ERROR = 'QUALITY_SCORE_ERROR'
INTERNAL_ERROR = 'INTERNAL_ERROR'


class HadoopToolError(Exception):
    """
    Hadoop Tool 调用失败。

    stage    出错环节（BEFORE_SCORE / CLEANING / AFTER_SCORE / ...）
    code     接口规范第 15 节的错误码
    message  面向用户的说明
    detail   技术细节（可选，用于排查，不替代 message）
    """

    def __init__(self, stage, code, message, detail=None):
        super(HadoopToolError, self).__init__(message)
        self.stage = stage
        self.code = code
        self.message = message
        self.detail = detail

    def to_dict(self):
        d = {'code': self.code, 'message': self.message}
        if self.stage:
            d['stage'] = self.stage
        if self.detail:
            d['detail'] = self.detail
        return d


class HadoopTool(object):
    """成员A三个 HTTP 端点的类型化封装 + 状态交接文件只读访问。"""

    def __init__(self, base_url=None, timeout=None):
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip('/')
        self.timeout = DEFAULT_TIMEOUT if timeout is None else float(timeout)

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _request(self, method, path, payload=None, stage='PARSE_REQUEST'):
        """发一个 HTTP 请求并把各种失败统一翻译成 HadoopToolError。"""
        url = self.base_url + path
        body = None
        headers = {'Accept': 'application/json'}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            headers['Content-Type'] = 'application/json; charset=utf-8'

        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode('utf-8', 'replace')
                http_status = resp.status
        except urllib.error.HTTPError as e:
            # 4xx/5xx：成员A只在协议级错误时使用（未知路径 / JSON 非法）
            raw = e.read().decode('utf-8', 'replace')
            http_status = e.code
        except urllib.error.URLError as e:
            raise HadoopToolError(
                stage, HADOOP_EXECUTION_ERROR,
                '无法连接 Hadoop 服务：%s' % self.base_url,
                '原因: %s。请确认成员A的服务已启动，例如：\n'
                '  python3 hadoop/src/server.py --mode local --data-dir <数据目录>'
                % e.reason,
            )
        except Exception as e:  # 超时等
            raise HadoopToolError(
                stage, HADOOP_EXECUTION_ERROR,
                '调用 Hadoop 服务异常：%s' % e,
                '接口: %s %s' % (method, url),
            )

        try:
            obj = json.loads(raw)
        except ValueError:
            raise HadoopToolError(
                stage, INTERNAL_ERROR,
                'Hadoop 服务返回了无法解析为 JSON 的响应',
                raw[:500],
            )
        if not isinstance(obj, dict):
            raise HadoopToolError(stage, INTERNAL_ERROR, 'Hadoop 响应不是 JSON 对象', raw[:500])

        # --- 业务失败：HTTP 200 + status=FAILED（成员A的约定）---
        if obj.get('status') == 'FAILED':
            err = obj.get('error') or {}
            raise HadoopToolError(
                err.get('stage') or stage,
                err.get('code') or INTERNAL_ERROR,
                err.get('message') or 'Hadoop 服务返回失败',
                err.get('detail'),
            )

        # --- 协议级失败但没带 status：按 HTTP 码报 ---
        if http_status >= 400:
            raise HadoopToolError(
                stage, INVALID_REQUEST if http_status < 500 else INTERNAL_ERROR,
                'Hadoop 服务返回 HTTP %d' % http_status, raw[:500])

        return obj

    @staticmethod
    def _require_keys(resp, keys, stage, section):
        """校验响应含契约必需字段；缺字段说明服务实现与文档不符。"""
        missing = [k for k in keys if k not in resp]
        if missing:
            code = (QUALITY_SCORE_ERROR if 'scores' in keys
                    else HADOOP_EXECUTION_ERROR)
            raise HadoopToolError(
                stage, code,
                'Hadoop 响应缺少契约字段 %s（接口规范第 %s 节）' % (missing, section),
                '实际字段: %s' % sorted(resp.keys()),
            )

    @staticmethod
    def _require_scores(scores, stage, section):
        """五维键必须齐全（值允许为 None：成员A在无法计算时如实给 null）。"""
        if not isinstance(scores, dict):
            raise HadoopToolError(stage, QUALITY_SCORE_ERROR,
                                  'scores 字段不是对象（接口规范第 %s 节）' % section)
        missing = [d for d in DIMENSIONS if d not in scores]
        if missing:
            raise HadoopToolError(stage, QUALITY_SCORE_ERROR,
                                  'scores 缺少维度 %s（接口规范第 %s 节）' % (missing, section))

    # ------------------------------------------------------------------
    # 三个主要工具（接口规范第 8 节要求的功能必须存在）
    # ------------------------------------------------------------------

    def quality_score_before(self, task_id, data_version, score_config=None):
        """清洗前质量评分。接口规范第 9 节。"""
        payload = {'task_id': task_id, 'data_version': data_version}
        if score_config:
            payload['score_config'] = score_config
        resp = self._request('POST', '/hadoop/quality-score/before', payload,
                             stage='BEFORE_SCORE')
        self._require_keys(resp, ('status', 'data_version', 'scores'),
                           'BEFORE_SCORE', '9')
        self._require_scores(resp['scores'], 'BEFORE_SCORE', '9')
        return resp

    def clean_dataset(self, task_id, data_version, rule_version=None):
        """数据清洗。接口规范第 10 节。"""
        payload = {'task_id': task_id, 'data_version': data_version}
        if rule_version:
            payload['rule_version'] = rule_version
        resp = self._request('POST', '/hadoop/clean', payload, stage='CLEANING')
        self._require_keys(resp, ('status', 'input_version', 'output_version',
                                  'rule_version', 'statistics'),
                           'CLEANING', '10')
        stats = resp.get('statistics') or {}
        self._require_keys(stats, ('before_count', 'after_count', 'fixed_count',
                                   'deduplicated_count', 'isolated_count'),
                           'CLEANING', '10')
        return resp

    def quality_score_after(self, task_id, data_version, score_config=None):
        """清洗后质量评分。接口规范第 11 节。"""
        payload = {'task_id': task_id, 'data_version': data_version}
        if score_config:
            payload['score_config'] = score_config
        resp = self._request('POST', '/hadoop/quality-score/after', payload,
                             stage='AFTER_SCORE')
        self._require_keys(resp, ('status', 'data_version', 'scores'),
                           'AFTER_SCORE', '11')
        self._require_scores(resp['scores'], 'AFTER_SCORE', '11')
        return resp

    # ------------------------------------------------------------------
    # 状态交接文件（只读）
    # ------------------------------------------------------------------

    def state_path(self, task_id):
        if not TASK_ID_RE.match(task_id or ''):
            raise HadoopToolError('GENERATE_REPORT', INVALID_REQUEST,
                                  'task_id 含非法字符: %r' % task_id)
        return os.path.join(STATE_DIR, task_id + '.json')

    def read_state(self, task_id):
        """
        读取成员A写入的任务状态交接文件。

        返回 dict；文件不存在时返回 None（由调用方判断是"还没执行"
        还是"执行了但没落盘"）。绝不创建或修改该文件。
        """
        p = self.state_path(task_id)
        if not os.path.exists(p):
            return None
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)

    # ------------------------------------------------------------------
    # 健康检查（联调辅助，非契约接口）
    # ------------------------------------------------------------------

    def health(self):
        """GET /health：确认成员A服务是否就绪。失败时返回错误 dict 而不抛异常。"""
        try:
            return self._request('GET', '/health', stage='PARSE_REQUEST')
        except HadoopToolError as e:
            return {'status': 'FAILED', 'error': e.to_dict()}
