# -*- coding: utf-8 -*-
"""schemas 校验层单测：参数白名单、目标归一、UNKNOWN_USER 请求级语义。"""

import os
import sys
import unittest

import _paths  # noqa: F401
from _paths import AGENT_TOOLS

_C = os.path.join(AGENT_TOOLS, 'clustering')
if _C not in sys.path:
    sys.path.insert(0, _C)

from common import AnalysisError                     # noqa: E402
from clustering import schemas                       # noqa: E402
from clustering.schemas import (validate_parameters,  # noqa: E402
                                normalize_targets, user_statuses)

ALLOWED = {'kmeans': {'k': [2, 30], 'seed': [0, 100]},
           'dbscan': {'eps': [0.01, 50.0], 'min_samples': [3, 100]}}


class TestValidateParameters(unittest.TestCase):

    def test_passthrough_subset(self):
        self.assertEqual(validate_parameters('kmeans', {'k': 5}, ALLOWED),
                         {'k': 5})
        self.assertEqual(validate_parameters('kmeans', None, ALLOWED), {})

    def test_unknown_key_rejected(self):
        with self.assertRaises(AnalysisError) as cm:
            validate_parameters('kmeans', {'nclusters': 3}, ALLOWED)
        self.assertEqual(cm.exception.code, 'INVALID_PARAMETER')
        self.assertIn('k', str(cm.exception))  # 消息要列出允许清单

    def test_out_of_range_rejected(self):
        for bad in ({'k': 1}, {'k': 31}, {'seed': -1}):
            with self.assertRaises(AnalysisError) as cm:
                validate_parameters('kmeans', bad, ALLOWED)
            self.assertEqual(cm.exception.code, 'INVALID_PARAMETER')

    def test_bool_not_number(self):
        with self.assertRaises(AnalysisError):
            validate_parameters('kmeans', {'k': True}, ALLOWED)

    def test_string_number_rejected(self):
        with self.assertRaises(AnalysisError):
            validate_parameters('dbscan', {'eps': '1.5'}, ALLOWED)


class TestNormalizeTargets(unittest.TestCase):

    def test_dedupe_sort_and_str(self):
        self.assertEqual(
            normalize_targets({'user_ids': [5, '6', 5, 1]}), [1, 5, 6])
        self.assertEqual(normalize_targets({'user_id': 7}), [7])
        self.assertEqual(normalize_targets({'user_id': 3, 'user_ids': [8, 3]}),
                         [3, 8])

    def test_missing_both(self):
        with self.assertRaises(AnalysisError) as cm:
            normalize_targets({})
        self.assertEqual(cm.exception.code, 'INVALID_REQUEST')

    def test_non_list_user_ids(self):
        with self.assertRaises(AnalysisError) as cm:
            normalize_targets({'user_ids': 5})
        self.assertEqual(cm.exception.code, 'INVALID_REQUEST')

    def test_garbage_and_nonpositive(self):
        for payload in ({'user_ids': ['abc']}, {'user_ids': [0]},
                        {'user_ids': [-3]}):
            with self.assertRaises(AnalysisError) as cm:
                normalize_targets(payload)
            self.assertEqual(cm.exception.code, 'INVALID_REQUEST')

    def test_cap_20000(self):
        with self.assertRaises(AnalysisError) as cm:
            normalize_targets({'user_ids': list(range(1, 20002))})
        self.assertEqual(cm.exception.code, 'INVALID_REQUEST')


class TestUserStatuses(unittest.TestCase):

    PROF = {1: {}, 2: {}, 5: {}}

    def test_all_unknown_is_request_level_error(self):
        with self.assertRaises(AnalysisError) as cm:
            user_statuses([999, 888], self.PROF)
        self.assertEqual(cm.exception.code, 'UNKNOWN_USER')

    def test_partial_unknown_returns_split(self):
        known, unknown = user_statuses([1, 999], self.PROF)
        self.assertEqual(known, [1])
        self.assertEqual(unknown, ['999'])


class TestToolName(unittest.TestCase):

    def test_envelope_required_fields_doc_sync(self):
        # 与 analysis_runner.REQUIRED_ENV_KEYS 的对齐依赖 tool_envelope 签名，
        # 这里锁定 schemas 导出的契约函数存在即可（行为在工具级测试覆盖）
        self.assertTrue(callable(schemas.tool_envelope))
        self.assertTrue(callable(schemas.cluster_summaries))
        self.assertTrue(callable(schemas.versions_block))
        self.assertTrue(callable(schemas.result_version_of))


if __name__ == '__main__':
    unittest.main()
