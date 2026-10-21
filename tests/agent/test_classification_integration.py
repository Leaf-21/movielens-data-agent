# -*- coding: utf-8 -*-
"""分类工具与 Agent 层的接入契约（成员A）。

回归 2026-10-21 排查出的两处断点：

1. `agent/config/analysis.json` 未登记 gnb/cart -> `registry.require` 抛
   MODEL_NOT_FOUND，router 在解析阶段就报"类别 classification 尚无登记算法"；
2. `analysis_runner` 的 payload 没带 algorithm -> 工具抛 INVALID_PARAMETER
   （分类工具一个文件服务两个登记条目，必须由 payload 告知跑哪个算法）。

本测试不需要清洗快照、模型文件或 scikit-learn；import 放在用例内部，避免在
收集阶段就把 clustering/ 目录压到 common 包前面（测试之间共享 sys.path）。
"""
import os
import unittest

import _paths  # noqa: F401


def _plan():
    return {
        'task_type': 'classification',
        'algorithms': ['gnb', 'cart'],
        'user_ids': [4169],
        'classification_target': {'user_id': 4169, 'movie_id': 260},
        'parameters_by_algorithm': {'gnb': {}, 'cart': {}},
        'data_version': 'movielens-1m-v2-clean-v1',
        'profile_version': 'profile-v1',
        'notes': '',
    }


class TestClassificationRegistration(unittest.TestCase):
    def test_both_algorithms_registered(self):
        import config
        import registry
        acfg = config.load_analysis()
        self.assertEqual(registry.algorithm_names('classification', acfg),
                         ['cart', 'gnb'])

    def test_module_file_exists(self):
        import registry
        for algo in ('gnb', 'cart'):
            entry = registry.require('classification', algo)
            tool_file = registry.module_file(entry)
            self.assertTrue(os.path.exists(tool_file),
                            '登记条目指向的工具文件不存在: %s' % tool_file)


class TestRunnerPayload(unittest.TestCase):
    def test_classification_payload_has_algorithm_and_target(self):
        import analysis_runner
        for algo in ('gnb', 'cart'):
            p = analysis_runner.tool_payload('classification', _plan(), algo)
            self.assertEqual(p['algorithm'], algo)
            self.assertEqual(p['user_id'], 4169)
            self.assertEqual(p['movie_id'], 260)
            self.assertEqual(p['data_version'], 'movielens-1m-v2-clean-v1')

    def test_clustering_payload_unchanged(self):
        import analysis_runner
        plan = {'user_ids': [1, 2],
                'parameters_by_algorithm': {'kmeans': {'k': 3}},
                'data_version': 'x', 'profile_version': 'y'}
        p = analysis_runner.tool_payload('clustering', plan, 'kmeans')
        self.assertNotIn('algorithm', p)
        self.assertEqual(p['user_ids'], [1, 2])
        self.assertEqual(p['parameters'], {'k': 3})
