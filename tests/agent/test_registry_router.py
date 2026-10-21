# -*- coding: utf-8 -*-
"""
统一注册表与自然语言路由单测（真实仓库配置口径；不跑重计算）。

覆盖：MODEL_NOT_FOUND 单一真源语义、类别/算法/用户/参数解析优先级、
版本不匹配的归一翻译、参数按算法裁剪、body 与 query 冲突记录。
"""

import os
import sys
import unittest

import _paths  # noqa: F401
from _paths import AGENT_TOOLS

_C = os.path.join(AGENT_TOOLS, 'clustering')
if _C not in sys.path:
    sys.path.insert(0, _C)

import config          # noqa: E402
import registry        # noqa: E402
import router as nl_router  # noqa: E402
from common import AnalysisError  # noqa: E402

_HAS_SNAPSHOT = os.path.exists(
    os.path.join(config.resolve_repo_path(
        config.load_analysis()['input']['clean_dir']), 'users.dat'))


class TestRegistry(unittest.TestCase):

    def test_algorithm_names_single_source(self):
        self.assertEqual(registry.algorithm_names('clustering'),
                         ['dbscan', 'kmeans'])
        self.assertEqual(registry.algorithm_names('classification'),
                         ['cart', 'gnb'])
        self.assertEqual(registry.algorithm_names('dimensionality_reduction'),
                         ['pca', 'tsne'])

    def test_tool_naming_convention(self):
        self.assertEqual(registry.tool_name('clustering', 'kmeans'),
                         'clustering_kmeans')
        self.assertEqual(registry.implemented_tools(),
                         ['clustering_dbscan', 'clustering_kmeans',
                          'classification_cart', 'classification_gnb',
                          'dimensionality_reduction_pca',
                          'dimensionality_reduction_tsne'])

    def test_require_registered(self):
        entry = registry.require('clustering', 'kmeans')
        self.assertEqual(entry['module'], 'clustering.kmeans_tool')
        self.assertTrue(os.path.exists(registry.module_file(entry)))
        for cat, algo in (('dimensionality_reduction', 'pca'),
                          ('dimensionality_reduction', 'tsne')):
            e = registry.require(cat, algo)
            self.assertTrue(os.path.exists(registry.module_file(e)))

    def test_require_unregistered_model_not_found(self):
        for cat, algo in (('clustering', 'pca'), ('classification', 'xgboost'),
                          ('dimensionality_reduction', 'umap')):
            with self.assertRaises(AnalysisError) as cm:
                registry.require(cat, algo)
            self.assertEqual(cm.exception.code, 'MODEL_NOT_FOUND')

    def test_category_slugs(self):
        self.assertEqual(registry.CATEGORY_SLUGS['dimensionality-reduction'],
                         'dimensionality_reduction')


