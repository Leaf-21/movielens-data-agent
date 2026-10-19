# -*- coding: utf-8 -*-
"""分类工具 registry 契约测试（成员A）。

验证 `classification_tool.run(payload)` 与成员B的 registry/runner 约定一致：
- payload 缺字段 -> 结构化错误（INVALID_PARAMETER）
- 版本不一致 -> VERSION_MISMATCH
- 成功时返回统一信封，含 runner 需要的版本与指标字段

用 mock 替换 predict，因此不需要清洗快照、模型文件或 scikit-learn。
"""
import unittest
import unittest.mock as mock

import _paths  # noqa: F401

from classification import classification_tool as ct
from classification import schemas

FAKE_META = {
    'model_version': 'cart-20261019',
    'parameters': {'max_depth': 12, 'min_samples_leaf': 100},
    'code_commit': 'testsha',
    'valid_roc_auc': 0.7768,
    'valid_pr_auc': 0.7967,
    'test_roc_auc': 0.7710,
    'test_pr_auc': 0.7872,
    'threshold': 0.49627,
}

FAKE_ITEM = {
    'algorithm': 'Decision Tree (entropy / ID3-C4.5 style split)',
    'algorithm_slug': 'cart',
    'model_version': 'cart-20261019',
    'predicted_class': 'HIGH_RATING',
    'positive_probability': 0.865831,
    'decision_score': 0.865831,
    'score_type': 'positive_probability',
    'parameters': {'max_depth': 12},
    'metrics': {'threshold': 0.49627, 'valid_roc_auc': 0.7768},
    'limitations': ['概率未经校准'],
    'features_used': {'user_mean': 3.6},
    'explain': None,
    'prediction_time_basis': 'train_snapshot(T1=974862386)',
}

FAKE_RESULT = {
    'task_type': 'classification',
    'status': 'SUCCESS',
    'data_version': 'movielens-1m-v2-clean-v1',
    'cleaning_rule_version': 'rule-v2',
    'feature_version': 'feat-v1',
    'split_version': 'split-v1',
    'target': {'user_id': 1, 'movie_id': 1193},
    'T1': 974862386,
    'T2': 976422054,
    'results': [FAKE_ITEM],
}

ENVELOPE_KEYS = ('algorithm', 'algorithm_tool', 'model_version', 'result_version',
                 'parameters', 'data_version', 'feature_version', 'T1', 'T2',
                 'code_version', 'created_at', 'metrics', 'results', 'limitations')


class TestPayloadValidation(unittest.TestCase):

    def test_missing_algorithm(self):
        with self.assertRaises(ct.ClassificationError) as ctx:
            ct.run({'user_id': 1, 'movie_id': 1193})
        self.assertEqual(ctx.exception.code, schemas.INVALID_PARAMETER)

    def test_unknown_algorithm(self):
        with self.assertRaises(ct.ClassificationError) as ctx:
            ct.run({'algorithm': 'svm', 'user_id': 1, 'movie_id': 1193})
        self.assertEqual(ctx.exception.code, schemas.INVALID_PARAMETER)

    def test_missing_ids(self):
        with self.assertRaises(ct.ClassificationError) as ctx:
            ct.run({'algorithm': 'gnb', 'user_id': 1})
        self.assertEqual(ctx.exception.code, schemas.INVALID_PARAMETER)

    def test_data_version_mismatch(self):
        with self.assertRaises(ct.ClassificationError) as ctx:
            ct.run({'algorithm': 'gnb', 'user_id': 1, 'movie_id': 2,
                    'data_version': 'movielens-1m-v1'})
        self.assertEqual(ctx.exception.code, schemas.VERSION_MISMATCH)

    def test_feature_version_mismatch(self):
        with self.assertRaises(ct.ClassificationError) as ctx:
            ct.run({'algorithm': 'gnb', 'user_id': 1, 'movie_id': 2,
                    'feature_version': 'feat-v0'})
        self.assertEqual(ctx.exception.code, schemas.VERSION_MISMATCH)


class TestEnvelope(unittest.TestCase):

    def _run(self, payload):
        with mock.patch.object(ct.predict, 'load_model', return_value=(None, FAKE_META)), \
                mock.patch.object(ct.predict, 'classify', return_value=FAKE_RESULT):
            return ct.run(payload)

    def test_envelope_shape(self):
        env = self._run({'algorithm': 'cart', 'user_id': 1, 'movie_id': 1193})
        for key in ENVELOPE_KEYS:
            self.assertIn(key, env, '信封缺少 %s' % key)
        self.assertEqual(env['algorithm'], 'cart')
        self.assertEqual(env['algorithm_tool'], 'classification_cart')
        self.assertEqual(env['data_version'], 'movielens-1m-v2-clean-v1')
        self.assertEqual(env['T1'], 974862386)
        self.assertEqual(env['code_version'], 'testsha')
        self.assertEqual(env['metrics']['threshold'], 0.49627)
        self.assertEqual(len(env['results']), 1)
        self.assertEqual(env['results'][0]['predicted_class'], 'HIGH_RATING')
        self.assertTrue(env['algorithm_source'].startswith('课程课件'))

    def test_result_version_is_deterministic(self):
        a = self._run({'algorithm': 'cart', 'user_id': 1, 'movie_id': 1193})
        b = self._run({'algorithm': 'cart', 'user_id': 1, 'movie_id': 1193})
        self.assertEqual(a['result_version'], b['result_version'])
        self.assertTrue(a['result_version'].startswith('cls-'))

    def test_tool_error_is_converted(self):
        err = schemas.ToolError(schemas.UNKNOWN_USER, 'UserID 999 不存在')
        with mock.patch.object(ct.predict, 'load_model', return_value=(None, FAKE_META)), \
                mock.patch.object(ct.predict, 'classify', side_effect=err):
            with self.assertRaises(ct.ClassificationError) as ctx:
                ct.run({'algorithm': 'gnb', 'user_id': 999, 'movie_id': 1})
        self.assertEqual(ctx.exception.code, schemas.UNKNOWN_USER)


if __name__ == '__main__':
    unittest.main()
