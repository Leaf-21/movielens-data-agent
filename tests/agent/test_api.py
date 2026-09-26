# -*- coding: utf-8 -*-
"""
Agent API 端到端单测。

组合真实组件：TaskStore + PipelineScheduler + HadoopTool + api.Handler，
后端用 fake_hadoop.FakeHadoopServer 替换成员A服务。
覆盖接口规范第 4/6/13/15/18 节的行为约定：
  · 参数校验在 HTTP 200 里回 FAILED + error；
  · 异步任务：创建即 PENDING，轮询到终态；
  · SUCCESS 结果含第 13 节字段；
  · 失败任务写明环节+原因，且部分结果缺失处是 null；
  · 追问接口走模板路径（本环境无 LLM）。
夹具数值为测试数据，不代表真实执行结果。
"""

import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

import _paths  # noqa: F401
import api
import hadoop_tool
from fake_hadoop import FakeHadoop, FakeHadoopServer
from scheduler import PipelineScheduler
from store import TaskStore
from hadoop_tool import HadoopTool


class TestAgentApi(unittest.TestCase):

    fail_at = None  # 子类/用例可覆盖

    def setUp(self):
        self.dirs = [tempfile.TemporaryDirectory() for _ in range(3)]
        state_dir, tasks_dir, results_dir = (d.name for d in self.dirs)
        self.srv = FakeHadoopServer(state_dir, fail_at=self.fail_at)
        # 用例可在 setUp 之后改这个 dict 来注入"某环节失败"
        self.opts = FakeHadoop.server_options
        self._orig_state_dir = hadoop_tool.STATE_DIR
        hadoop_tool.STATE_DIR = state_dir

        self.store = TaskStore(tasks_dir)
        self.tool = HadoopTool(base_url=self.srv.base_url, timeout=10)
        self.scheduler = PipelineScheduler(self.store, self.tool,
                                           results_dir=results_dir)
        self.scheduler.start()
        self.httpd = api.make_server(self.store, self.tool, self.scheduler,
                                     '127.0.0.1', 0)
        self.t = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.t.start()
        host, port = self.httpd.server_address[:2]
        self.base = 'http://%s:%d' % (host, port)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.scheduler.stop()
        hadoop_tool.STATE_DIR = self._orig_state_dir
        self.srv.stop()
        for d in self.dirs:
            d.cleanup()

    # ---------------- 客户端辅助 ----------------

    def _req(self, method, path, body=None):
        data = json.dumps(body, ensure_ascii=False).encode('utf-8') if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode('utf-8'))

    def post_json(self, path, body):
        return self._req('POST', path, body)

    def get_json(self, path):
        return self._req('GET', path)

    def _create(self, prompt='请使用默认规则清洗 MovieLens 1M，评估清洗前后的五个数据质量维度。',
                **kw):
        body = {'prompt': prompt, 'data_version': 'movielens-1m-v1'}
        body.update(kw)
        status, resp = self.post_json('/api/tasks', body)
        self.assertEqual(status, 200)
        return resp

    def _wait_terminal(self, task_id, timeout=20):
        deadline = time.time() + timeout
        while time.time() < deadline:
            _, rec = self.get_json('/api/tasks/%s' % task_id)
            if rec['status'] in ('SUCCESS', 'FAILED'):
                return rec
            time.sleep(0.03)
        self.fail('任务 %s 超时未到终态（最后状态 %s）' % (task_id, rec))

    # ---------------- 参数校验（第 4/15 节）----------------

    def test_missing_prompt(self):
        st, resp = self.post_json('/api/tasks', {'data_version': 'movielens-1m-v1'})
        self.assertEqual(st, 200)  # 业务失败按约定走 HTTP 200
        self.assertEqual(resp['status'], 'FAILED')
        self.assertEqual(resp['error']['code'], 'INVALID_REQUEST')
        self.assertIn('prompt', resp['error']['message'])

    def test_missing_data_version(self):
        st, resp = self.post_json('/api/tasks', {'prompt': '清洗'})
        self.assertEqual(resp['error']['code'], 'INVALID_REQUEST')

    def test_unregistered_data_version(self):
        resp = self._create(data_version='movielens-99m-v9')
        self.assertEqual(resp['status'], 'FAILED')
        self.assertEqual(resp['error']['code'], 'INVALID_DATA_VERSION')

    def test_unregistered_rule_version(self):
        resp = self._create(rule_version='rule-v99')
        self.assertEqual(resp['error']['code'], 'INVALID_RULE_VERSION')

    def test_bad_score_config(self):
        resp = self._create(score_config={'accurate': 'yes'})
        self.assertEqual(resp['error']['code'], 'INVALID_REQUEST')

    def test_invalid_json_body_is_protocol_error(self):
        req = urllib.request.Request(self.base + '/api/tasks',
                                     data=b'{not json', method='POST',
                                     headers={'Content-Type': 'application/json'})
        try:
            urllib.request.urlopen(req, timeout=10)
            self.fail('应返回 4xx')
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)

    # ---------------- 成功链路（第 5/6/13 节）----------------

    def test_full_pipeline_success(self):
        created = self._create()
        self.assertEqual(created['status'], 'PENDING')
        self.assertRegex(created['task_id'], r'^task_\d{8}_\d{4}$')
        self.assertIn('understanding', created)

        rec = self._wait_terminal(created['task_id'])
        self.assertEqual(rec['status'], 'SUCCESS', rec.get('message'))
        self.assertEqual(rec['stage'], 'COMPLETED')
        self.assertIn('94.6000', rec['message'])  # 真实夹具分数出现在完成消息中

        st, result = self.get_json('/api/tasks/%s/result' % created['task_id'])
        self.assertEqual(st, 200)
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertEqual(result['before_score']['accurate'], 99.0)
        self.assertEqual(result['after_score']['accurate'], 100.0)
        self.assertEqual(result['score_change']['accurate'], 1.0)
        self.assertEqual(result['statistics']['isolated_count'], 1)
        self.assertEqual(result['T1_epoch'], 974862386)  # epoch 精确透传
        self.assertTrue(result['problems'])
        self.assertEqual(result['_assembled_by'], 'agent/http-pipeline(成员B)')
        # 报告四段（第 14 节）
        for k in ('method', 'improvements', 'unresolved', 'limitations'):
            self.assertIn(k, result['report'])

    def test_evaluate_only_leaves_after_null(self):
        created = self._create(prompt='只评估数据质量，不清洗')
        rec = self._wait_terminal(created['task_id'])
        self.assertEqual(rec['status'], 'SUCCESS')
        _, result = self.get_json('/api/tasks/%s/result' % created['task_id'])
        self.assertIsNone(result['after_score']['overall'])
        self.assertIsNone(result['statistics']['fixed_count'])
        self.assertEqual(result['data_version'], 'movielens-1m-v1')

    # ---------------- 失败链路（第 6/15/23 节）----------------

    def _run_failing(self):
        created = self._create()
        rec = self._wait_terminal(created['task_id'])
        self.assertEqual(rec['status'], 'FAILED')
        return rec

    def test_failure_reports_stage_and_cause(self):
        self.opts['fail_at'] = 'clean'
        rec = self._run_failing()
        err = rec['error']
        self.assertEqual(err['stage'], 'CLEANING')
        self.assertEqual(err['code'], 'HADOOP_EXECUTION_ERROR')
        self.assertIn('任务失败（环节 CLEANING）', rec['message'])
        self.assertIn('请检查 Hadoop 服务', rec['message'])  # 附指引

        st, resp = self.get_json('/api/tasks/%s/result' % rec['task_id'])
        self.assertEqual(resp['status'], 'FAILED')
        partial = resp['partial_result']  # 已完成环节结果如实保留
        self.assertEqual(partial['before_score']['accurate'], 99.0)
        self.assertIsNone(partial['after_score']['accurate'])  # 未执行=null 而非 0
        self.assertIsNone(partial['statistics']['fixed_count'])

    def test_failure_at_before_has_no_partial(self):
        self.opts['fail_at'] = 'before'
        rec = self._run_failing()
        self.assertEqual(rec['error']['stage'], 'BEFORE_SCORE')
        _, resp = self.get_json('/api/tasks/%s/result' % rec['task_id'])
        self.assertNotIn('partial_result', resp)  # 没有任何真实结果可给

    def test_hadoop_down_fails_cleanly(self):
        # 后端服务不可用 -> 任务 FAILED 且提示连接问题，不产生假结果
        self.srv.stop()
        created = self._create()
        rec = self._wait_terminal(created['task_id'])
        self.assertEqual(rec['status'], 'FAILED')
        self.assertIn('无法连接 Hadoop 服务', rec['error']['message'])

    # ---------------- 查询与追问 ----------------

    def test_unknown_task(self):
        st, resp = self.get_json('/api/tasks/task_19700101_9999')
        self.assertEqual(st, 200)
        self.assertEqual(resp['status'], 'FAILED')
        self.assertIn('任务不存在', resp['error']['message'])

    def test_list_and_health(self):
        created = self._create()
        _, lst = self.get_json('/api/tasks')
        ids = [t['task_id'] for t in lst['tasks']]
        self.assertIn(created['task_id'], ids)
        _, h = self.get_json('/health')
        self.assertEqual(h['service'], 'movielens-agent')
        self.assertFalse(h['llm_enabled'])  # 本环境无 API Key，模板路径

    def test_ask_endpoint(self):
        created = self._create()
        self._wait_terminal(created['task_id'])
        st, resp = self.post_json('/api/tasks/%s/ask' % created['task_id'],
                                  {'question': '被隔离的记录算修复了吗'})
        self.assertEqual(st, 200)
        self.assertEqual(resp['source'], 'template')
        self.assertIn('未被修正', resp['answer'])

    def test_ask_requires_question(self):
        created = self._create()
        st, resp = self.post_json('/api/tasks/%s/ask' % created['task_id'], {})
        self.assertEqual(resp['status'], 'FAILED')
        self.assertIn('question', resp['error']['message'])

    def test_result_before_completion(self):
        # 直接塞一个 PENDING 记录（不过调度），result 接口只回状态不回数值
        tid = self.store.new_task_id()
        self.store.create(tid, 'p', {'do_clean': True, 'data_version': 'movielens-1m-v1',
                                     'rule_version': 'rule-v1', 'notes': []})
        _, resp = self.get_json('/api/tasks/%s/result' % tid)
        self.assertEqual(resp['status'], 'PENDING')
        self.assertNotIn('before_score', resp)
        self.assertIn('_note', resp)

    def test_unknown_path_404(self):
        st, resp = self.get_json('/api/nonexistent')
        self.assertEqual(st, 404)


if __name__ == '__main__':
    unittest.main()