class TestRouter(unittest.TestCase):

    def _route(self, category, payload):
        return nl_router.route(category, payload)

    def test_default_runs_both_algorithms(self):
        plan = self._route('clustering', {'user_ids': [1]})
        self.assertEqual(plan['task_type'], 'clustering')
        self.assertEqual(plan['algorithms'], ['dbscan', 'kmeans'])
        self.assertIn('对照', plan['notes'])
        self.assertEqual(plan['data_version'], 'movielens-1m-v2-clean-v1')
        self.assertEqual(plan['profile_version'], 'profile-v1')

    def test_dimensionality_reduction_defaults_to_registered_population(self):
        plan = self._route('dimensionality-reduction', {
            'query': '对用户画像进行降维'
        })
        self.assertEqual(plan['task_type'], 'dimensionality_reduction')
        self.assertIsNone(plan['user_ids'])
        self.assertEqual(plan['algorithms'], ['pca', 'tsne'])
        self.assertIn('已登记的拟合画像用户', plan['notes'])

    def test_query_algorithm_keywords(self):
        self.assertEqual(
            self._route('clustering', {'query': '用k-means给用户 1 分组',
                                       'user_ids': [1]})['algorithms'],
            ['kmeans'])
        self.assertEqual(
            self._route('clustering', {'query': 'kmeans 和 dbscan 都跑，用户 1',
                                       'user_ids': [1]})['algorithms'],
            ['dbscan', 'kmeans'])

    def test_body_algorithm_field_authoritative(self):
        plan = self._route('clustering', {'user_ids': [1],
                                          'algorithm': 'K-Means'})
        self.assertEqual(plan['algorithms'], ['kmeans'])
        self.assertIn('请求字段', plan['notes'])

    def test_unregistered_algorithm_model_not_found(self):
        with self.assertRaises(AnalysisError) as cm:
            self._route('clustering', {'user_ids': [1], 'algorithm': 'hdbscan'})
        self.assertEqual(cm.exception.code, 'MODEL_NOT_FOUND')

    def test_classification_requires_movie_id(self):
        # 分类已登记（gnb/cart）；缺 movie_id 是请求不完整，不是“类别尚未实现”。
        with self.assertRaises(AnalysisError) as cm:
            self._route('classification',
                        {'query': '预测用户 1 是否会喜欢电影', 'user_ids': [1]})
        self.assertEqual(cm.exception.code, 'INVALID_REQUEST')
        self.assertIn('movie_id', cm.exception.message)

    def test_classification_plan_with_target(self):
        plan = self._route('classification',
                           {'query': '预测用户 1 是否喜欢电影 260',
                            'user_ids': [1], 'movie_id': 260})
        self.assertEqual(plan['task_type'], 'classification')
        self.assertEqual(plan['algorithms'], ['cart', 'gnb'])
        self.assertEqual(plan['classification_target'],
                         {'user_id': 1, 'movie_id': 260})

    def test_no_users_invalid_request(self):
        with self.assertRaises(AnalysisError) as cm:
            self._route('clustering', {'query': '给用户聚类分组'})
        self.assertEqual(cm.exception.code, 'INVALID_REQUEST')
        self.assertIn('不会替你挑选', cm.exception.message)

    def test_user_ids_must_be_list(self):
        with self.assertRaises(AnalysisError) as cm:
            self._route('clustering', {'user_ids': 1})
        self.assertEqual(cm.exception.code, 'INVALID_REQUEST')

    def test_query_user_extraction_and_body_priority(self):
        plan = self._route('clustering', {'query': '把用户 3 和用户 5 聚类'})
        self.assertEqual(plan['user_ids'], [3, 5])
        plan2 = self._route('clustering',
                            {'query': '把用户 3 聚类', 'user_ids': [5]})
        self.assertEqual(plan2['user_ids'], [5])
        self.assertIn('以请求字段为准', plan2['notes'])

    def test_version_mismatches(self):
        with self.assertRaises(AnalysisError) as cm:
            self._route('clustering', {'user_ids': [1],
                                       'data_version': 'movielens-1m-v1'})
        self.assertEqual(cm.exception.code, 'VERSION_MISMATCH')
        with self.assertRaises(AnalysisError) as cm2:
            self._route('clustering', {'user_ids': [1],
                                       'data_version': 'totally-bogus'})
        self.assertEqual(cm2.exception.code, 'VERSION_MISMATCH')
        with self.assertRaises(AnalysisError) as cm3:
            self._route('clustering', {'user_ids': [1],
                                       'profile_version': 'profile-v9'})
        self.assertEqual(cm3.exception.code, 'VERSION_MISMATCH')

    def test_category_consistency_guidance(self):
        with self.assertRaises(AnalysisError) as cm:
            self._route('classification', {'query': '给用户做聚类',
                                           'user_ids': [1]})
        self.assertEqual(cm.exception.code, 'INVALID_REQUEST')
        self.assertIn('/api/analysis/clustering/tasks', cm.exception.message)
        with self.assertRaises(AnalysisError) as cm2:
            self._route('clustering', {'query': '聚类并降维用户 1',
                                       'user_ids': [1]})
        self.assertEqual(cm2.exception.code, 'INVALID_REQUEST')
        self.assertIn('拆分', cm2.exception.message)

    def test_parameters_pruned_per_algorithm(self):
        plan = self._route('clustering', {'user_ids': [1],
                                          'parameters': {'k': 5, 'eps': 1.5}})
        pba = plan['parameters_by_algorithm']
        self.assertEqual(pba['kmeans'], {'k': 5})
        self.assertEqual(pba['dbscan'], {'eps': 1.5})
        # 多算法对照时：对他法合法、对己法不适用的参数按算法裁剪并登记 notes
        self.assertIn('已忽略', plan['notes'])
        # 单算法选择了它不支持的参数名 -> 如实拒绝，绝不静默丢弃
        with self.assertRaises(AnalysisError) as cm3:
            self._route('clustering', {'user_ids': [1], 'algorithm': 'kmeans',
                                       'parameters': {'eps': 1.5}})
        self.assertEqual(cm3.exception.code, 'INVALID_PARAMETER')
        with self.assertRaises(AnalysisError) as cm:
            self._route('clustering', {'user_ids': [1],
                                       'parameters': {'nclusters': 3}})
        self.assertEqual(cm.exception.code, 'INVALID_PARAMETER')
        with self.assertRaises(AnalysisError) as cm2:
            self._route('clustering', {'user_ids': [1],
                                       'parameters': {'k': 1}})
        self.assertEqual(cm2.exception.code, 'INVALID_PARAMETER')

    def test_query_length_cap(self):
        with self.assertRaises(AnalysisError) as cm:
            self._route('clustering', {'query': '聚' * 2001,
                                       'user_ids': [1]})
        self.assertEqual(cm.exception.code, 'INVALID_REQUEST')

    @unittest.skipUnless(_HAS_SNAPSHOT, '清洗快照不可用')
    def test_all_unknown_users_rejected_at_creation(self):
        with self.assertRaises(AnalysisError) as cm:
            self._route('clustering', {'user_ids': [999999, 888888]})
        self.assertEqual(cm.exception.code, 'UNKNOWN_USER')

    @unittest.skipUnless(_HAS_SNAPSHOT, '清洗快照不可用')
    def test_partial_unknown_filtered_with_note(self):
        plan = self._route('clustering', {'user_ids': [1, 999999]})
        self.assertEqual(plan['user_ids'], [1])
        self.assertIn('UNKNOWN_USER', plan['notes'])


if __name__ == '__main__':
    unittest.main()
