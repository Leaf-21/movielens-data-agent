#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hadoop 服务层（HTTP）

职责：把 driver 的三个阶段暴露为 HTTP 接口。

契约依据：docs/接口规范文档.md
  第 2.3 节  统一使用 JSON / UTF-8 / REST API / HTTP
  第 9 节    POST /hadoop/quality-score/before
  第 10 节   POST /hadoop/clean
  第 11 节   POST /hadoop/quality-score/after
  第 15 节   错误统一返回 {task_id, status:FAILED, error:{code,message}}
  第 18 节   成员A 负责这三条路由

为什么用标准库而非 Flask/FastAPI
--------------------------------
本项目接口只有 3 个 POST 端点、同步执行、单用户访问，性能不是瓶颈。
用标准库 http.server 带来两个实际好处：
  1. 零第三方依赖 —— 成员B、成员C 拉下代码即可运行，不必先 pip install
  2. 减少联调故障点 —— 不引入版本冲突、虚拟环境差异等问题
若后续需要并发或更复杂路由，可平滑替换为 Flask，driver 层无需改动。

启动方式
--------
    python3 hadoop/src/server.py --port 8080
    # 默认监听 127.0.0.1:8080

调用示例
--------
    curl -X POST http://127.0.0.1:8080/hadoop/quality-score/before \
         -H 'Content-Type: application/json' \
         -d '{"task_id":"task_001","data_version":"movielens-1m-v1"}'
