# -*- coding: utf-8 -*-
"""
分析任务执行器单测：子进程协议（成功/语义失败不重试/崩溃重试/违约拒收）
与任务级装配（SUCCESS 字段、失败保留已完成算法的部分结果）。

协议类用例用临时脚本冒充工具（不经注册表），真实算法用例走夹具数据。
"""

import json
import os
import sys
import tempfile
import unittest

import _paths  # noqa: F401
import analysis_fixture as fx  # noqa: F401  (clustering 路径引导)

import analysis_runner           # noqa: E402
import config                    # noqa: E402
import models                    # noqa: E402
import registry                  # noqa: E402
from common import AnalysisError # noqa: E402
from store import TaskStore      # noqa: E402

MIN_ENV = {
    'algorithm': 'fake', 'algorithm_tool': 'clustering_fake',
    'model_version': 'mdl-test', 'result_version': 'res-test',
    'parameters': {}, 'data_version': 'd', 'profile_version': 'p',
    'T1': '2000-11-22', 'T2': '2000-12-10', 'code_version': 'x',
    'created_at': '2026-01-01T00:00:00Z', 'metrics': {'n_fit_users': 1},
    'assignments': [], 'cluster_summaries': [], 'limitations': [],
}

_SCRIPTS = {
    'ok': """
import argparse, json
p = argparse.ArgumentParser(); p.add_argument('--request'); p.add_argument('--output')
a = p.parse_args()
json.dump(%s, open(a.output, 'w'))
print(json.dumps({'status': 'SUCCESS'}))
""",
    'semantic_fail': """
import json, sys
print(json.dumps({'status': 'FAILED', 'error': {'code': 'UNKNOWN_USER',
      'message': '测试语义失败', 'details': {'x': 1}}}))
sys.exit(2)
""",
    'flaky': """
import argparse, json, os, sys
p = argparse.ArgumentParser(); p.add_argument('--request'); p.add_argument('--output')
a = p.parse_args()
marker = a.output + '.marker'
if not os.path.exists(marker):
    open(marker, 'w').write('1'); sys.exit(3)
json.dump(%s, open(a.output, 'w'))
""",
    'no_output': """
import sys
sys.exit(0)
""",
    'broken_env': """
import argparse, json
p = argparse.ArgumentParser(); p.add_argument('--request'); p.add_argument('--output')
a = p.parse_args()
bad = json.loads(%r); bad.pop('metrics')
json.dump(bad, open(a.output, 'w'))
""",
}


class TestSubprocessProtocol(unittest.TestCase):

    def test_required_envelope_keys_follow_task_type(self):
        self.assertIn('coordinates',
                      analysis_runner.required_env_keys('dimensionality_reduction'))
        self.assertIn('information_retention',
                      analysis_runner.required_env_keys('dimensionality_reduction'))
        self.assertNotIn('assignments',
                         analysis_runner.required_env_keys('dimensionality_reduction'))
        self.assertIn('assignments', analysis_runner.required_env_keys('clustering'))
        self.assertIn('results', analysis_runner.required_env_keys('classification'))

    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self._orig_mf = registry.module_file

    def tearDown(self):
        registry.module_file = self._orig_mf
        self.work.cleanup()

    def _script(self, name):
        tpl = _SCRIPTS[name]
        body = (tpl % json.dumps(MIN_ENV)) if ('%s' in tpl or '%r' in tpl) \
            else tpl
        fp = os.path.join(self.work.name, '%s_tool.py' % name)
        with open(fp, 'w', encoding='utf-8') as f:
            f.write(body)
        registry.module_file = lambda entry: fp
        return fp

    def _run(self, name, algo='fake'):
        log = []
        entry = {'timeout_s': 60}
        payload = {'user_ids': [1], 'parameters': {}}
        env = analysis_runner._run_tool_subprocess(
            entry, algo, 'test_%s' % name, payload, log)
        return env, log

    def test_success_attempt_1(self):
        self._script('ok')
        env, log = self._run('ok')
        self.assertEqual(env['_execution']['attempt'], 1)
        self.assertEqual(env['algorithm_tool'], 'clustering_fake')
        self.assertIn('第1次尝试成功', log[0])

    def test_semantic_failure_no_retry(self):
        self._script('semantic_fail')
        with self.assertRaises(AnalysisError) as cm:
            self._run('semantic_fail')
        self.assertEqual(cm.exception.code, 'UNKNOWN_USER')
        self.assertEqual(cm.exception.details, {'x': 1})

    def test_crash_then_retry_success(self):
        fp = self._script('flaky')
        # 重置脚本内部的状态标记，保证本用例每次从"第一次尝试必失败"开始
        marker = os.path.join(analysis_runner.RUNTIME_ANALYSIS_DIR,
                              'test_flaky', 'result-fake.json.marker')
        if os.path.exists(marker):
            os.remove(marker)
        env, log = self._run('flaky')
        self.assertEqual(env['_execution']['attempt'], 2)
        self.assertTrue(any('第2次尝试成功' in x for x in log))

    def test_persistent_failure_algorithm_error(self):
        self._script('no_output')
        with self.assertRaises(AnalysisError) as cm:
            self._run('no_output')
        self.assertEqual(cm.exception.code, 'ALGORITHM_ERROR')
        self.assertIn('已重试', cm.exception.message)

    def test_missing_keys_rejected_as_contract_violation(self):
        self._script('broken_env')
        with self.assertRaises(AnalysisError) as cm:
            self._run('broken_env')
        self.assertEqual(cm.exception.code, 'ALGORITHM_ERROR')
        self.assertIn('工具违约', cm.exception.message)


