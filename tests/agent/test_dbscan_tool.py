# -*- coding: utf-8 -*-
"""
clustering_dbscan 工具单测（夹具合成数据）。

覆盖：eps 两种来源语义、噪声诚实标记（不塞群）、无样本外投影、
单簇时轮廓/DBI 为 null、确定性、版本与必需键、参数校验。
"""

import os
import sys
import unittest

import _paths  # noqa: F401
import analysis_fixture as fx  # noqa: F401

from common import AnalysisError   # noqa: E402
import dbscan_tool                 # noqa: E402

REQUIRED_KEYS = ('algorithm', 'algorithm_tool', 'model_version',
                 'result_version', 'parameters', 'data_version',
                 'profile_version', 'T1', 'T2', 'code_version', 'created_at',
                 'metrics', 'assignments', 'cluster_summaries', 'limitations')


class TestDBScanTool(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.ctx = fx.install()
        cls.f = cls.ctx.__enter__()
        cls.env_small = dbscan_tool.run(
            {'user_ids': fx.ALL_USERS, 'parameters': {'eps': 0.5},
             'data_version': cls.f.acfg['input']['data_version'],
             'profile_version': cls.f.acfg['profile_version']},
            acfg=cls.f.acfg, rcfg=cls.f.rcfg, quiet=True)

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    def test_envelope_contract(self):
        for k in REQUIRED_KEYS:
            self.assertIn(k, self.env_small)
        self.assertEqual(self.env_small['algorithm_tool'],
                         'clustering_dbscan')
        # DBSCAN 不提供样本外投影，质心仅为信息参考
        self.assertIn('cluster_centroids_reference', self.env_small)
        self.assertTrue(any('chaining' in s or '链' in s or '密度' in s
                            for s in self.env_small['limitations']))

    def test_two_blobs_and_noise(self):
        env = self.env_small
        mt = env['metrics']
        self.assertEqual(mt['n_clusters'], 2)
        self.assertEqual(mt['eps_method'], 'user_provided')
        self.assertEqual(mt['min_samples'], 3)
        lab = {a['user_id']: a for a in env['assignments']}
        a = {u: lab[u]['cluster_id'] for u in fx.ALL_USERS}
        self.assertEqual({a[1], a[2], a[3]}, {a[1]})
        self.assertEqual({a[4], a[5], a[6]}, {a[4]})
        self.assertNotEqual(a[1], a[4])
        # 用户 10（孤儿类型群）：密度上孤立 -> 噪声，不塞进任何群
        self.assertTrue(lab[10]['is_noise'])
        self.assertIsNone(lab[10]['cluster_id'])
        self.assertEqual(lab[10]['status'], 'UNASSIGNED_BY_DENSITY')
        self.assertEqual(mt['noise_count'], 1)

    def test_no_out_of_sample_projection(self):
        lab = {a['user_id']: a for a in self.env_small['assignments']}
        for u in (7, 8, 9):
            self.assertIsNone(lab[u]['cluster_id'])
            self.assertIn(lab[u]['status'], ('INSUFFICIENT_HISTORY',
                                             'NO_TRAIN_HISTORY'))

    def test_default_eps_from_kdistance(self):
        env = dbscan_tool.run(
            {'user_ids': fx.ALL_USERS, 'parameters': {},
             'data_version': self.f.acfg['input']['data_version'],
             'profile_version': self.f.acfg['profile_version']},
            acfg=self.f.acfg, rcfg=self.f.rcfg, quiet=True)
        mt = env['metrics']
        self.assertEqual(mt['eps_method'], 'kdistance_p90')
        self.assertIn('k_percentiles', mt['eps_kdistance'])
        self.assertAlmostEqual(mt['eps_used'],
                               mt['eps_kdistance']['k_percentiles']['p90'])
        # 默认 P90 把两团簇连成 1 个密度簇（chaining）：如实 null 指标
        self.assertEqual(mt['n_clusters'], 1)
        self.assertIsNone(mt['silhouette_full'])

    def test_metrics_fields_and_determinism(self):
        mt = self.env_small['metrics']
        self.assertEqual(mt['n_fit_users'], 7)
        self.assertEqual(sorted(mt['cluster_sizes'].values()), [3, 3])
        self.assertAlmostEqual(mt['noise_ratio'], 1.0 / 7.0, places=6)
        again = dbscan_tool.run(
            {'user_ids': fx.ALL_USERS, 'parameters': {'eps': 0.5},
             'data_version': self.f.acfg['input']['data_version'],
             'profile_version': self.f.acfg['profile_version']},
            acfg=self.f.acfg, rcfg=self.f.rcfg, quiet=True)
        self.assertEqual(again['result_version'],
                         self.env_small['result_version'])

    def test_min_samples_below_fit_users_errors(self):
        with self.assertRaises(AnalysisError) as cm:
            dbscan_tool.run(
                {'user_ids': fx.ALL_USERS,
                 'parameters': {'min_samples': 100},
                 'data_version': self.f.acfg['input']['data_version'],
                 'profile_version': self.f.acfg['profile_version']},
                acfg=self.f.acfg, rcfg=self.f.rcfg, quiet=True)
        self.assertEqual(cm.exception.code, 'ALGORITHM_ERROR')

    def test_unknown_user_and_invalid_param(self):
        base = {'data_version': self.f.acfg['input']['data_version'],
                'profile_version': self.f.acfg['profile_version']}
        with self.assertRaises(AnalysisError) as cm:
            dbscan_tool.run(dict(base, user_ids=[999999], parameters={}),
                            acfg=self.f.acfg, rcfg=self.f.rcfg, quiet=True)
        self.assertEqual(cm.exception.code, 'UNKNOWN_USER')
        with self.assertRaises(AnalysisError) as cm2:
            dbscan_tool.run(dict(base, user_ids=[1, 2],
                                 parameters={'min_samples': 2}),
                            acfg=self.f.acfg, rcfg=self.f.rcfg, quiet=True)
        self.assertEqual(cm2.exception.code, 'INVALID_PARAMETER')


if __name__ == '__main__':
    unittest.main()
