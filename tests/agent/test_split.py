# -*- coding: utf-8 -*-
"""时间切分与标签口径测试（成员A，迭代二）。

覆盖验收清单 D-03（切分口径）与 C-03（Rating >= 4 标签）。
纯逻辑测试，不依赖本机是否存在清洗快照。
"""
import os
import sys
import unittest

import _paths  # noqa: F401  把 agent/src 与 agent/tools 加入 sys.path

from common import split


class TestSplitBoundary(unittest.TestCase):
    """D-03：三个子集互不重叠，边界归属正确。"""

    T1 = 974862386
    T2 = 976422054

    def test_epoch_equal_t1_is_train(self):
        self.assertEqual(split.split_of(self.T1, self.T1, self.T2), split.TRAIN)

    def test_one_second_before_t1_is_train(self):
        self.assertEqual(split.split_of(self.T1 - 1, self.T1, self.T2), split.TRAIN)

    def test_one_second_after_t1_is_validate(self):
        self.assertEqual(split.split_of(self.T1 + 1, self.T1, self.T2), split.VALIDATE)

    def test_epoch_equal_t2_is_validate(self):
        self.assertEqual(split.split_of(self.T2, self.T1, self.T2), split.VALIDATE)

    def test_one_second_after_t2_is_test(self):
        self.assertEqual(split.split_of(self.T2 + 1, self.T1, self.T2), split.TEST)

    def test_sets_do_not_overlap(self):
        seen = [split.split_of(ts, self.T1, self.T2) for ts in (self.T1, self.T1 + 1, self.T2 + 1)]
        self.assertEqual(seen, [split.TRAIN, split.VALIDATE, split.TEST])


class TestLabelRule(unittest.TestCase):
    """C-03：label = 1 当且仅当 Rating >= 4。"""

    T1 = 100
    T2 = 200

    def _summary(self, rows):
        return split.summarize_list(rows, self.T1, self.T2)

    def test_rating_three_is_negative(self):
        s = self._summary([(1, 10, 3, 50)])
        self.assertEqual(s['train']['positives'], 0)
        self.assertEqual(s['train']['records'], 1)

    def test_rating_four_and_five_are_positive(self):
        s = self._summary([(1, 10, 4, 50), (2, 11, 5, 60)])
        self.assertEqual(s['train']['positives'], 2)

    def test_positive_rate_matches_definition(self):
        s = self._summary([(1, 10, 1, 50), (2, 11, 4, 60), (3, 12, 5, 70), (4, 13, 2, 80)])
        self.assertAlmostEqual(s['train']['positive_rate'], 0.5)


class TestSummaryShape(unittest.TestCase):
    """统计结构完整，供结果封装与报告直接引用。"""

    T1 = 100
    T2 = 200

    def test_counts_and_unique_sets(self):
        rows = [
            (1, 10, 5, 50),    # train
            (1, 11, 4, 90),    # train, same user
            (2, 10, 3, 150),   # validate
            (3, 12, 5, 250),   # test
        ]
        s = split.summarize_list(rows, self.T1, self.T2)
        self.assertEqual(s['train']['records'], 2)
        self.assertEqual(s['validate']['records'], 1)
        self.assertEqual(s['test']['records'], 1)
        self.assertEqual(s['train']['users'], 1)
        self.assertEqual(s['train']['movies'], 2)
        self.assertEqual(s['_meta']['records'], 4)
        self.assertEqual(s['_meta']['invalid_rows'], 0)

    def test_time_range_per_split(self):
        rows = [(1, 10, 5, 50), (1, 11, 4, 90), (2, 10, 3, 150)]
        s = split.summarize_list(rows, self.T1, self.T2)
        self.assertEqual(s['train']['time_min'], 50)
        self.assertEqual(s['train']['time_max'], 90)
        self.assertEqual(s['validate']['time_min'], 150)
        self.assertEqual(s['validate']['time_max'], 150)

    def test_ratios_sum_to_one(self):
        rows = [(1, 10, 5, 50), (2, 11, 1, 150), (3, 12, 4, 250)]
        s = split.summarize_list(rows, self.T1, self.T2)
        total = sum(s[name]['ratio'] for name in split.SPLITS)
        self.assertAlmostEqual(total, 1.0, places=5)


class TestDataUnavailable(unittest.TestCase):
    """D-01/C-06：快照缺失时抛明确异常，不返回占位统计。"""

    def test_missing_snapshot_raises(self):
        missing = os.path.join(_paths.REPO_DIR, 'data', '__not_exists__')
        with self.assertRaises(split.DataUnavailable):
            split.summarize(clean=missing, check_unique=False)


class TestRulesSource(unittest.TestCase):
    """T1/T2 只从 rules.json 读取，不在代码里写死日期。"""

    def test_time_bounds_from_rules(self):
        t1, t2 = split.time_bounds()
        self.assertIsInstance(t1, int)
        self.assertIsInstance(t2, int)
        self.assertLess(t1, t2)

    def test_split_version_declared(self):
        self.assertEqual(split.SPLIT_VERSION, 'split-v1')


if __name__ == '__main__':
    unittest.main()
