#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent API 服务（成员B负责的三条接口 + 追问扩展）

契约依据：docs/接口规范文档.md
  第 4/5 节   POST /api/tasks                 创建任务（异步）
  第 6 节     GET  /api/tasks/{task_id}       查询状态
  第 13 节    GET  /api/tasks/{task_id}/result 最终评估结果
  第 18 节    这三条由成员B负责
  第 20 节    接口变更须先改文档 —— 本服务新增的两个只读辅助接口
              （GET /api/tasks 列表、GET /health）与追问接口
              （POST /api/tasks/{task_id}/ask）均已在接口文档中登记。

实现：标准库 ThreadingHTTPServer，与成员A服务层同选型（零第三方依赖）。

HTTP 状态码约定与成员A一致：
  业务失败（参数不合法、任务不存在、Hadoop 出错）返回 HTTP 200 +
  {status:"FAILED", error:{...}}，调用方统一按 JSON 解析；
  协议级错误（未知路径、请求体不是 JSON）才用 4xx。

启动：
  python3 agent/src/api.py --port 8090
  环境变量 ML_HADOOP_URL 指向成员A服务（默认 http://127.0.0.1:8080）
"""

import argparse
import json
import os
import re
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)
_TOOLS_DIR = os.path.join(os.path.dirname(_SRC_DIR), 'tools')
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

import config                # noqa: E402
import models                # noqa: E402
import parser as req_parser  # noqa: E402
import explainer             # noqa: E402
from errors import (build_error_response, INVALID_REQUEST,  # noqa: E402
                    AGENT_EXECUTION_ERROR)
from hadoop_tool import HadoopTool       # noqa: E402
from store import TaskStore              # noqa: E402
from scheduler import PipelineScheduler  # noqa: E402

# task_id 允许 1-64 个字母数字及 _ . -（与 hadoop_tool 白名单一致）
_TASK_ID = r'[A-Za-z0-9_.\-]{1,64}'
RE_TASK = re.compile(r'^/api/tasks/(%s)$' % _TASK_ID)
RE_RESULT = re.compile(r'^/api/tasks/(%s)/result$' % _TASK_ID)
RE_ASK = re.compile(r'^/api/tasks/(%s)/ask$' % _TASK_ID)

MAX_PROMPT_LEN = 2000

# 由 serve() 注入
G = {}


class Handler(BaseHTTPRequestHandler):

    # ---------------- 基础 ----------------

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False, indent=2).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _fail(self, task_id, stage, code, message, detail=None, status=200):
        resp = build_error_response(task_id, stage, code, message, detail)
        self._send_json(resp, status=status)

    def _read_body(self):
        length = int(self.headers.get('Content-Length') or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode('utf-8'))
        except (ValueError, UnicodeDecodeError) as e:
            raise ValueError('请求体不是合法 JSON: %s' % e)

    # ---------------- POST ----------------

    def do_POST(self):
        path = self.path.split('?', 1)[0].rstrip('/') or self.path
        try:
            if path == '/api/tasks':
                self._create_task()
            elif RE_ASK.match(path):
                self._ask(RE_ASK.match(path).group(1))
            else:
                self._fail(None, models.PARSE_REQUEST, INVALID_REQUEST,
                           '未知接口路径: POST %s' % path,
                           '可用接口: POST /api/tasks, '
                           'POST /api/tasks/{task_id}/ask', status=404)
        except ValueError as e:  # JSON 解析类错误 -> 400 协议级
            self._fail(None, models.PARSE_REQUEST, INVALID_REQUEST, str(e),
                       status=400)
        except Exception as e:
            self._fail(None, models.PARSE_REQUEST, AGENT_EXECUTION_ERROR,
                       'Agent 服务内部错误: %s' % e,
                       traceback.format_exc()[-2000:])

    def _create_task(self):
        req = self._read_body()
        if not isinstance(req, dict):
            raise ValueError('请求体必须是 JSON 对象')

        # ---- prompt（必填，接口规范第 4 节）----
        prompt = req.get('prompt')
        if not isinstance(prompt, str) or not prompt.strip():
            self._fail(None, models.PARSE_REQUEST, INVALID_REQUEST,
                       '缺少必填字段 prompt（用户自然语言需求，非空字符串）')
            return
        if len(prompt) > MAX_PROMPT_LEN:
            self._fail(None, models.PARSE_REQUEST, INVALID_REQUEST,
                       'prompt 超过 %d 字符上限' % MAX_PROMPT_LEN)
            return

        cfg = config.load_rules()

        # ---- data_version（必填，第 16 节：未登记版本直接拒绝）----
        if 'data_version' not in req:
            self._fail(None, models.PARSE_REQUEST, INVALID_REQUEST,
                       '缺少必填字段 data_version')
            return
        dv, err = config.validate_data_version(req.get('data_version'), cfg)
        if err:
            self._fail(None, models.BEFORE_SCORE, err['code'], err['message'],
                       err.get('detail'))
            return

        # ---- rule_version（可选，"default"=登记的默认方案）----
        rv, err = config.validate_rule_version(req.get('rule_version'), cfg)
        if err:
            self._fail(None, models.CLEANING, err['code'], err['message'],
                       err.get('detail'))
            return

        # ---- score_config（可选，第 9 节结构：维度 -> bool）----
        sc = req.get('score_config')
        if sc is not None:
            if not isinstance(sc, dict) or any(
                    k not in models.DIM_ORDER or not isinstance(v, bool)
                    for k, v in sc.items()):
                self._fail(None, models.PARSE_REQUEST, INVALID_REQUEST,
                           'score_config 必须是 null 或 {维度名: bool} 对象',
                           '维度名取值: %s' % list(models.DIM_ORDER))
                return

        # ---- 解析 + 建档 + 入队 ----
        plan = req_parser.build_plan(prompt, dv, rv, sc)
        store = G['store']
        task_id = store.new_task_id()
        store.create(task_id, prompt, plan)
        G['scheduler'].submit(task_id)

        self._send_json({
            'task_id': task_id,
            'status': models.PENDING,
            'message': '任务已创建',
            # 附加字段：让用户立刻看到 Agent 理解成了什么（接口文档已登记）
            'understanding': plan['notes'],
        })

    def _ask(self, task_id):
        req = self._read_body()
        question = (req or {}).get('question') if isinstance(req, dict) else None
        if not isinstance(question, str) or not question.strip():
            self._fail(task_id, models.PARSE_REQUEST, INVALID_REQUEST,
                       '缺少必填字段 question（字符串）')
            return
        rec = G['store'].get(task_id)
        if rec is None:
            self._fail(task_id, models.PARSE_REQUEST, INVALID_REQUEST,
                       '任务不存在: %s' % task_id)
            return
        answer, source = explainer.answer(rec, question)
        self._send_json({'task_id': task_id, 'question': question.strip(),
                         'answer': answer, 'source': source})

    # ---------------- GET ----------------

    def do_GET(self):
        path = self.path.split('?', 1)[0].rstrip('/') or self.path
        try:
            if path == '/health':
                self._health()
            elif path == '/api/tasks':
                self._send_json({'status': models.SUCCESS,
                                 'tasks': G['store'].list_summary()})
            elif RE_RESULT.match(path):
                self._result(RE_RESULT.match(path).group(1))
            elif RE_TASK.match(path):
                self._status(RE_TASK.match(path).group(1))
            else:
                self._fail(None, models.PARSE_REQUEST, INVALID_REQUEST,
                           '未知接口路径: GET %s' % path,
                           '可用接口: POST /api/tasks, GET /api/tasks, '
                           'GET /api/tasks/{task_id}, '
                           'GET /api/tasks/{task_id}/result, GET /health',
                           status=404)
        except Exception as e:
            self._fail(None, models.PARSE_REQUEST, AGENT_EXECUTION_ERROR,
                       'Agent 服务内部错误: %s' % e,
                       traceback.format_exc()[-2000:])

    def _status(self, task_id):
        rec = G['store'].get(task_id)
        if rec is None:
            self._fail(task_id, models.PARSE_REQUEST, INVALID_REQUEST,
                       '任务不存在: %s' % task_id)
            return
        resp = {
            'task_id': task_id,
            'status': rec['status'],
            'stage': rec['stage'],
            'message': rec['message'],
        }
        if rec['status'] == models.FAILED and rec.get('error'):
            resp['error'] = rec['error']
        pos = G['store'].queue_position(task_id)
        if pos is not None:
            resp['queue_position'] = pos
        self._send_json(resp)

    def _result(self, task_id):
        rec = G['store'].get(task_id)
        if rec is None:
            self._fail(task_id, models.PARSE_REQUEST, INVALID_REQUEST,
                       '任务不存在: %s' % task_id)
            return
        status = rec['status']
        if status in (models.PENDING, models.RUNNING):
            # 执行中只回状态，不回任何数值（接口规范第 2.2 节）
            self._send_json({'task_id': task_id, 'status': status,
                             'stage': rec['stage'], 'message': rec['message'],
                             '_note': '任务尚未完成，结果暂不可得'})
            return
        if status == models.FAILED:
            resp = {'task_id': task_id, 'status': models.FAILED,
                    'stage': rec['stage'], 'message': rec['message'],
                    'error': rec.get('error')}
            # 失败时如实附带已完成环节的部分结果（缺失字段为 null）
            if rec.get('result'):
                resp['partial_result'] = rec['result']
            self._send_json(resp)
            return
        # SUCCESS：返回第 13 节完整结果
        self._send_json(rec['result'] or {
            'task_id': task_id, 'status': models.SUCCESS,
            '_note': '结果文件缺失（异常状态），请查看任务记录'})

    def _health(self):
        cfg = None
        try:
            cfg = config.load_rules()
        except Exception:
            pass
        self._send_json({
            'status': models.SUCCESS,
            'service': 'movielens-agent',
            'port': G.get('port'),
            'hadoop_url': G['tool'].base_url,
            'rule_version': cfg.get('rule_version') if cfg else None,
            'llm_enabled': bool(explainer.llm.enabled()),
            'scheduler': {'queue_size': G['scheduler'].q.qsize(),
                          'pending': G['store'].pending_ids()},
        })

    def log_message(self, fmt, *args):
        sys.stderr.write('[agent] %s - %s\n'
                         % (self.address_string(), fmt % args))


def make_server(store, tool, scheduler, host, port):
    G['store'] = store
    G['tool'] = tool
    G['scheduler'] = scheduler
    G['port'] = port
    httpd = ThreadingHTTPServer((host, port), Handler)
    return httpd


def serve(host, port, hadoop_url):
    cfg = config.load_rules()  # 启动即校验规则文件可用，缺位置直接报错退出
    store = TaskStore(config.TASKS_DIR)
    recovered = store.load()
    tool = HadoopTool(base_url=hadoop_url)
    scheduler = PipelineScheduler(store, tool)
    scheduler.start()
    httpd = make_server(store, tool, scheduler, host, port)

    print('=' * 62)
    print(' MovieLens Agent 服务（成员B）')
    print('   监听地址 : http://%s:%d' % (host, port))
    print('   Hadoop   : %s' % tool.base_url)
    print('   规则版本 : %s' % cfg['rule_version'])
    print('   数据版本 : %s -> %s' % (cfg['input_version'], cfg['output_version']))
    print('   T1/T2    : %s / %s（epoch %s / %s）' % (
        cfg['time']['T1'], cfg['time']['T2'],
        cfg['time']['T1_epoch'], cfg['time']['T2_epoch']))
    if recovered:
        print('   恢复提醒 : 上次运行有 %d 个未完成任务，已如实标记为中断失败' % recovered)
    print('-' * 62)
    print('   POST /api/tasks')
    print('   GET  /api/tasks')
    print('   GET  /api/tasks/{task_id}')
    print('   GET  /api/tasks/{task_id}/result')
    print('   POST /api/tasks/{task_id}/ask')
    print('   GET  /health')
    print('=' * 62)
    print(' 停止服务请按 Ctrl+C')
    sys.stdout.flush()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n[agent] 收到中断，正在停止 ...')
    finally:
        scheduler.stop()
        httpd.server_close()
    return 0


def main():
    ap = argparse.ArgumentParser(
        description='Agent API 服务（对应 docs/接口规范文档.md 第 4/6/13/18 节）')
    ap.add_argument('--host', default=config.AGENT_HOST)
    ap.add_argument('--port', type=int, default=config.AGENT_PORT)
    ap.add_argument('--hadoop-url',
        default=os.environ.get('ML_HADOOP_URL', 'http://127.0.0.1:8080'),
        help='成员A Hadoop 服务地址')
    args = ap.parse_args()
    return serve(args.host, args.port, args.hadoop_url)


if __name__ == '__main__':
    sys.exit(main())
