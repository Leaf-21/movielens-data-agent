# -*- coding: utf-8 -*-
"""
端到端一致性测试（成员C 主导）

验证"结果一致性测试"（分工文档第六.5节）：
    Hadoop 实际结果
          ↓
    Agent 返回结果
          ↓
    前端展示结果
三个环节的数据是否一致。

实现方式：
  - 复用成员B的测试夹具 fake_hadoop（模拟成员A服务），
    上真 Agent 服务（成员B）与真前端服务（成员C）。
  - 前端服务只做静态托管 + 反向代理，因此"前端拿到的数据"
    等于"Agent 返回的数据"；本测试通过前端代理出口采样，
    再逐字段与 Agent 直连结果、与 fake Hadoop 夹具侧写证比对。

运行：
  python tests/frontend/test_e2e_consistency.py
零依赖：仅标准库 unittest。
"""

import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.request

# ---- 复用成员B的 Agent 源码与夹具 ----
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
for p in (os.path.join(_REPO, 'agent', 'src'),
          os.path.join(_REPO, 'agent', 'tools'),
          os.path.join(_REPO, 'tests', 'agent'),
          os.path.join(_REPO, 'frontend', 'src')):
    if p not in sys.path:
        sys.path.insert(0, p)

import api                      # noqa: E402  agent/src
import serve as frontend_serve  # noqa: E402  frontend/src
import hadoop_tool              # noqa: E402
from fake_hadoop import (FakeHadoop, FakeHadoopServer, BEFORE_SCORES,  # noqa: E402
                         AFTER_SCORES, CLEAN_STATS)
from scheduler import PipelineScheduler  # noqa: E402
from store import TaskStore              # noqa: E402
from hadoop_tool import HadoopTool       # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402

DIMS = ('accurate', 'complete', 'unique', 'up_to_date', 'consistent')


def _get_json(url):
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode('utf-8'))


def _post_json(url, body):
    data = json.dumps(body, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST',
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode('utf-8'))


