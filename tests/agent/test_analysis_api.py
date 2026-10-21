# -*- coding: utf-8 -*-
"""
迭代二分析接口端到端单测（夹具合成数据 + FakeHadoop + 真实调度/子进程执行）。

覆盖：POST /api/analysis/{类别}/tasks 的创建即校验（同步拒绝不出僵尸任务）、
双算法对照异步完成、状态/结果/追问/health 的 task_type 贯通。
夹具数值为测试数据，不代表真实执行结果。
"""

import json
import threading
import time
import unittest
import urllib.request

import _paths  # noqa: F401
import analysis_fixture as fx

import api  # noqa: E402
from fake_hadoop import FakeHadoopServer  # noqa: E402
from hadoop_tool import HadoopTool       # noqa: E402
from scheduler import PipelineScheduler  # noqa: E402
from store import TaskStore              # noqa: E402
import tempfile                          # noqa: E402


def _post(url, payload):
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8'))


def _get(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode('utf-8'))


class TestAnalysisApi(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.ctx = fx.install()
        cls.f = cls.ctx.__enter__()
        cls.dirs = [tempfile.TemporaryDirectory() for _ in range(3)]
        state_dir, tasks_dir, results_dir = (d.name for d in cls.dirs)
        cls.srv = FakeHadoopServer(state_dir)
        cls.store = TaskStore(tasks_dir)
        cls.tool = HadoopTool(base_url=cls.srv.base_url, timeout=10)
        cls.scheduler = PipelineScheduler(cls.store, cls.tool,
                                          results_dir=results_dir)
        cls.scheduler.start()
        cls.httpd = api.make_server(cls.store, cls.tool, cls.scheduler,
                                    '127.0.0.1', 0)
        cls.t = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.t.start()
        host, port = cls.httpd.server_address[:2]
        cls.base = 'http://%s:%d' % (host, port)
        cls.results_dir = results_dir

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.scheduler.stop()
        cls.srv.stop()
        for d in cls.dirs:
            d.cleanup()
        cls.ctx.__exit__(None, None, None)

    # ---- helpers ----

    def _wait_terminal(self, task_id, timeout=180):
        deadline = time.time() + timeout
        while time.time() < deadline:
            rec = _get(self.base + '/api/tasks/' + task_id)
            if rec['status'] in ('SUCCESS', 'FAILED'):
                return rec
            time.sleep(0.5)
        self.fail('任务超时未到终态: %s' % task_id)

    # ---- 创建 + 异步执行 ----

    def test_clustering_dual_algorithm_e2e(self):
        resp = _post(self.base + '/api/analysis/clustering/tasks',
                     {'user_ids': [1, 4, 7, 8],
                      'query': '把这几个用户聚类分组并解释群体'})
        self.assertEqual(resp['status'], 'PENDING')
        self.assertEqual(resp['task_type'], 'clustering')
        self.assertEqual(resp['algorithms'], ['dbscan', 'kmeans'])
        self.assertIn('对照', resp['understanding'])
        rec = self._wait_terminal(resp['task_id'])
        self.assertEqual(rec['status'], 'SUCCESS', rec.get('message'))
        result = _get(self.base + '/api/tasks/%s/result' % resp['task_id'])
        self.assertEqual(result['task_type'], 'clustering')
        self.assertEqual(len(result['results']), 2)
        tools = [e['algorithm_tool'] for e in result['results']]
        self.assertEqual(tools, ['clustering_dbscan', 'clustering_kmeans'])
        self.assertEqual(set(result['result_versions']), set(tools))
        self.assertEqual(result['data_version'], 'movielens-1m-v2-clean-v1')
        self.assertEqual(result['profile_version'], 'profile-test')
        self.assertEqual(result['analysis_version'], 'iter2-analysis-test')
        self.assertEqual(sorted(result['requested_user_ids']), [1, 4, 7, 8])
        # 诚实语义：INSUFFICIENT/NO_TRAIN 用户不伪造归属
        for e in result['results']:
            lab = {a['user_id']: a for a in e['assignments']}
            self.assertEqual(lab[8]['status'], 'NO_TRAIN_HISTORY')
            self.assertIsNone(lab[8]['cluster_id'])
        # 执行记录贯通
        self.assertEqual(result['execution']['mode'], 'subprocess_isolated')

    def test_single_algorithm_query_and_ask(self):
        resp = _post(self.base + '/api/analysis/clustering/tasks',
                     {'query': '用 kmeans 给用户 1 聚类', 'user_ids': [1]})
        self.assertEqual(resp['algorithms'], ['kmeans'])
        rec = self._wait_terminal(resp['task_id'])
        self.assertEqual(rec['status'], 'SUCCESS', rec.get('message'))
        ask = _post(self.base + '/api/tasks/%s/ask' % resp['task_id'],
                    {'question': '用户 1 属于哪个群体？'})
        # 追问已改为大模型主路径（模板已移除）。单元测试环境禁用真实模型，
        # 因此应如实返回「不可用」，而不是拿模板凑一段看似完整的答案。
        self.assertEqual(ask['source'], 'unavailable')
        self.assertIn('未配置可用的语言模型', ask['answer'])
        ask2 = _post(self.base + '/api/tasks/%s/ask' % resp['task_id'],
                     {'question': '这些结果有什么局限？'})
        self.assertEqual(ask2['source'], 'unavailable')

    def test_task_list_exposes_task_type(self):
        resp = _post(self.base + '/api/analysis/clustering/tasks',
                     {'user_ids': [2]})
        self._wait_terminal(resp['task_id'])
        listing = _get(self.base + '/api/tasks')
        entry = next(t for t in listing['tasks']
                     if t['task_id'] == resp['task_id'])
        self.assertEqual(entry['task_type'], 'clustering')

    # ---- 同步拒绝（不产生任务）----

    def test_classification_model_not_found_sync(self):
        resp = _post(self.base + '/api/analysis/classification/tasks',
                     {'query': '预测用户 1 会不会喜欢电影 5', 'user_ids': [1]})
        self.assertEqual(resp['status'], 'FAILED')
        self.assertEqual(resp['error']['code'], 'MODEL_NOT_FOUND')
        self.assertIsNone(resp['task_id'])

    def test_dimensionality_reduction_model_not_found(self):
        resp = _post(
            self.base + '/api/analysis/dimensionality-reduction/tasks',
            {'query': '给用户 1 做降维', 'user_ids': [1]})
        self.assertEqual(resp['error']['code'], 'MODEL_NOT_FOUND')

    def test_invalid_requests_sync(self):
        n0 = len(_get(self.base + '/api/tasks')['tasks'])
        r1 = _post(self.base + '/api/analysis/clustering/tasks',
                   {'query': '聚类一下用户们'})
        self.assertEqual(r1['error']['code'], 'INVALID_REQUEST')
        r2 = _post(self.base + '/api/analysis/clustering/tasks',
                   {'user_ids': [1], 'parameters': {'k': 1}})
        self.assertEqual(r2['error']['code'], 'INVALID_PARAMETER')
        r3 = _post(self.base + '/api/analysis/clustering/tasks',
                   {'user_ids': [1], 'data_version': 'totally-bogus'})
        self.assertEqual(r3['error']['code'], 'VERSION_MISMATCH')
        r4 = _post(self.base + '/api/analysis/clustering/tasks',
                   {'user_ids': [999999]})
        self.assertEqual(r4['error']['code'], 'UNKNOWN_USER')
        # 全部同步拒绝，不产生任何新任务（无僵尸任务）
        n1 = len(_get(self.base + '/api/tasks')['tasks'])
        self.assertEqual(n1, n0)

    def test_health_exposes_analysis(self):
        h = _get(self.base + '/health')
        self.assertEqual(h['analysis']['profile_version'], 'profile-test')
        self.assertEqual(h['analysis']['registered_tools'],
                         ['clustering_dbscan', 'clustering_kmeans'])


if __name__ == '__main__':
    unittest.main()
