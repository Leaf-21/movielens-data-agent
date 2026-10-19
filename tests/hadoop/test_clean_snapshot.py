# -*- coding: utf-8 -*-
"""清洗快照完整性测试（成员A，迭代二）。

快照文件不进 Git（.gitignore 已排除 *.dat），因此本测试在数据缺失时
自动 skip，而不是失败；有数据时校验行数、切分规模、标签口径与唯一性，
对应验收清单 D-01（数据版本）、D-04（切分记录数）。

数据目录由 common.split 的默认规则决定（data/<output_version>），
也可用 ML_CLEAN_DIR 指向其他位置。
"""
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_DIR = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_REPO_DIR, 'agent', 'tools'))

from common import split  # noqa: E402


def _snapshot_ready():
    try:
        return os.path.exists(split.ratings_path())
    except split.DataUnavailable:
        return False


@unittest.skipUnless(_snapshot_ready(), '清洗快照不在本机（data/<output_version>），跳过')
class TestCleanSnapshot(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.stats = split.summarize(check_unique=True)
        cls.rules = split.load_rules()

    def test_record_count_matches_iteration_one(self):
        self.assertEqual(self.stats['_meta']['records'], 996113)

    def test_no_invalid_rows(self):
        self.assertEqual(self.stats['_meta']['invalid_rows'], 0)

    def test_no_duplicate_pairs(self):
        self.assertEqual(self.stats['_meta']['duplicate_pairs'], 0)

    def test_split_counts_match_registered_expectation(self):
        expected = self.rules['time']['expected_split']
        self.assertEqual(self.stats['train']['records'], expected['train_count'])
        self.assertEqual(self.stats['validate']['records'], expected['validate_count'])
        self.assertEqual(self.stats['test']['records'], expected['test_count'])

    def test_every_split_has_both_classes(self):
        for name in split.SPLITS:
            s = self.stats[name]
            self.assertGreater(s['positives'], 0)
            self.assertLess(s['positives'], s['records'])

    def test_split_windows_do_not_overlap(self):
        t1, t2 = split.time_bounds(self.rules)
        self.assertLessEqual(self.stats['train']['time_max'], t1)
        self.assertGreater(self.stats['validate']['time_min'], t1)
        self.assertLessEqual(self.stats['validate']['time_max'], t2)
        self.assertGreater(self.stats['test']['time_min'], t2)

    def test_three_tables_present(self):
        files = self.stats['source']['files']
        self.assertEqual(files['ratings.dat']['lines'], 996113)
        self.assertEqual(files['movies.dat']['lines'], 3883)
        self.assertEqual(files['users.dat']['lines'], 6025)


if __name__ == '__main__':
    unittest.main()
