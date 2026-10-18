# -*- coding: utf-8 -*-
"""
训练期用户画像（profile-v1 口径）单测——夹具为合成小数据（数值均为测试数据）。

覆盖：训练期边界（T1 前后）、三类用户状态计数、孤儿引用登记、
特征手算对账、scaler 仅用 OK 用户、可复现（同输入字节级一致）。
"""

import hashlib
import os
import sys
import unittest

import _paths  # noqa: F401
import analysis_fixture as fx  # noqa: F401  (完成 clustering 路径引导)

import config  # noqa: E402
import build_profile as bp  # noqa: E402


def _sha(fp):
    with open(fp, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


class TestProfile(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.ctx = fx.install()
        cls.f = cls.ctx.__enter__()
        cls.prof_path, cls.meta = bp.build_profile(cls.f.acfg, cls.f.rcfg,
                                                   quiet=True)
        cls.users = bp.load_profile(cls.prof_path)

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    def test_status_counts(self):
        self.assertEqual(self.meta['n_users_total'], 10)
        self.assertEqual(self.meta['n_profile_ok'], 7)
        self.assertEqual(self.meta['n_insufficient_history'], 1)
        self.assertEqual(self.meta['n_no_train_history'], 2)

    def test_t1_boundary_only_training_window(self):
        # 用户 8 只有 (T1,T2] 评分：不得混入训练期特征
        r8 = self.users[8]
        self.assertFalse(r8['fit'])
        self.assertIsNone(r8['features'])
        self.assertIsNone(r8['vector'])
        self.assertIn('训练期', r8['note'])

    def test_insufficient_user(self):
        r7 = self.users[7]
        self.assertEqual(r7['status'], 'INSUFFICIENT_HISTORY')
        self.assertFalse(r7['fit'])
        self.assertIsNotNone(r7['features'])   # 特征保留供解释
        self.assertIsNotNone(r7['vector'])
        self.assertEqual(int(r7['features']['n_ratings']), 3)

    def test_no_ratings_user(self):
        r9 = self.users[9]
        self.assertFalse(r9['fit'])
        self.assertIsNone(r9['features'])

    def test_orphans_registered_not_dropped(self):
        self.assertEqual(self.meta['n_train_users_not_in_users_dat'], 1)
        self.assertEqual(self.meta['orphan_user_ids'], [fx.ORPHAN_USER])
        self.assertNotIn(fx.ORPHAN_USER, self.users)  # 画像域以 users.dat 为准

    def test_feature_values_hand_check(self):
        f1 = self.users[1]['features']
        self.assertEqual(int(f1['n_ratings']), 8)
        self.assertAlmostEqual(float(f1['avg_rating']), 4.75)
        self.assertAlmostEqual(float(f1['high_share']), 1.0)
        # 类型 slug 规范化：Children's -> genre_share_childrens（去撇号/空格）
        self.assertIn('genre_share_childrens', self.meta['feature_names'])
        self.assertAlmostEqual(float(f1['genre_share_drama']), 1.0, places=6)
        self.assertAlmostEqual(float(f1['genre_share_childrens']), 0.0)

    def test_global_mean_hand_check(self):
        # (3*38 + 3*14 + 8*3 + 9 + 4) / (24+24+8+3+1) = 193/60
        self.assertAlmostEqual(self.meta['global_train_mean_rating'],
                               193.0 / 60.0, places=9)

    def test_scaler_fitted_on_ok_users_only(self):
        mean = self.meta['scaler']['mean']
        # OK 用户 avg_rating: 4.75*3, 1.75*3(注:恐怖群和为14/8=1.75), 3.0*1
        want = (3 * 4.75 + 3 * (14.0 / 8.0) + 3.0) / 7.0
        self.assertAlmostEqual(mean['avg_rating'], want, places=9)
        self.assertNotIn('_status_override', str(self.meta['scaler']))

    def test_determinism_same_input(self):
        sha1 = _sha(self.prof_path)
        # force 重建：同输入同口径必须字节级一致（created_at 在 meta 不在 jsonl）
        prof2, meta2 = bp.build_profile(self.f.acfg, self.f.rcfg,
                                        force=True, quiet=True)
        self.assertEqual(_sha(prof2), sha1)
        self.assertEqual(meta2['input_sha256'], self.meta['input_sha256'])
        self.assertEqual(meta2['config_fingerprint'],
                         self.meta['config_fingerprint'])

    def test_cache_reuse_when_inputs_unchanged(self):
        before = self.meta['created_at']
        prof2, meta2 = bp.build_profile(self.f.acfg, self.f.rcfg, quiet=True)
        self.assertEqual(meta2['created_at'], before)  # 命中缓存，未重建

    def test_missing_snapshot_raises_data_unavailable(self):
        from common import AnalysisError
        bad = dict(self.f.acfg)
        bad['input'] = dict(bad['input'], clean_dir='no/such/dir')
        with self.assertRaises(AnalysisError) as cm:
            bp.build_profile(bad, self.f.rcfg, force=True, quiet=True)
        self.assertEqual(cm.exception.code, 'DATA_UNAVAILABLE')


if __name__ == '__main__':
    unittest.main()
