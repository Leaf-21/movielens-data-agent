# -*- coding: utf-8 -*-
"""
clustering_kmeans 工具单测（夹具合成数据；数值为测试数据非真实结果）。

覆盖：统一信封必需键、团簇归属正确性、确定性与结果版本、
INSUFFICIENT/NO_TRAIN 的诚实语义、显式 k、UNKNOWN_USER / INVALID_PARAMETER。
"""

import os
import sys
import unittest

import _paths  # noqa: F401
import analysis_fixture as fx  # noqa: F401

from common import AnalysisError  # noqa: E402
import kmeans_tool               # noqa: E402

REQUIRED_KEYS = ('algorithm', 'algorithm_tool', 'model_version',
                 'result_version', 'parameters', 'data_version',
                 'profile_version', 'T1', 'T2', 'code_version', 'created_at',
                 'metrics', 'assignments', 'cluster_summaries', 'limitations')


class TestKMeansTool(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.ctx = fx.install()
        cls.f = cls.ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    def _payload(self, users=None, params=None):
        return {'user_ids': users or fx.ALL_USERS,
                'parameters': params or {},
                'data_version': self.f.acfg['input']['data_version'],
                'profile_version': self.f.acfg['profile_version']}

    def test_envelope_contract(self):
        env = kmeans_tool.run(self._payload(), acfg=self.f.acfg,
                              rcfg=self.f.rcfg, quiet=True)
        for k in REQUIRED_KEYS:
            self.assertIn(k, env)
        self.assertEqual(env['algorithm'], 'kmeans')
        self.assertEqual(env['algorithm_tool'], 'clustering_kmeans')
        self.assertEqual(env['data_version'], 'movielens-1m-v2-clean-v1')
        self.assertEqual(env['profile_version'], 'profile-test')
        self.assertTrue(env['model_version'].startswith('mdl-'))
        self.assertTrue(env['result_version'].startswith('res-'))
        self.assertEqual(len(env['assignments']), len(fx.ALL_USERS))
        self.assertTrue(any('kmeans++' in s for s in env['limitations']))

    def test_blob_assignment_and_honest_statuses(self):
        env = kmeans_tool.run(self._payload(), acfg=self.f.acfg,
                              rcfg=self.f.rcfg, quiet=True)
        lab = {a['user_id']: a for a in env['assignments']}
        a = {u: lab[u]['cluster_id'] for u in fx.ALL_USERS}
        # 群内同簇、群间分簇（夹具两团簇相距足够远）
        self.assertEqual({a[1], a[2], a[3]}, {a[1]})
        self.assertEqual({a[4], a[5], a[6]}, {a[4]})
        self.assertNotEqual(a[1], a[4])
        # 历史不足：最近质心参考 + reliability_low
        self.assertEqual(lab[7]['status'], 'ASSIGNED_FROM_FITTED_CENTROIDS')
        self.assertTrue(lab[7]['reliability_low'])
        # 无训练记录：不伪造归属
        for u in (8, 9):
            self.assertEqual(lab[u]['status'], 'NO_TRAIN_HISTORY')
            self.assertIsNone(lab[u]['cluster_id'])

    def test_metrics_and_definitions(self):
        env = kmeans_tool.run(self._payload(), acfg=self.f.acfg,
                              rcfg=self.f.rcfg, quiet=True)
        mt = env['metrics']
        self.assertIn(mt['k_selected'], [2, 3])
        self.assertEqual([t['k'] for t in mt['k_selection_table']], [2, 3])
        self.assertGreater(mt['silhouette_full'], 0.5)
        self.assertEqual(mt['n_fit_users'], 7)
        self.assertIn('silhouette', mt['definition'])
        self.assertEqual(mt['k_selection_rule'],
                         self.f.acfg['algorithms']['clustering']['kmeans']
                         ['selection_rule'])

    def test_summaries_real_stats(self):
        env = kmeans_tool.run(self._payload(), acfg=self.f.acfg,
                              rcfg=self.f.rcfg, quiet=True)
        sizes = sorted(s['size'] for s in env['cluster_summaries'])
        self.assertEqual(sizes, [1, 3, 3])
        drama = next(s for s in env['cluster_summaries']
                    if s['cluster_id'] == env['assignments'][0]['cluster_id'])
        self.assertAlmostEqual(drama['avg_rating_mean'], 4.75, places=6)
        titles = {m['title'] for m in drama['representative_movies']}
        self.assertIn('Movie One (1990)', titles)  # 3 人群内高分 >= min_member_votes
        self.assertIn('真实统计', drama['summary_basis'])

    def test_determinism_and_result_version_stability(self):
        e1 = kmeans_tool.run(self._payload(), acfg=self.f.acfg,
                             rcfg=self.f.rcfg, quiet=True)
        e2 = kmeans_tool.run(self._payload(), acfg=self.f.acfg,
                             rcfg=self.f.rcfg, quiet=True)
        self.assertEqual(e1['result_version'], e2['result_version'])
        self.assertEqual([(a['user_id'], a['cluster_id']) for a in
                          e1['assignments']],
                         [(a['user_id'], a['cluster_id']) for a in
                          e2['assignments']])

    def test_explicit_k_fixes_candidates(self):
        env = kmeans_tool.run(self._payload(params={'k': 2}),
                              acfg=self.f.acfg, rcfg=self.f.rcfg, quiet=True)
        self.assertEqual(env['metrics']['k_selected'], 2)
        self.assertEqual([t['k'] for t in env['metrics']['k_selection_table']],
                         [2])
        self.assertEqual(env['parameters']['k'], 2)

    def test_unknown_user(self):
        with self.assertRaises(AnalysisError) as cm:
            kmeans_tool.run(self._payload(users=[999999]), acfg=self.f.acfg,
                            rcfg=self.f.rcfg, quiet=True)
        self.assertEqual(cm.exception.code, 'UNKNOWN_USER')

    def test_invalid_parameter_range_and_key(self):
        for bad in ({'k': 1}, {'k': 31}, {'nope': 1}):
            with self.assertRaises(AnalysisError) as cm:
                kmeans_tool.run(self._payload(params=bad), acfg=self.f.acfg,
                                rcfg=self.f.rcfg, quiet=True)
            self.assertEqual(cm.exception.code, 'INVALID_PARAMETER')

    def test_no_targets_invalid_request(self):
        with self.assertRaises(AnalysisError) as cm:
            kmeans_tool.run({'user_ids': [], 'parameters': {}},
                            acfg=self.f.acfg, rcfg=self.f.rcfg, quiet=True)
        self.assertEqual(cm.exception.code, 'INVALID_REQUEST')


if __name__ == '__main__':
    unittest.main()
