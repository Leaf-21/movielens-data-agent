# -*- coding: utf-8 -*-
"""
Hadoop Tool 封装单测。

用 fake_hadoop.FakeHadoopServer 模拟成员A的契约行为，验证：
  · 三个工具函数的请求/响应转发与字段校验（接口规范第 9-11 节）；
  · HTTP 200 + status=FAILED 被翻译为 HadoopToolError（保留环节/错误码）；
  · 连接不可用时给出可操作的提示而不是裸异常；
  · read_state 只读消费状态交接文件，且 task_id 不能穿越目录。
"""

import json
import os
import tempfile
import unittest

import _paths  # noqa: F401
import hadoop_tool
from fake_hadoop import FakeHadoopServer
from hadoop_tool import HadoopTool, HadoopToolError


class TestHadoopTool(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.srv = FakeHadoopServer(self.dir.name)
        self.tool = HadoopTool(base_url=self.srv.base_url, timeout=10)
        self._orig_state_dir = hadoop_tool.STATE_DIR
        hadoop_tool.STATE_DIR = self.dir.name

    def tearDown(self):
        hadoop_tool.STATE_DIR = self._orig_state_dir
        self.srv.stop()
        self.dir.cleanup()

    # ---- 成功路径 ----

    def test_quality_score_before_success(self):
        resp = self.tool.quality_score_before('task_x1', 'movielens-1m-v2')
        self.assertEqual(resp['status'], 'SUCCESS')
        self.assertEqual(resp['scores']['accurate'], 99.0)
        # 五维齐全
        for d in hadoop_tool.DIMENSIONS:
            self.assertIn(d, resp['scores'])

    def test_clean_dataset_success(self):
        self.tool.quality_score_before('task_x1', 'movielens-1m-v2')
        resp = self.tool.clean_dataset('task_x1', 'movielens-1m-v2', 'rule-v2')
        st = resp['statistics']
        # 修复/去重/隔离三个口径必须分别存在，不允许被合并成一个"处理数"
        for k in ('before_count', 'after_count', 'fixed_count',
                  'deduplicated_count', 'isolated_count'):
            self.assertIn(k, st)

    def test_quality_score_after_success(self):
        resp = self.tool.quality_score_after('task_x1', 'movielens-1m-clean')
        self.assertEqual(resp['scores']['consistent'], 98.3)

    def test_read_state_after_calls(self):
        self.tool.quality_score_before('task_x1', 'movielens-1m-v2')
        state = self.tool.read_state('task_x1')
        self.assertIsNotNone(state)
        self.assertEqual(state['_state'], 'BEFORE_DONE')
        self.assertEqual(state['before_metrics']['users_u_zip_bad'], 5)

    def test_read_state_missing_returns_none(self):
        self.assertIsNone(self.tool.read_state('task_never'))

    def test_read_state_does_not_write(self):
        # Agent 绝不写成员A的状态文件：读不存在的任务后文件仍不存在
        self.tool.read_state('task_untouched')
        self.assertFalse(os.path.exists(
            os.path.join(self.dir.name, 'task_untouched.json')))

    def test_health(self):
        self.assertEqual(self.tool.health()['status'], 'SUCCESS')

    # ---- 失败翻译 ----

    def _new_tool(self, fail_at):
        srv = FakeHadoopServer(self.dir.name, fail_at=fail_at)
        self.addCleanup(srv.stop)
        return HadoopTool(base_url=srv.base_url, timeout=10)

    def test_business_failure_translated_to_exception(self):
        tool = self._new_tool('before')
        with self.assertRaises(HadoopToolError) as cm:
            tool.quality_score_before('task_f1', 'movielens-1m-v2')
        self.assertEqual(cm.exception.stage, 'BEFORE_SCORE')
        self.assertEqual(cm.exception.code, 'QUALITY_SCORE_ERROR')

    def test_clean_failure_keeps_stage_and_code(self):
        tool = self._new_tool('clean')
        tool.quality_score_before('task_f2', 'movielens-1m-v2')
        with self.assertRaises(HadoopToolError) as cm:
            tool.clean_dataset('task_f2', 'movielens-1m-v2')
        self.assertEqual(cm.exception.stage, 'CLEANING')
        self.assertEqual(cm.exception.code, 'HADOOP_EXECUTION_ERROR')
        self.assertEqual(cm.exception.to_dict()['code'], 'HADOOP_EXECUTION_ERROR')

    def test_connection_refused_gives_guidance(self):
        srv = FakeHadoopServer(self.dir.name)
        url = srv.base_url
        srv.stop()  # 端口释放后再调用 -> 连接被拒
        tool = HadoopTool(base_url=url, timeout=5)
        with self.assertRaises(HadoopToolError) as cm:
            tool.quality_score_before('task_c1', 'movielens-1m-v2')
        self.assertIn('无法连接 Hadoop 服务', cm.exception.message)
        self.assertEqual(cm.exception.code, 'HADOOP_EXECUTION_ERROR')

    def test_health_never_raises(self):
        srv = FakeHadoopServer(self.dir.name)
        url = srv.base_url
        srv.stop()
        out = HadoopTool(base_url=url, timeout=5).health()
        self.assertEqual(out['status'], 'FAILED')

    # ---- 契约校验 ----

    def test_require_keys_missing(self):
        with self.assertRaises(HadoopToolError) as cm:
            HadoopTool._require_keys({'status': 'SUCCESS'},
                                     ('status', 'scores'), 'BEFORE_SCORE', '9')
        self.assertIn('缺少契约字段', cm.exception.message)
        self.assertEqual(cm.exception.code, 'QUALITY_SCORE_ERROR')

    def test_require_scores_missing_dimension(self):
        with self.assertRaises(HadoopToolError):
            HadoopTool._require_scores({'accurate': 1.0}, 'AFTER_SCORE', '11')

    def test_require_scores_allows_none_values(self):
        # 成员A无法计算时如实给 null，封装层不拦
        HadoopTool._require_scores({d: None for d in hadoop_tool.DIMENSIONS},
                                   'BEFORE_SCORE', '9')

    def test_task_id_path_traversal_blocked(self):
        for bad in ('../secret', 'a/b', 'id;rm', ''):
            with self.assertRaises(HadoopToolError):
                self.tool.state_path(bad)

    def test_state_path_normal(self):
        p = self.tool.state_path('task_20260926_0001')
        self.assertEqual(p, os.path.join(self.dir.name,
                                         'task_20260926_0001.json'))


if __name__ == '__main__':
    unittest.main()