class TestE2EConsistency(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.dirs = [tempfile.TemporaryDirectory() for _ in range(3)]
        state_dir, tasks_dir, results_dir = (d.name for d in cls.dirs)

        # ---- 1. Hadoop 层（夹具模拟成员A服务）----
        cls.hadoop = FakeHadoopServer(state_dir)
        cls._orig_state_dir = hadoop_tool.STATE_DIR
        hadoop_tool.STATE_DIR = state_dir

        # ---- 2. Agent 层（成员B真实服务）----
        cls.store = TaskStore(tasks_dir)
        cls.tool = HadoopTool(base_url=cls.hadoop.base_url, timeout=10)
        cls.scheduler = PipelineScheduler(cls.store, cls.tool,
                                          results_dir=results_dir)
        cls.scheduler.start()
        cls.agent_httpd = api.make_server(cls.store, cls.tool, cls.scheduler,
                                          '127.0.0.1', 0)
        cls.agent_port = cls.agent_httpd.server_address[1]
        cls.agent_base = 'http://127.0.0.1:%d' % cls.agent_port
        threading.Thread(target=cls.agent_httpd.serve_forever,
                         daemon=True).start()

        # ---- 3. 前端层（成员C真实服务：静态 + 反代 Agent）----
        frontend_serve.G['agent_url'] = cls.agent_base
        cls.front_httpd = ThreadingHTTPServer(('127.0.0.1', 0),
                                              frontend_serve.Handler)
        cls.front_port = cls.front_httpd.server_address[1]
        cls.front_base = 'http://127.0.0.1:%d' % cls.front_port
        threading.Thread(target=cls.front_httpd.serve_forever,
                         daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.front_httpd.shutdown(); cls.front_httpd.server_close()
        cls.agent_httpd.shutdown(); cls.agent_httpd.server_close()
        cls.scheduler.stop()
        hadoop_tool.STATE_DIR = cls._orig_state_dir
        cls.hadoop.stop()
        for d in cls.dirs:
            d.cleanup()

    # ---------------- 辅助 ----------------
    def _run_task(self, prompt='请使用默认规则清洗 MovieLens 1M，评估五个维度。'):
        # FakeHadoop 的 server_options['state'] 是进程级共享 dict，且 fake 用
        # update() 增量写；类级 setUpClass 只起一个 FakeHadoop，多任务之间会
        # 残留上一任务的 after_* 键。成员B的用例靠"每例重开 FakeHadoop"规避，
        # 此处主动清零，保证每个任务看到干净的状态（否则"只评估"会误见 after）。
        FakeHadoop.server_options['state'] = {}
        created = _post_json(self.agent_base + '/api/tasks',
                             {'prompt': prompt, 'data_version': 'movielens-1m-v2'})
        self.assertEqual(created['status'], 'PENDING')
        tid = created['task_id']
        deadline = time.time() + 20
        while time.time() < deadline:
            st = _get_json(self.agent_base + '/api/tasks/' + tid)
            if st['status'] in ('SUCCESS', 'FAILED'):
                return tid, st
            time.sleep(0.03)
        self.fail('任务未在时限内完成')

    # ---------------- 用例 ----------------

    def test_frontend_static_assets_served(self):
        """前端服务能正确托管页面与三类静态资源。"""
        for path, must_contain in (
                ('/', '<title>MovieLens 数据治理 Agent</title>'),
                ('/style.css', '--accent'),
                ('/js/api.js', 'AgentApi'),
                ('/js/render.js', 'const Render'),
                ('/js/app.js', 'function submit')):
            with urllib.request.urlopen(self.front_base + path, timeout=10) as r:
                body = r.read().decode('utf-8')
                self.assertEqual(r.status, 200, path)
                self.assertIn(must_contain, body, '资源 %s 内容异常' % path)

    def test_frontend_proxy_forwards_health(self):
        """前端 /health 反代到 Agent，证明三层连通。"""
        h = _get_json(self.front_base + '/health')
        self.assertEqual(h['service'], 'movielens-agent')

    def test_three_layer_values_identical(self):
        """核心：Hadoop → Agent → 前端 三层数值完全一致。"""
        tid, _ = self._run_task()

        # 前端出口（经反代）拿到的结果
        front_result = _get_json(self.front_base + '/api/tasks/%s/result' % tid)
        # Agent 直连拿到的结果
        agent_result = _get_json(self.agent_base + '/api/tasks/%s/result' % tid)

        # 1) 前端与 Agent 逐字节一致（前端不得改写数据）
        self.assertEqual(front_result, agent_result,
                         '前端代理结果与 Agent 返回不一致')

        # 2) Agent 结果与 Hadoop 夹具（=Hadoop 实际输出）一致
        #    before_score
        for d in DIMS:
            self.assertAlmostEqual(front_result['before_score'][d],
                                   BEFORE_SCORES[d], places=4,
                                   msg='before.%s 与 Hadoop 层不一致' % d)
            self.assertAlmostEqual(front_result['after_score'][d],
                                   AFTER_SCORES[d], places=4,
                                   msg='after.%s 与 Hadoop 层不一致' % d)

        #    statistics（数据量变化）
        stats = front_result['statistics']
        for key in ('before_count', 'after_count', 'fixed_count',
                    'deduplicated_count', 'isolated_count'):
            self.assertEqual(stats[key], CLEAN_STATS[key],
                             'statistics.%s 与 Hadoop 层不一致' % key)

        #    score_change = after - before（前端若自算也必须一致）
        for d in DIMS:
            expected = round(AFTER_SCORES[d] - BEFORE_SCORES[d], 4)
            self.assertAlmostEqual(front_result['score_change'][d], expected,
                                   places=4, msg='score_change.%s 计算不一致' % d)

    def test_frontend_sees_null_not_zero_for_evaluate_only(self):
        """只评估不清洗：after 必须为 null，前端应渲染占位符而非 0。"""
        tid, st = self._run_task(prompt='只评估原始数据质量，不清洗')
        self.assertEqual(st['status'], 'SUCCESS')
        r = _get_json(self.front_base + '/api/tasks/%s/result' % tid)
        self.assertIsNone(r['after_score'].get('overall'))
        self.assertIsNone(r['statistics'].get('fixed_count'))

    def test_frontend_proxy_reports_backend_down(self):
        """异常测试：Agent 不可用时前端不应崩溃，应返回可解析的错误 JSON。"""
        # 临时把前端反代指向一个关闭的端口
        old = frontend_serve.G['agent_url']
        frontend_serve.G['agent_url'] = 'http://127.0.0.1:1'  # 必然拒绝
        try:
            h = _get_json(self.front_base + '/health')
            self.assertEqual(h['status'], 'FAILED')
            self.assertEqual(h['error']['code'], 'PROXY_ERROR')
        finally:
            frontend_serve.G['agent_url'] = old

    def test_frontend_proxy_forwards_task_errors(self):
        """异常测试：非法 data_version 的错误经前端透传，前端可展示。"""
        resp = _post_json(self.front_base + '/api/tasks',
                          {'prompt': '清洗', 'data_version': 'movielens-999m'})
        self.assertEqual(resp['status'], 'FAILED')
        self.assertEqual(resp['error']['code'], 'INVALID_DATA_VERSION')

    def test_frontend_ask_endpoint_roundtrip(self):
        """追问经前端反代往返正常。"""
        tid, _ = self._run_task()
        resp = _post_json(self.front_base + '/api/tasks/%s/ask' % tid,
                          {'question': '被隔离的记录算修复了吗'})
        self.assertEqual(resp['source'], 'template')
        self.assertIn('answer', resp)
        self.assertTrue(resp['answer'])

    def test_no_numbers_before_completion(self):
        """任务未完成时前端出口不得返回任何数值（接口规范第 2.2 节）。"""
        created = _post_json(self.front_base + '/api/tasks',
                             {'prompt': '清洗', 'data_version': 'movielens-1m-v2'})
        tid = created['task_id']
        # 立即查询（大概率仍在跑）
        r = _get_json(self.front_base + '/api/tasks/%s/result' % tid)
        if r['status'] in ('PENDING', 'RUNNING'):
            self.assertNotIn('before_score', r)
            self.assertIn('_note', r)


if __name__ == '__main__':
    unittest.main(verbosity=2)
