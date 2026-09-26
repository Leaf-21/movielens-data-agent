# -*- coding: utf-8 -*-
"""
假 Hadoop 服务（测试夹具）

模拟成员A hadoop/src/server.py 的契约行为，供 Agent 单元测试使用：
  · 三个 POST 端点的成功响应严格按接口规范第 9-11 节；
  · 业务失败按第 15 节返回 HTTP 200 + {status:FAILED, error:{...}}；
  · 与A一样把完整中间结果【增量】写入状态交接文件
    <state_dir>/{task_id}.json。

⚠️ 本文件里的指标与得分是【测试夹具数据】，不是真实执行结果，
    仅用于验证 Agent 的组装/调度逻辑；真实数值链路依赖成员A服务。
    夹具数值刻意保持小而整（千级），与真实 ml-1m 量级区分。
"""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---- 夹具数据（测试专用，见文件头警示）----

BEFORE_METRICS = {
    'ratings_total': 1000, 'movies_total': 100, 'users_total': 60,
    'users_u_zip_bad': 5,
    'movies_m_title_nonascii': 3,
}
AFTER_METRICS = {
    'ratings_total': 999, 'movies_total': 100, 'users_total': 60,
    'users_u_zip_bad': 0,
    'movies_m_title_nonascii': 3,
}
BEFORE_SCORES = {'accurate': 99.0, 'complete': 100.0, 'unique': 100.0,
                 'up_to_date': 50.0, 'consistent': 98.0, 'overall': 94.60}
AFTER_SCORES = {'accurate': 100.0, 'complete': 100.0, 'unique': 100.0,
                'up_to_date': 50.0, 'consistent': 98.3, 'overall': 95.04}
CLEAN_STATS = {'before_count': 1160, 'after_count': 1159,
               'fixed_count': 4, 'deduplicated_count': 0, 'isolated_count': 1}


class FakeHadoop(BaseHTTPRequestHandler):
    server_options = None  # {'state': dict, 'httpd': ...}

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _failed(self, task_id, stage, code, message):
        self._json({'task_id': task_id, 'status': 'FAILED',
                    'error': {'code': code, 'message': message, 'stage': stage}})

    def _read(self):
        n = int(self.headers.get('Content-Length') or 0)
        return json.loads(self.rfile.read(n).decode('utf-8')) if n else {}

    def _save(self):
        opts = self.server_options
        p = os.path.join(opts['state_dir'], opts['task_id'] + '.json')
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(opts['state'], f, ensure_ascii=False, indent=2)

    def do_POST(self):
        opts = self.server_options
        req = self._read()
        task_id = req.get('task_id')
        opts['task_id'] = task_id
        path = self.path.rstrip('/')

        if path == '/hadoop/quality-score/before':
            if opts['fail_at'] == 'before':
                self._failed(task_id, 'BEFORE_SCORE', 'QUALITY_SCORE_ERROR',
                             '模拟：清洗前评分失败')
                return
            opts['state'].update({'_state': 'BEFORE_DONE',
                                  'before_metrics': dict(BEFORE_METRICS),
                                  'before_scores': dict(BEFORE_SCORES),
                                  'before_details': {}})
            self._save()
            self._json({'task_id': task_id, 'status': 'SUCCESS',
                        'data_version': req.get('data_version'),
                        'scores': {k: BEFORE_SCORES[k] for k in
                                   ('accurate', 'complete', 'unique',
                                    'up_to_date', 'consistent')}})
        elif path == '/hadoop/clean':
            if opts['fail_at'] == 'clean':
                self._failed(task_id, 'CLEANING', 'HADOOP_EXECUTION_ERROR',
                             '模拟：清洗作业执行失败')
                return
            opts['state'].update({'_state': 'CLEAN_DONE',
                                  'clean_statistics': dict(CLEAN_STATS)})
            self._save()
            self._json({'task_id': task_id, 'status': 'SUCCESS',
                        'input_version': 'movielens-1m-v1',
                        'output_version': 'movielens-1m-v1-clean-v1',
                        'rule_version': 'rule-v1',
                        'statistics': dict(CLEAN_STATS)})
        elif path == '/hadoop/quality-score/after':
            if opts['fail_at'] == 'after':
                self._failed(task_id, 'AFTER_SCORE', 'QUALITY_SCORE_ERROR',
                             '模拟：清洗后评分失败')
                return
            opts['state'].update({'_state': 'AFTER_DONE',
                                  'after_metrics': dict(AFTER_METRICS),
                                  'after_scores': dict(AFTER_SCORES),
                                  'after_details': {}})
            self._save()
            self._json({'task_id': task_id, 'status': 'SUCCESS',
                        'data_version': 'movielens-1m-v1-clean-v1',
                        'scores': {k: AFTER_SCORES[k] for k in
                                   ('accurate', 'complete', 'unique',
                                    'up_to_date', 'consistent')}})
        else:
            self._json({'task_id': task_id, 'status': 'FAILED',
                        'error': {'code': 'INVALID_REQUEST',
                                  'message': '未知路径'}}, status=404)
            return

    def do_GET(self):
        if self.path.split('?')[0].rstrip('/') in ('/health', ''):
            self._json({'status': 'SUCCESS', 'service': 'fake-hadoop'})
        else:
            self._json({'status': 'FAILED',
                        'error': {'code': 'INVALID_REQUEST',
                                  'message': '不支持'}}, status=404)

    def log_message(self, fmt, *args):
        pass


class FakeHadoopServer(object):
    """在临时目录上起一个假Hadoop服务；fail_at 控制首个失败环节。"""

    def __init__(self, state_dir, fail_at=None):
        self.state_dir = state_dir
        self._stopped = False
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), FakeHadoop)
        FakeHadoop.server_options = {
            'state_dir': state_dir, 'state': {}, 'task_id': None,
            'fail_at': fail_at,
        }
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)
        self.thread.start()

    @property
    def base_url(self):
        host, port = self.httpd.server_address[:2]
        return 'http://%s:%d' % (host, port)

    def stop(self):
        if self._stopped:  # 幂等：用例中可能已手动停止模拟服务宕机
            return
        self._stopped = True
        self.httpd.shutdown()
        self.httpd.server_close()
