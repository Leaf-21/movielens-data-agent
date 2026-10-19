# -*- coding: utf-8 -*-
"""分类特征与预测入口测试（成员A，迭代二）。

重点覆盖防泄漏（D-06、C-03）与异常状态（C-06）：
- 目标事件自身的 Rating 不进入特征；
- 同一秒内的其它事件也不参与该事件的特征；
- 未来事件不影响过去事件；
- 缺少用户属性的样本被显式标记；
- 未知用户/电影、模型缺失返回结构化错误而不是占位结果。

这些用例只用 numpy 与标准库；训练相关用例在未安装 scikit-learn 时跳过。
"""
import os
import shutil
import sys
import tempfile
import unittest
import uuid

import _paths  # noqa: F401

import numpy as np

from classification import common_features, schemas

HAVE_SKLEARN = True
try:
    import sklearn  # noqa: F401
except ImportError:
    HAVE_SKLEARN = False

RULES = {
    'output_version': 'test-clean-v1',
    'rule_version': 'rule-test',
    'time': {'T1_epoch': 200, 'T2_epoch': 350},
    'genres': {'valid': ['Action', 'Comedy', 'Drama']},
    'users': {'occupation_min': 0, 'occupation_max': 20,
              'valid_age': ['1', '18', '25', '35', '45', '50', '56']},
}

# 临时目录放在仓库内，避免依赖系统 TEMP 的写权限（部分环境/沙箱不可写）
TMP_ROOT = os.path.join(_paths.REPO_DIR, '.test-tmp')
if not os.path.isdir(TMP_ROOT):
    os.makedirs(TMP_ROOT)


def _mkdtemp(prefix):
    """在 TMP_ROOT 下建唯一目录（不用 tempfile.mkdtemp，避免 0700 权限问题）。"""
    path = os.path.join(TMP_ROOT, prefix + uuid.uuid4().hex[:8])
    os.makedirs(path)
    return path

USERS = [
    '1::F::25::10::12345',
    '2::M::35::5::23456',
]

MOVIES = [
    '10::Movie A (2000)::Action|Comedy',
    '11::Movie B (2000)::Drama',
]

RATINGS = [
    '1::10::1::100',
    '2::10::4::150',
    '1::10::5::300',
    '1::11::4::300',
    '3::11::3::320',
    '3::10::5::320',
    '1::11::2::400',
]


class SnapshotFixture(object):
    """在临时目录写一个最小清洗快照。"""

    def __init__(self, ratings=None, users=None, movies=None):
        self.dir = _mkdtemp('cls-fixture-')
        _write(os.path.join(self.dir, 'users.dat'), users or USERS)
        _write(os.path.join(self.dir, 'movies.dat'), movies or MOVIES)
        _write(os.path.join(self.dir, 'ratings.dat'), ratings or RATINGS)

    def dataset(self):
        return common_features.Dataset(clean_dir=self.dir, rules=dict(RULES))

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def _write(path, lines):
    with open(path, 'w', encoding='latin-1') as f:
        for line in lines:
            f.write(line + '\n')


class TestLeakage(unittest.TestCase):

    def setUp(self):
        self.fx = SnapshotFixture()
        self.ds = self.fx.dataset()
        self.i_user_mean = self.ds.feature_names.index('user_mean')
        self.i_movie_mean = self.ds.feature_names.index('movie_mean')

    def tearDown(self):
        self.fx.close()

    def test_target_rating_not_in_own_features(self):
        """目标事件 Rating=5，但此前只有 1 分，用户均分应为 1.0。"""
        row, info = self.ds.build_row(1, 10, prediction_time=300)
        self.assertAlmostEqual(float(row[0, self.i_user_mean]), 1.0, places=5)
        self.assertEqual(info['features']['user_mean'], 1.0)
        self.assertEqual(info['features']['user_history_count'], 1)

    def test_same_second_events_excluded(self):
        """同一秒的另一条评分（1::11::4::300）也不得参与该秒事件的特征。"""
        X, y, split_codes, meta = self.ds.build_matrix()
        mask = (self.ds.u == 1) & (self.ds.m == 10) & (self.ds.ts == 300)
        idx = np.where(mask)[0][0]
        self.assertAlmostEqual(float(X[idx, self.i_user_mean]), 1.0, places=5)

    def test_future_events_do_not_change_past_features(self):
        before, _ = self.ds.build_row(1, 10, prediction_time=300)
        self.fx.close()
        self.fx = SnapshotFixture(ratings=RATINGS + ['1::10::1::600'])
        ds_after = self.fx.dataset()
        after, _ = ds_after.build_row(1, 10, prediction_time=300)
        self.assertAlmostEqual(float(before[0, self.i_user_mean]),
                               float(after[0, self.i_user_mean]), places=6)

    def test_default_basis_uses_train_snapshot(self):
        row, info = self.ds.build_row(2, 10)
        self.assertIn('train_snapshot', info['prediction_time_basis'])
        # 用户 2 在训练期只有 1 条 4 分评分
        self.assertAlmostEqual(float(row[0, self.i_user_mean]), 4.0, places=5)


