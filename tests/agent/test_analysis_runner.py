# -*- coding: utf-8 -*-
"""
分析任务执行器单测：子进程协议（成功/语义失败不重试/崩溃重试/违约拒收）
与任务级装配（SUCCESS 字段、失败保留已完成算法的部分结果）。

协议类用例用临时脚本冒充工具（不经注册表），真实算法用例走夹具数据。
"""

import json
import os
import subprocess
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



class TestToolSubprocessEnv(unittest.TestCase):
    """回归 2026-10-21 修好的两处环境缺陷（本机曾导致分类/降维整类任务失败）。

    缺陷一：`python3 -I` 隐含 `-s`，不含用户级 site-packages，numpy 装在
      `pip install --user` 时分类/降维子进程 import 即失败；
    缺陷二：分类/降维默认读 `data/<清洗版本>/`，与聚类读的
      `analysis.json.input.clean_dir` 不是同一路径，默认配置下 DATA_UNAVAILABLE。
    """

    def test_tool_command_keeps_isolation_flag(self):
        cmd = analysis_runner.tool_command('/x/tool.py', '--request', 'r.json')
        self.assertEqual(cmd[0], sys.executable)
        self.assertEqual(cmd[1], '-I')          # 隔离隔离语义必须保留（防 WSL 段错误）
        self.assertEqual(cmd[2], '-c')
        self.assertIn('runpy', cmd[3])
        self.assertEqual(cmd[-3], '/x/tool.py')
        self.assertEqual(cmd[-2:], ['--request', 'r.json'])

    def test_tool_command_carries_user_site(self):
        paths = analysis_runner.tool_search_paths()
        user_site = None
        try:
            import site
            user_site = site.getusersitepackages()
        except Exception:
            pass
        if user_site and os.path.isdir(user_site):
            self.assertIn(user_site, paths)
        for p in paths:
            self.assertTrue(os.path.isdir(p), '只登记真实存在的目录: %s' % p)

    def test_extra_path_env_appended_without_duplicates(self):
        wd = tempfile.TemporaryDirectory()
        self.addCleanup(wd.cleanup)
        orig = os.environ.get('ML_TOOL_EXTRA_PATH')
        os.environ['ML_TOOL_EXTRA_PATH'] = os.pathsep.join(
            [wd.name, wd.name, '/no/such/dir'])
        try:
            paths = analysis_runner.tool_search_paths()
        finally:
            if orig is None:
                os.environ.pop('ML_TOOL_EXTRA_PATH', None)
            else:
                os.environ['ML_TOOL_EXTRA_PATH'] = orig
        self.assertEqual(paths.count(wd.name), 1)   # 去重
        self.assertNotIn('/no/such/dir', paths)     # 不存在的目录不进

    def test_tool_env_injects_clean_dir_from_analysis_config(self):
        orig = os.environ.pop('ML_CLEAN_DIR', None)
        try:
            env = analysis_runner.tool_env()
        finally:
            if orig is not None:
                os.environ['ML_CLEAN_DIR'] = orig
        expect = config.resolve_repo_path(config.load_analysis()['input']['clean_dir'])
        if os.path.isdir(expect):
            self.assertEqual(env['ML_CLEAN_DIR'], expect)
        self.assertEqual(env.get('PYTHONIOENCODING'), 'utf-8')

    def test_tool_env_never_overrides_explicit_clean_dir(self):
        orig = os.environ.get('ML_CLEAN_DIR')
        os.environ['ML_CLEAN_DIR'] = '/explicit/choice'
        try:
            env = analysis_runner.tool_env()
        finally:
            if orig is None:
                os.environ.pop('ML_CLEAN_DIR', None)
            else:
                os.environ['ML_CLEAN_DIR'] = orig
        self.assertEqual(env['ML_CLEAN_DIR'], '/explicit/choice')

    def test_child_can_import_user_site_package(self):
        """端到端：`-I` 子进程里能否 import numpy（缺依赖则跳过，不伪装通过）。"""
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest('本机未安装 numpy，跳过依赖可见性验证')
        wd = tempfile.TemporaryDirectory()
        self.addCleanup(wd.cleanup)
        script = os.path.join(wd.name, 'probe.py')
        out = os.path.join(wd.name, 'probe.json')
        with open(script, 'w', encoding='utf-8') as f:
            f.write("""
import argparse, json
p = argparse.ArgumentParser(); p.add_argument('--output')
a = p.parse_args()
import numpy
json.dump({'numpy': numpy.__version__}, open(a.output, 'w'))
""")
        cmd = analysis_runner.tool_command(script, '--output', out)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                              env=analysis_runner.tool_env())
        self.assertEqual(proc.returncode, 0, proc.stderr[-1500:])
        with open(out, encoding='utf-8') as f:
            self.assertTrue(json.load(f)['numpy'])

    def test_missing_dependency_detected(self):
        """依赖缺失要从 stderr 里认出来（numpy/sklearn 两种写法）。"""
        cases = [
            ("Traceback (most recent call last):\n"
             "  File \"x.py\", line 30, in <module>\n"
             "    import numpy as np\n"
             "ModuleNotFoundError: No module named 'numpy'", 'numpy'),
            ("ModuleNotFoundError: No module named 'sklearn.tree'", 'sklearn'),
            ("ImportError: cannot import name 'foo'", None),
            ("", None),
            ("Some unrelated failure", None),
        ]
        for stderr, expect in cases:
            self.assertEqual(analysis_runner.missing_dependency(stderr), expect,
                             'stderr=%r' % stderr[:60])

    def test_dependency_hint_is_actionable(self):
        """提示必须同时给出装依赖与加路径两条修法，并能用 ML_TOOL_EXTRA_PATH。"""
        hint = analysis_runner.dependency_hint('numpy')
        self.assertIn('numpy', hint)
        self.assertIn('pip install -r requirements.txt', hint)
        self.assertIn('ML_TOOL_EXTRA_PATH', hint)
        self.assertIn('-I', hint)          # 说明为什么仍是隔离模式

    def test_real_missing_dependency_surfaces_actionable_error(self):
        """端到端：子进程真缺模块时，错误消息应含修法而不是只报"退出码 1"。"""
        wd = tempfile.TemporaryDirectory()
        self.addCleanup(wd.cleanup)
        script = os.path.join(wd.name, 'needs_missing.py')
        out = os.path.join(wd.name, 'never.json')
        with open(script, 'w', encoding='utf-8') as f:
            f.write("import totally_absent_module_xyz\n")
        orig_cmd = analysis_runner.tool_command
        orig_mf = registry.module_file
        analysis_runner.tool_command = lambda tool, *a: ([sys.executable, '-I', tool]
                                                         + list(a))
        registry.module_file = lambda entry: script
        try:
            with self.assertRaises(AnalysisError) as cm:
                analysis_runner._run_tool_subprocess(
                    {'timeout_s': 60}, 'fake', 'test_missingdep',
                    {'user_ids': [1]}, [])
        finally:
            analysis_runner.tool_command = orig_cmd
            registry.module_file = orig_mf
        self.assertEqual(cm.exception.code, 'ALGORITHM_ERROR')
        msg = cm.exception.message
        self.assertIn('totally_absent_module_xyz', msg)
        self.assertIn('pip install', msg)
        self.assertEqual(cm.exception.details.get('missing_module'),
                         'totally_absent_module_xyz')

    def test_child_receives_clean_dir(self):
        wd = tempfile.TemporaryDirectory()
        self.addCleanup(wd.cleanup)
        script = os.path.join(wd.name, 'envprobe.py')
        out = os.path.join(wd.name, 'env.json')
        with open(script, 'w', encoding='utf-8') as f:
            f.write("""
import argparse, json, os
p = argparse.ArgumentParser(); p.add_argument('--output')
a = p.parse_args()
json.dump({'clean': os.environ.get('ML_CLEAN_DIR')}, open(a.output, 'w'))
""")
        cmd = analysis_runner.tool_command(script, '--output', out)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                              env=analysis_runner.tool_env())
        self.assertEqual(proc.returncode, 0, proc.stderr[-1500:])
        with open(out, encoding='utf-8') as f:
            clean = json.load(f)['clean']
        self.assertTrue(clean, '子进程必须拿到 ML_CLEAN_DIR（否则分类/降维 DATA_UNAVAILABLE）')


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
