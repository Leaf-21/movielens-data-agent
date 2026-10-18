# -*- coding: utf-8 -*-
"""聚类指标单测：已知小例手算对账 + null 语义（簇数<2 / 质心重合）。"""

import math
import os
import sys
import unittest

import _paths  # noqa: F401
from _paths import AGENT_TOOLS

_C = os.path.join(AGENT_TOOLS, 'clustering')
if _C not in sys.path:
    sys.path.insert(0, _C)

import metrics as M  # noqa: E402


class TestBasics(unittest.TestCase):

    def test_euclid_equals_math_dist(self):
        self.assertEqual(M.euclid([0, 0], [3, 4]), 5.0)
        self.assertEqual(M.euclid([1, 2, 2], [1, 2, 2]), 0.0)

    def test_centroid(self):
        self.assertEqual(M.centroid([]), None)
        self.assertEqual(M.centroid([[0, 0], [2, 4]]), [1.0, 2.0])
        self.assertAlmostEqual(
            M.centroid([[0, 0], [2, 0], [4, 6]])[1], 2.0)

    def test_sse_skips_noise(self):
        vectors = [[0, 0], [2, 0], [10, 0], [100, 100]]
        labels = [0, 0, 1, -1]
        cent = [[1, 0], [10, 0], None]
        # 簇0: 1+1；簇1: 0；噪声不计
        self.assertAlmostEqual(M.sse(vectors, labels, cent), 2.0)


class TestSample(unittest.TestCase):

    def test_full_when_size_ge_n(self):
        self.assertEqual(M.sample_indices(5, 5, 42), [0, 1, 2, 3, 4])
        self.assertEqual(M.sample_indices(3, 100, 42), [0, 1, 2])

    def test_deterministic_and_sorted(self):
        a = M.sample_indices(100, 20, 42)
        b = M.sample_indices(100, 20, 42)
        self.assertEqual(a, b)
        self.assertEqual(len(a), 20)
        self.assertEqual(a, sorted(a))
        self.assertEqual(len(set(a)), 20)

    def test_seed_formula_stability(self):
        # 口径登记依赖该公式（seed*7919+size），改动即结果版本变化
        import random
        rng = random.Random(42 * 7919 + 20)
        self.assertEqual(M.sample_indices(100, 20, 42),
                         sorted(rng.sample(range(100), 20)))


class TestSilhouette(unittest.TestCase):

    def test_two_clean_blobs_positive(self):
        vectors = [[0, 0], [0.1, 0], [0, 0.1], [10, 10], [10.1, 10], [10, 10.1]]
        labels = [0, 0, 0, 1, 1, 1]
        overall, per = M.silhouette(vectors, labels)
        self.assertGreater(overall, 0.9)
        self.assertEqual(sorted(per), [0, 1])
        for v in per.values():
            self.assertGreater(v, 0.8)

    def test_single_cluster_returns_none(self):
        overall, per = M.silhouette([[0, 0], [1, 0]], [0, 0])
        self.assertIsNone(overall)
        self.assertEqual(per, {})

    def test_singleton_convention_zero(self):
        vectors = [[0, 0], [0, 1], [100, 100]]
        labels = [0, 0, 1]
        overall, per = M.silhouette(vectors, labels)
        self.assertEqual(per[1], 0.0)  # 孤立样本 s 记 0（口径已登记）

    def test_noise_excluded(self):
        # 噪声剔除后只剩 1 个簇 -> 如实 null，不拿单簇伪造评分
        vectors = [[0, 0], [0, 1], [50, 50], [0, 2], [1, 0]]
        labels = [0, 0, -1, 0, 0]
        overall, per = M.silhouette(vectors, labels)
        self.assertIsNone(overall)
        self.assertEqual(per, {})
        # 两个真簇 + 噪声：噪声点不影响均值口径（不参与 a/b）
        vectors2 = [[0, 0], [0, 1], [9, 9], [9, 10], [50, 50]]
        labels2 = [0, 0, 1, 1, -1]
        overall2, per2 = M.silhouette(vectors2, labels2)
        self.assertEqual(sorted(per2), [0, 1])
        self.assertGreater(overall2, 0.8)

    def test_sampled_matches_full_when_sample_is_all(self):
        vectors = [[0, 0], [0.1, 0], [10, 10], [10.1, 10]]
        labels = [0, 0, 1, 1]
        full, _ = M.silhouette(vectors, labels)
        sampled = M.silhouette_sampled(vectors, labels,
                                       list(range(len(vectors))))
        self.assertAlmostEqual(full, sampled)

    def test_sampled_single_cluster_none(self):
        self.assertIsNone(M.silhouette_sampled([[0], [1]], [0, 0], [0]))


class TestDaviesBouldin(unittest.TestCase):

    def test_symmetric_two_clusters_positive(self):
        vectors = [[-1, 0], [1, 0], [9, 0], [11, 0]]
        labels = [0, 0, 1, 1]
        cent = [[0, 0], [10, 0]]
        dbi = M.davies_bouldin(vectors, labels, cent)
        # 手算：两簇散度同为1，质心距10 -> R=(1+1)/10=0.2，均值0.2
        self.assertAlmostEqual(dbi, 0.2)

    def test_single_cluster_none(self):
        self.assertIsNone(M.davies_bouldin([[0], [1]], [0, 0], [[0.5]]))

    def test_coincident_centroids_none(self):
        vectors = [[0], [1]]
        self.assertIsNone(M.davies_bouldin(vectors, [0, 1], [[5], [5]]))

    def test_null_centroid_none(self):
        self.assertIsNone(M.davies_bouldin([[0], [1]], [0, 1], [[0], None]))


class TestDefinitions(unittest.TestCase):

    def test_definitions_registered(self):
        self.assertIn('silhouette', M.METRIC_DEFINITIONS)
        self.assertIn('轮廓系数', M.METRIC_DEFINITIONS['silhouette'])


if __name__ == '__main__':
    unittest.main()