class TestMissingAttributes(unittest.TestCase):

    def setUp(self):
        self.fx = SnapshotFixture()
        self.ds = self.fx.dataset()

    def tearDown(self):
        self.fx.close()

    def test_user_without_attrs_flagged(self):
        row, info = self.ds.build_row(3, 10, prediction_time=320)
        self.assertFalse(info['features']['has_user_attrs'])
        i_flag = self.ds.feature_names.index('has_user_attrs')
        i_unknown = self.ds.feature_names.index('occupation_unknown')
        i_age = self.ds.feature_names.index('age_ordinal')
        self.assertEqual(float(row[0, i_flag]), 0.0)
        self.assertEqual(float(row[0, i_unknown]), 1.0)
        self.assertEqual(float(row[0, i_age]), -1.0)

    def test_matrix_counts_missing_rows(self):
        X, y, split_codes, meta = self.ds.build_matrix()
        self.assertEqual(meta['missing_user_attrs_rows'], 2)


class TestUnknownIds(unittest.TestCase):

    def setUp(self):
        self.fx = SnapshotFixture()
        self.ds = self.fx.dataset()

    def tearDown(self):
        self.fx.close()

    def test_unknown_user(self):
        with self.assertRaises(schemas.ToolError) as ctx:
            self.ds.build_row(999, 10, prediction_time=300)
        self.assertEqual(ctx.exception.code, schemas.UNKNOWN_USER)

    def test_unknown_movie(self):
        with self.assertRaises(schemas.ToolError) as ctx:
            self.ds.build_row(1, 999, prediction_time=300)
        self.assertEqual(ctx.exception.code, schemas.UNKNOWN_MOVIE)

    def test_legacy_mapping_keeps_sub_code(self):
        err = schemas.ToolError(schemas.UNKNOWN_USER, '未知用户')
        legacy = err.to_legacy_error('PREDICT')
        self.assertEqual(legacy['code'], 'INVALID_REQUEST')
        self.assertEqual(legacy['detail']['sub_code'], 'UNKNOWN_USER')


class TestMatrixShape(unittest.TestCase):

    def setUp(self):
        self.fx = SnapshotFixture()
        self.ds = self.fx.dataset()
        self.X, self.y, self.split_codes, self.meta = self.ds.build_matrix()

    def tearDown(self):
        self.fx.close()

    def test_shape_and_labels(self):
        self.assertEqual(self.X.shape[0], 7)
        self.assertEqual(self.X.shape[1], len(self.ds.feature_names))
        self.assertEqual(int(self.y.sum()), 4)  # 5,4,5,4 为正类

    def test_split_counts(self):
        self.assertEqual(int((self.split_codes == 0).sum()), 2)
        self.assertEqual(int((self.split_codes == 1).sum()), 4)
        self.assertEqual(int((self.split_codes == 2).sum()), 1)

    def test_no_nan(self):
        self.assertFalse(np.isnan(self.X).any())


class TestModelMissing(unittest.TestCase):

    def test_model_not_found(self):
        if not HAVE_SKLEARN:
            self.skipTest('未安装 scikit-learn')
        from classification import predict
        empty = _mkdtemp('cls-artifacts-')
        try:
            with self.assertRaises(schemas.ToolError) as ctx:
                predict.load_model('gnb', artifacts_dir=empty)
            self.assertEqual(ctx.exception.code, schemas.MODEL_NOT_FOUND)
        finally:
            shutil.rmtree(empty, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