class TestRunTask(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.ctx = fx.install()
        cls.f = cls.ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    def _store(self, plan):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        store = TaskStore(d.name)
        tid = 'task_runtest'
        store.create(tid, '测试分析任务', plan, task_type=plan['task_type'])
        return store, tid, d.name

    def _plan(self, algorithms):
        return {'task_type': 'clustering', 'algorithms': algorithms,
                'user_ids': [1, 4, 7, 8], 'parameters_by_algorithm':
                {a: {} for a in algorithms},
                'data_version': 'movielens-1m-v2-clean-v1',
                'profile_version': 'profile-test', 'notes': '测试'}

    def test_success_assembly(self):
        store, tid, results_dir = self._store(self._plan(['kmeans']))
        analysis_runner.run_task(store, tid, results_dir)
        rec = store.get(tid)
        self.assertEqual(rec['status'], models.SUCCESS)
        r = rec['result']
        self.assertEqual(r['task_type'], 'clustering')
        self.assertEqual(len(r['results']), 1)
        self.assertEqual(r['results'][0]['algorithm_tool'],
                         'clustering_kmeans')
        self.assertEqual(r['result_versions']['clustering_kmeans'],
                         r['results'][0]['result_version'])
        self.assertEqual(r['execution']['mode'], 'subprocess_isolated')
        self.assertEqual(r['profile_version'], 'profile-test')
        self.assertIsNotNone(r['T1_epoch'])
        # 结果文件同内容落盘
        fp = os.path.join(results_dir, tid + '.json')
        with open(fp, encoding='utf-8') as f:
            self.assertEqual(json.load(f)['task_id'], tid)

    def test_failure_keeps_completed_algorithm(self):
        orig_mf, orig_req = registry.module_file, registry.require
        # 造一个必然失败的注册条目（脚本 exit 2 语义失败）
        wd = tempfile.TemporaryDirectory()
        self.addCleanup(wd.cleanup)
        script = os.path.join(wd.name, 'fail_tool.py')
        with open(script, 'w', encoding='utf-8') as f:
            f.write(_SCRIPTS['semantic_fail'])
        fake_entry = {'module': 'clustering.fail_tool', 'timeout_s': 60}

        def mf(entry):
            return script if entry is fake_entry else orig_mf(entry)

        def req(cat, algo, acfg=None):
            return fake_entry if algo == 'alwaysfail' else orig_req(cat, algo,
                                                                    acfg)
        registry.module_file, registry.require = mf, req
        try:
            plan = self._plan(['kmeans', 'alwaysfail'])
            plan['parameters_by_algorithm']['alwaysfail'] = {}
            store, tid, results_dir = self._store(plan)
            analysis_runner.run_task(store, tid, results_dir)
        finally:
            registry.module_file, registry.require = orig_mf, orig_req
        rec = store.get(tid)
        self.assertEqual(rec['status'], models.FAILED)
        self.assertEqual(rec['error']['code'], 'UNKNOWN_USER')
        # 先完成的 kmeans 真实部分结果必须保留（不丢、不伪造）
        partial = rec['result']
        self.assertEqual(partial['status'], models.FAILED)
        self.assertEqual(len(partial['results']), 1)
        self.assertEqual(partial['results'][0]['algorithm_tool'],
                         'clustering_kmeans')
        self.assertIn('部分结果', partial['_note'])


if __name__ == '__main__':
    unittest.main()