"""

import argparse
import json
import os
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# --- 路径（与 driver 保持一致）---
SRC_DIR = os.path.dirname(os.path.abspath(__file__))
HADOOP_DIR = os.path.dirname(SRC_DIR)
REPO_DIR = os.path.dirname(HADOOP_DIR)
COMMON_DIR = os.path.join(SRC_DIR, 'common')
PIPELINE_DIR = os.path.join(SRC_DIR, 'pipeline')

sys.path.insert(0, COMMON_DIR)
sys.path.insert(0, PIPELINE_DIR)
sys.path.insert(0, SRC_DIR)

import ml_common as ml
import errors as errors_mod
from errors import StageError
import driver as driver_mod


# ---------------------------------------------------------------------------
# 路由表（路径 -> (阶段名, 处理函数)）
# ---------------------------------------------------------------------------
ROUTES = {
    '/hadoop/quality-score/before': ('before', driver_mod.stage_before),
    '/hadoop/clean':                ('clean',  driver_mod.stage_clean),
    '/hadoop/quality-score/after':  ('after',  driver_mod.stage_after),
}


class Options(object):
    """
    把 HTTP 请求转换为 driver 阶段函数可接受的参数对象。

    driver 的三个阶段原本接受 argparse.Namespace，这里构造一个等价对象，
    使同一套逻辑既能被命令行调用，也能被 HTTP 调用，避免重复实现。
    """

    def __init__(self, mode, work_dir, data_dir, quiet=True):
        self.mode = mode
        self.work_dir = work_dir
        self.data_dir = data_dir
        self.quiet = quiet
        self.out = None
        self.stage = None


class Handler(BaseHTTPRequestHandler):
    # 由 serve() 注入
    server_options = None

    # ------------------------------------------------------------------
    # 基础工具
    # ------------------------------------------------------------------

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False, indent=2).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error_response(self, task_id, stage, code, message, detail=None, status=200):
        """
        错误响应统一走这里。

        注意 HTTP 状态码的取舍：
          接口规范第 15 节规定错误以 {status:"FAILED", error:{...}} 表达，
          而不是靠 HTTP 状态码。为了让 Agent 能统一按 JSON 解析，
          业务失败也返回 200，由 status 字段区分成功/失败。
          真正的协议级错误（路径不存在、JSON 非法）才用 4xx。
        """
        resp = errors_mod.build_error_response(task_id, stage, code, message, detail)
        self._send_json(resp, status=status)

    def _read_body(self):
        """读取并解析请求体 JSON。"""
        length = int(self.headers.get('Content-Length') or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode('utf-8'))
        except (ValueError, UnicodeDecodeError) as e:
            raise StageError(
                stage='PARSE_REQUEST', code=errors_mod.INVALID_REQUEST,
                message='请求体不是合法的 JSON',
                detail=str(e),
            )

    # ------------------------------------------------------------------
    # HTTP 方法
    # ------------------------------------------------------------------

    def do_POST(self):
        path = self.path.split('?', 1)[0].rstrip('/')
        if path not in ROUTES:
            self._send_error_response(
                task_id=None, stage='PARSE_REQUEST',
                code=errors_mod.INVALID_REQUEST,
                message='未知接口路径: %s' % path,
                detail='可用接口: %s' % sorted(ROUTES.keys()),
                status=404,
            )
            return

        stage_name, stage_func = ROUTES[path]

        # --- 解析请求体 ---
        try:
            req = self._read_body()
        except StageError as e:
            self._send_error_response(None, e.stage, e.code, e.message, e.detail, status=400)
            return

        task_id = req.get('task_id')
        if not task_id:
            # 接口规范第 4 节：task_id 由 Agent 生成并传入
            self._send_error_response(
                None, 'PARSE_REQUEST', errors_mod.INVALID_REQUEST,
                '缺少必填字段 task_id',
                '接口规范第 4 节规定 Agent 生成 task_id 后传入。',
                status=400,
            )
            return

        # --- 数据版本校验（接口规范第 16 节）---
        cfg = ml.load_rules()
        dv = req.get('data_version')
        if dv is not None:
            allowed = {cfg['input_version'], cfg['output_version']}
            if dv not in allowed:
                self._send_error_response(
                    task_id, stage_name.upper(), errors_mod.INVALID_DATA_VERSION,
                    '数据版本不被识别: %s' % dv,
                    '已知版本: %s' % sorted(allowed),
                )
                return

        # --- 规则版本校验 ---
        rv = req.get('rule_version')
        if rv is not None and rv not in (cfg['rule_version'], 'default', None):
            self._send_error_response(
                task_id, stage_name.upper(), errors_mod.INVALID_RULE_VERSION,
                '清洗规则版本不被识别: %s' % rv,
                '已知版本: %s' % cfg['rule_version'],
            )
            return

        # --- 执行阶段 ---
        opts = Options(
            mode=self.server_options['mode'],
            work_dir=self.server_options['work_dir'],
            data_dir=self.server_options['data_dir'],
            quiet=True,
        )
        if stage_name == 'after':
            opts.stage = 'after'

        try:
            result = stage_func(opts, task_id)
        except StageError as e:
            self._send_error_response(task_id, e.stage, e.code, e.message, e.detail)
            return
        except SystemExit as e:
            self._send_error_response(
                task_id, stage_name.upper(), errors_mod.INTERNAL_ERROR,
                str(e.code) if e.code else '未知错误')
            return
        except Exception as e:
            # 未预期的异常也要返回结构化错误，便于 Agent 处理与排查
            self._send_error_response(
                task_id, stage_name.upper(), errors_mod.INTERNAL_ERROR,
                '服务内部错误',
                traceback.format_exc()[-2000:])
            return

        self._send_json(result)

    def do_GET(self):
        """提供健康检查，便于联调时确认服务是否就绪。"""
        path = self.path.split('?', 1)[0].rstrip('/')
        if path in ('/health', '/healthz', ''):
            self._send_json({
                'status': 'SUCCESS',
                'service': 'movielens-hadoop-service',
                'routes': sorted(ROUTES.keys()),
                'mode': self.server_options['mode'],
                'data_dir': self.server_options['data_dir'],
            })
            return
        self._send_error_response(
            None, 'PARSE_REQUEST', errors_mod.INVALID_REQUEST,
            '不支持 GET %s' % path,
            '本服务仅提供 POST 接口，以及 GET /health 健康检查。',
            status=404,
        )

    def log_message(self, fmt, *args):
        """精简访问日志，避免刷屏。"""
        sys.stderr.write('[server] %s - %s\n' % (self.address_string(), fmt % args))


def serve(host, port, mode, data_dir, work_dir):
    ml.init_rules()
    cfg = ml.load_rules()

    Handler.server_options = {
        'mode': mode,
        'data_dir': data_dir,
        'work_dir': work_dir,
    }

    httpd = ThreadingHTTPServer((host, port), Handler)

    print('=' * 62)
    print(' MovieLens Hadoop 服务')
    print('   监听地址 : http://%s:%d' % (host, port))
    print('   运行模式 : %s' % mode)
    print('   数据目录 : %s' % data_dir)
    print('   规则版本 : %s' % cfg['rule_version'])
    print('   数据版本 : %s -> %s' % (cfg['input_version'], cfg['output_version']))
    print('-' * 62)
    for p in sorted(ROUTES):
        print('   POST %s' % p)
    print('   GET  /health')
    print('=' * 62)
    print(' 停止服务请按 Ctrl+C')
    sys.stdout.flush()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n[server] 收到中断，正在停止 ...')
    finally:
        httpd.server_close()
    return 0


def main():
    ap = argparse.ArgumentParser(
        description='Hadoop 服务层（对应 docs/接口规范文档.md 第 9-11 节）')
    ap.add_argument('--host', default='127.0.0.1', help='监听地址，默认 127.0.0.1')
    ap.add_argument('--port', type=int, default=8080, help='监听端口，默认 8080')
    ap.add_argument('--mode', choices=['local', 'hadoop'], default='hadoop',
                    help='local=本机文件模拟（调试）；hadoop=提交 Hadoop 作业（默认）')
    ap.add_argument('--data-dir', default=os.path.expanduser('~/data/ml-1m'))
    ap.add_argument('--work-dir', default='/tmp/mlqc-server')
    args = ap.parse_args()

    return serve(args.host, args.port, args.mode, args.data_dir, args.work_dir)


if __name__ == '__main__':
    sys.exit(main())
