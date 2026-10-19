# -*- coding: utf-8 -*-
"""阈值选择与评价口径测试（成员A，迭代二）。

阈值策略：验证期最大化 F1，并要求预测正类比例不超过真实正类比例的 1.10 倍。
若不加约束，朴素贝叶斯会退化到「几乎全判正类」（实测阈值 0.022、判定率 90%），
因此这里专门验证约束确实生效。
"""
import unittest

import _paths  # noqa: F401

import numpy as np

HAVE_SKLEARN = True
try:
    import sklearn  # noqa: F401
except ImportError:
    HAVE_SKLEARN = False

if HAVE_SKLEARN:
    from classification import modeling


@unittest.skipUnless(HAVE_SKLEARN, '未安装 scikit-learn')
class TestThresholdPolicy(unittest.TestCase):

    def test_separable_case_returns_sane_threshold(self):
        y = np.array([1, 1, 0, 0], dtype=np.int8)
        s = np.array([0.9, 0.8, 0.2, 0.1])
        threshold, f1 = modeling.best_threshold(y, s)
        self.assertAlmostEqual(f1, 1.0, places=6)
        # 0.8 与 0.2 之间的任何阈值都能完全分开；取第一个 F1 最优点即可
        self.assertGreaterEqual(threshold, 0.2)
        self.assertAlmostEqual(float((s >= threshold).mean()), 0.5)

    def test_positive_rate_constraint_is_applied(self):
        # 正类率 50%，但 F1 最优点会判 3/4 为正类；约束到 50% 后必须收敛
        y = np.array([1, 0, 1, 0], dtype=np.int8)
        s = np.array([0.9, 0.85, 0.8, 0.1])
        unconstrained, _ = modeling.best_threshold(y, s)
        self.assertGreater(float((s >= unconstrained).mean()), 0.5)
        constrained, _ = modeling.best_threshold(y, s, max_positive_rate=0.5)
        self.assertLessEqual(float((s >= constrained).mean()), 0.5 + 1e-9)

    def test_all_negative_labels_do_not_crash(self):
        y = np.zeros(5, dtype=np.int8)
        s = np.array([0.5, 0.4, 0.3, 0.2, 0.1])
        threshold, f1 = modeling.best_threshold(y, s, max_positive_rate=0.2)
        self.assertIsInstance(threshold, float)


@unittest.skipUnless(HAVE_SKLEARN, '未安装 scikit-learn')
class TestEvaluationShape(unittest.TestCase):

    def test_metrics_include_confusion_and_rate(self):
        from sklearn.naive_bayes import GaussianNB
        X = np.array([[0.0], [0.1], [0.9], [1.0]])
        y = np.array([0, 0, 1, 1])
        model = GaussianNB().fit(X, y)
        metrics, score = modeling.evaluate(model, X, y, threshold=0.5)
        for key in ('roc_auc', 'pr_auc', 'precision', 'recall', 'f1',
                    'accuracy', 'confusion_matrix', 'predicted_positive_rate'):
            self.assertIn(key, metrics)
        self.assertEqual(len(score), 4)
        self.assertEqual(metrics['threshold'], 0.5)


if __name__ == '__main__':
    unittest.main()
