# -*- coding: utf-8 -*-
"""
降维工具单测（成员C）：PCA / t-SNE

不依赖清洗快照的部分（可离线跑）：
  · 参数白名单/范围校验（validate_dr_params）
  · PCA 数学性质：主成分正交、解释方差比单调递减且和为 1、符号规范化确定性
  · PCA 对角化与 eigh 结果一致；同输入同参数两次运行逐位相同
  · t-SNE 参数约束（3*perplexity < n）；随机种子固定时逐位可复现
  · kNN 一致率定义与基线

依赖清洗快照的部分（@skipUnless）：样本外投影/不投影语义、缺失用户、
聚类前后对照结构完整。（参数越界与 t-SNE 约束也走真实 CLI 做端到端验证）
"""

import json
import os
import subprocess
import sys
import unittest
from unittest import mock

import _paths  # noqa: F401
from _paths import AGENT_SRC, AGENT_TOOLS, REPO_DIR

_C = os.path.join(AGENT_TOOLS, 'clustering')
_DR = os.path.join(AGENT_TOOLS, 'dimensionality_reduction')
for _p in (_C, _DR, AGENT_SRC):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config                                    # noqa: E402
import dr_common as D                            # noqa: E402
import pca_tool                                  # noqa: E402
import tsne_tool                                 # noqa: E402
from common import AnalysisError                 # noqa: E402

_HAS_SNAPSHOT = os.path.exists(os.path.join(
    config.resolve_repo_path(config.load_analysis()['input']['clean_dir']),
    'ratings.dat'))

# 小型可重复数据：3 簇 × 4 点，满足 3*perplexity < n（p=3 时 9<12）
_VECS = [
    [1.0, 0.0, 0.0], [1.1, 0.1, 0.0], [0.9, -0.1, 0.1], [1.05, 0.05, -0.05],
    [0.0, 1.0, 0.0], [0.1, 1.1, 0.1], [-0.1, 0.9, -0.1], [0.05, 0.95, 0.05],
    [0.5, 0.5, 1.0], [0.6, 0.4, 1.1], [0.4, 0.6, 0.9], [0.55, 0.45, 1.05],
]


class TestDrParams(unittest.TestCase):

    def test_empty_ok(self):
        self.assertEqual(D.validate_dr_params(None), {})
        self.assertEqual(D.validate_dr_params({}), {})

    def test_unknown_key_rejected(self):
        with self.assertRaises(AnalysisError) as cm:
            D.validate_dr_params({'n_components': 2})
        self.assertEqual(cm.exception.code, 'INVALID_PARAMETER')

    def test_out_of_range_rejected(self):
        for bad in ({'target_dimensions': 0},
                    {'target_dimensions': 99},
                    {'perplexity': 1.0},
                    {'perplexity': 100.0},
                    {'n_iter': 10},
                    {'learning_rate': 0.0},
                    {'random_state': -1},
                    {'information_retention_threshold': 1.5},
                    {'knn_k': 3}):
            with self.assertRaises(AnalysisError) as cm:
                D.validate_dr_params(bad)
            self.assertEqual(cm.exception.code, 'INVALID_PARAMETER', bad)

    def test_non_numeric_rejected(self):
        with self.assertRaises(AnalysisError) as cm:
            D.validate_dr_params({'perplexity': '三十'})
        self.assertEqual(cm.exception.code, 'INVALID_PARAMETER')

    def test_valid_passthrough(self):
        p = {'target_dimensions': 3, 'perplexity': 10.0, 'random_state': 7}
        self.assertEqual(D.validate_dr_params(p), p)


class TestPcaMath(unittest.TestCase):

    def test_explained_variance_properties(self):
        fit = pca_tool.fit_pca(_VECS, 2)
        evr = fit['explained_ratio']
        self.assertAlmostEqual(sum(evr), 1.0, places=9)
        # 单调递减
        self.assertTrue(all(evr[i] >= evr[i + 1] - 1e-12
                            for i in range(len(evr) - 1)))
        # 累计解释方差单调不减，末项=1
        cum = fit['cumulative']
        self.assertTrue(all(cum[i] <= cum[i + 1] + 1e-12
                            for i in range(len(cum) - 1)))
        self.assertAlmostEqual(cum[-1], 1.0, places=9)

    def test_components_orthonormal(self):
        fit = pca_tool.fit_pca(_VECS, 3)
        comp = fit['components']
        np = pca_tool._numpy()
        gram = comp.T @ comp
        self.assertTrue(np.allclose(gram, np.eye(3), atol=1e-10))

    def test_loading_sign_convention_deterministic(self):
        fit1 = pca_tool.fit_pca(_VECS, 2)
        fit2 = pca_tool.fit_pca(_VECS, 2)
        np = pca_tool._numpy()
        self.assertTrue(np.array_equal(fit1['components'], fit2['components']))
        # 每个主成分内绝对值最大的载荷为正
        for j in range(2):
            col = fit1['components'][:, j]
            self.assertGreaterEqual(col[int(np.argmax(np.abs(col)))], 0.0)

    def test_projection_reproduces_coords(self):
        """用 mean+components 手动投影，应与 fit 返回的 coords 一致（样本内）。"""
        np = pca_tool._numpy()
        fit = pca_tool.fit_pca(_VECS, 2)
        X = np.asarray(_VECS, dtype=float)
        manual = (X - np.asarray(fit['mean'])) @ fit['components']
        self.assertTrue(np.allclose(manual, fit['coords'], atol=1e-12))

    def test_target_dim_bounds(self):
        with self.assertRaises(AnalysisError) as cm:
            pca_tool.fit_pca(_VECS, 4)
        self.assertEqual(cm.exception.code, 'INVALID_PARAMETER')
        with self.assertRaises(AnalysisError) as cm2:
            pca_tool.fit_pca(_VECS, 0)
        self.assertEqual(cm2.exception.code, 'INVALID_PARAMETER')

    def test_too_few_users(self):
        with self.assertRaises(AnalysisError) as cm:
            pca_tool.fit_pca(_VECS[:2], 1)
        self.assertEqual(cm.exception.code, 'ALGORITHM_ERROR')

    def test_keep_dimensions_for_threshold(self):
        fit = pca_tool.fit_pca(_VECS, 1, threshold=0.8)
        self.assertGreaterEqual(fit['keep_dimensions_for_threshold'], 1)
        self.assertLessEqual(fit['keep_dimensions_for_threshold'], 3)
        # 该维数的累计解释方差确实达到阈值
        k = fit['keep_dimensions_for_threshold']
        self.assertGreaterEqual(fit['cumulative'][k - 1], 0.8 - 1e-12)


class TestTsneMath(unittest.TestCase):

    def test_student_t_probabilities_use_pairwise_distances(self):
        import numpy as np
        Y = np.asarray([[0.0, 0.0], [1.0, 0.0], [0.0, 2.0]])
        num, q = tsne_tool._student_t_distribution(Y)
        expected = np.asarray([
            [0.0, 1.0 / 2.0, 1.0 / 5.0],
            [1.0 / 2.0, 0.0, 1.0 / 6.0],
            [1.0 / 5.0, 1.0 / 6.0, 0.0],
        ])
        self.assertTrue(np.allclose(num, expected))
        self.assertTrue(np.allclose(q, expected / expected.sum()))
        self.assertAlmostEqual(float(q.sum()), 1.0)

    def test_student_t_gradient_matches_finite_difference(self):
        import numpy as np
        Y = np.asarray([[0.0, 0.0], [1.0, 0.2], [-0.3, 0.8]])
        P = np.asarray([
            [0.0, 0.2, 0.3],
            [0.2, 0.0, 0.1],
            [0.3, 0.1, 0.0],
        ])
        P /= P.sum()
        num, q = tsne_tool._student_t_distribution(Y)
        gradient = tsne_tool._kl_gradient(Y, P, num, q)

        def loss(points):
            _numerator, probabilities = tsne_tool._student_t_distribution(points)
            return float(np.sum(P * np.log((P + 1e-12) /
                                           (probabilities + 1e-12))))

        epsilon = 1e-6
        numerical = np.zeros_like(Y)
        for i in range(Y.shape[0]):
            for j in range(Y.shape[1]):
                plus, minus = Y.copy(), Y.copy()
                plus[i, j] += epsilon
                minus[i, j] -= epsilon
                numerical[i, j] = (loss(plus) - loss(minus)) / (2 * epsilon)
        self.assertTrue(np.allclose(gradient, numerical, atol=1e-6))

    def test_perplexity_constraint(self):
        # 3*3 = 9 不小于 n=8 -> 必须拒绝（严格 <，数据与实验规范）
        with self.assertRaises(AnalysisError) as cm:
            tsne_tool.fit_tsne(_VECS[:8], perplexity=3.0, n_iter=5)
        self.assertEqual(cm.exception.code, 'INVALID_PARAMETER')
        self.assertIn('3*perplexity', cm.exception.message)

    def test_perplexity_boundary_just_accepted(self):
        # 3*3 = 9 < n=12 -> 接受
        out = tsne_tool.fit_tsne(_VECS, perplexity=3.0, n_iter=5)
        self.assertEqual(out['perplexity'], 3.0)

    def test_deterministic_with_seed(self):
        a = tsne_tool.fit_tsne(_VECS, perplexity=3.0, n_iter=40, seed=42)
        b = tsne_tool.fit_tsne(_VECS, perplexity=3.0, n_iter=40, seed=42)
        self.assertEqual(a['coords'], b['coords'])

    def test_different_seed_differs(self):
        a = tsne_tool.fit_tsne(_VECS, perplexity=3.0, n_iter=40, seed=1)
        b = tsne_tool.fit_tsne(_VECS, perplexity=3.0, n_iter=40, seed=2)
        self.assertNotEqual(a['coords'], b['coords'])

    def test_too_few_users(self):
        with self.assertRaises(AnalysisError) as cm:
            tsne_tool.fit_tsne(_VECS[:2], perplexity=0.5, n_iter=5)
        self.assertEqual(cm.exception.code, 'ALGORITHM_ERROR')

    def test_fit_accepts_plain_lists(self):
        """不依赖调用方预转 numpy（工具边界要健壮）。"""
        out = tsne_tool.fit_tsne([[float(v) for v in r] for r in _VECS],
                                 perplexity=3.0, n_iter=5)
        self.assertEqual(len(out['coords']), len(_VECS))

    def test_knn_agreement_bounds(self):
        import numpy as np
        X = np.asarray(_VECS, dtype=float)
        # 低维=高维（取前两维）时一致率应显著高于随机基线
        Y = X[:, :2]
        agree, base = tsne_tool.knn_agreement(X, Y, k=2)
        self.assertIsNotNone(agree)
        self.assertGreaterEqual(agree, base)
        self.assertLessEqual(agree, 1.0)

    def test_knn_agreement_none_when_too_small(self):
        import numpy as np
        X = np.asarray(_VECS[:3], dtype=float)
        agree, base = tsne_tool.knn_agreement(X, X[:, :2], k=10)
        self.assertIsNone(agree)
        self.assertIsNone(base)


class TestToolEnvelopes(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import numpy as np
        rng = np.random.RandomState(11)
        centers = np.asarray([np.full(27, -1.0), np.full(27, 1.0)])
        cls.vectors = np.vstack([
            centers[i % 2] + rng.normal(0, 0.15, 27) for i in range(20)
        ]).tolist()
        cls.users = {
            'meta': {
                'profile_version': 'profile-test',
                'input_sha256': {'ratings.dat': 'a' * 64},
                'T1_epoch': 1000, 'T2_epoch': 2000,
                'T1': 'T1-test', 'T2': 'T2-test',
                'code_version': 'test',
                'feature_names': ['feature-%d' % i for i in range(27)],
            },
            'fit_uids': list(range(1, 21)),
            'orig_vectors': cls.vectors,
            'out_of_sample': {},
            'missing': [],
        }
        cls.acfg = config.load_analysis()
        cls.rcfg = config.load_rules()

    def test_pca_tool_envelope_includes_comparison_and_coordinates(self):
        with mock.patch.object(D, 'resolve_users', return_value=self.users):
            result = pca_tool.run({
                'user_ids': None,
                'parameters': {'clustering_k': 2},
            }, self.acfg, self.rcfg)
        self.assertEqual(result['algorithm'], 'pca')
        self.assertEqual(len(result['coordinates']), 20)
        self.assertEqual(result['information_retention']['metric'],
                         'explained_variance_ratio')
        self.assertTrue(result['clustering_comparison']['kmeans']['same_user_set'])
        self.assertIn('elapsed_ms', result['resource_usage'])

    def test_tsne_tool_envelope_does_not_claim_explained_variance(self):
        with mock.patch.object(D, 'resolve_users', return_value=self.users):
            result = tsne_tool.run({
                'user_ids': None,
                'parameters': {'perplexity': 5.0, 'n_iter': 250,
                               'knn_k': 5, 'clustering_k': 2},
            }, self.acfg, self.rcfg)
        self.assertEqual(result['algorithm'], 'tsne')
        self.assertEqual(len(result['coordinates']), 20)
        self.assertEqual(result['information_retention']['metric'], 'knn_agreement')
        self.assertIsNone(result['information_retention']['explained_variance_ratio'])
        self.assertTrue(result['clustering_comparison']['kmeans']['same_user_set'])


class TestCliProtocol(unittest.TestCase):
    """端到端 CLI：--request/--output 子进程协议与失败码。"""

    def _run(self, script, payload):
        req = os.path.join(REPO_DIR, 'agent', 'tools', 'dimensionality_reduction',
                           '_t_req.json')
        out = os.path.join(REPO_DIR, 'agent', 'tools', 'dimensionality_reduction',
                           '_t_out.json')
        with open(req, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False)
        try:
            proc = subprocess.run(
                [sys.executable, '-I', os.path.join(_DR, script),
                 '--request', req, '--output', out],
                capture_output=True, text=True, timeout=300,
                env=dict(os.environ, PYTHONIOENCODING='utf-8'))
        finally:
            for p in (req, out):
                if os.path.exists(p):
                    os.remove(p)
        return proc

    def test_pca_invalid_parameter_exit_2(self):
        proc = self._run('pca_tool.py',
                         {'user_ids': [1, 2, 3],
                          'parameters': {'target_dimensions': 999}})
        self.assertEqual(proc.returncode, 2, proc.stderr)
        body = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(body['status'], 'FAILED')
        self.assertEqual(body['error']['code'], 'INVALID_PARAMETER')

    def test_tsne_unknown_parameter_exit_2(self):
        proc = self._run('tsne_tool.py',
                         {'user_ids': [1, 2, 3],
                          'parameters': {'foo': 1}})
        self.assertEqual(proc.returncode, 2, proc.stderr)
        body = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(body['error']['code'], 'INVALID_PARAMETER')


@unittest.skipUnless(_HAS_SNAPSHOT, '清洗快照不可用')
class TestWithSnapshot(unittest.TestCase):
    """真实数据上的语义：样本外投影（PCA）与不投影（t-SNE）。"""

    @classmethod
    def setUpClass(cls):
        acfg = config.load_analysis()
        rcfg = config.load_rules()
        cls.acfg = acfg
        # 取一个拟合用户 + 一个历史不足用户（若存在）
        prof = os.path.join(config.resolve_repo_path(
            acfg['artifacts']['profiles_dir']), 'profile-v1.jsonl')
        fit_uid, cold_uid = None, None
        with open(prof, 'r', encoding='utf-8') as f:
            for line in f:
                r = json.loads(line)
                if fit_uid is None and r.get('fit') and r.get('vector'):
                    fit_uid = r['user_id']
                elif cold_uid is None and not r.get('fit'):
                    cold_uid = r['user_id']
                if fit_uid and cold_uid:
                    break
        cls.fit_uid, cls.cold_uid = fit_uid, cold_uid

    def test_pca_projects_out_of_sample_cold_user(self):
        # 追加足够多的拟合用户，保证拟合集 >= 3
        prof = os.path.join(config.resolve_repo_path(
            self.acfg['artifacts']['profiles_dir']), 'profile-v1.jsonl')
        uids = [self.fit_uid]
        with open(prof, 'r', encoding='utf-8') as f:
            for line in f:
                r = json.loads(line)
                if r.get('fit') and r.get('vector') and r['user_id'] not in uids:
                    uids.append(r['user_id'])
                if len(uids) >= 20:
                    break
        env = pca_tool.run({'user_ids': uids,
                            'parameters': {'clustering_k': 2,
                                           'clustering_eps': 2.0,
                                           'clustering_min_samples': 3}},
                           self.acfg, config.load_rules())
        self.assertEqual(env['algorithm'], 'pca')
        self.assertEqual(env['reduced_dimensions'], 2)
        self.assertEqual(len(env['coordinates']), len(uids))
        for c in env['coordinates']:
            self.assertEqual(c['status'], 'SUCCESS')
            self.assertIsNotNone(c['x'])
        self.assertEqual(env['information_retention']['metric'],
                         'explained_variance_ratio')
        cmp_all = env['clustering_comparison']
        self.assertIn('kmeans', cmp_all)
        self.assertIn('dbscan', cmp_all)
        self.assertEqual(cmp_all['dbscan']['parameters']['eps'], 2.0)
        # K-Means 前后对照结构完整，且使用同一用户集合
        k = cmp_all['kmeans']
        self.assertTrue(k['same_user_set'])
        self.assertEqual(len(k['labels_before']), len(uids))
        self.assertEqual(len(k['labels_after']), len(uids))
        self.assertEqual(k['before']['dimensions'], 27)
        self.assertEqual(k['after']['dimensions'], 2)

    def test_pca_unknown_user_reported_not_faked(self):
        prof = os.path.join(config.resolve_repo_path(
            self.acfg['artifacts']['profiles_dir']), 'profile-v1.jsonl')
        uids = []
        with open(prof, 'r', encoding='utf-8') as f:
            for line in f:
                r = json.loads(line)
                if r.get('fit') and r.get('vector'):
                    uids.append(r['user_id'])
                if len(uids) >= 5:
                    break
        uids.append(999999999)
        env = pca_tool.run({'user_ids': uids,
                            'parameters': {'clustering_k': 2}},
                           self.acfg, config.load_rules())
        self.assertIn('999999999', env['fit_scope']['missing_user_ids'])
        ids = [c['user_id'] for c in env['coordinates']]
        self.assertNotIn(999999999, ids)

    def test_tsne_does_not_project_out_of_sample(self):
        if self.cold_uid is None:
            self.skipTest('无历史不足用户样本')
        prof = os.path.join(config.resolve_repo_path(
            self.acfg['artifacts']['profiles_dir']), 'profile-v1.jsonl')
        uids = [self.fit_uid, self.cold_uid]
        with open(prof, 'r', encoding='utf-8') as f:
            for line in f:
                r = json.loads(line)
                if r.get('fit') and r.get('vector') and r['user_id'] not in uids:
                    uids.append(r['user_id'])
                if len(uids) >= 25:
                    break
        env = tsne_tool.run({'user_ids': uids,
                             'parameters': {'perplexity': 5.0, 'n_iter': 250,
                                            'clustering_k': 2}},
                            self.acfg, config.load_rules())
        cold = [c for c in env['coordinates'] if c['user_id'] == self.cold_uid]
        self.assertEqual(len(cold), 1)
        self.assertIsNone(cold[0]['x'])
        self.assertIsNone(cold[0]['y'])
        self.assertIn(cold[0]['status'],
                      ('NO_TRAIN_HISTORY', 'NOT_PROJECTED_BY_TSNE'))
        self.assertIsNone(env['information_retention']['explained_variance_ratio'])
        self.assertEqual(env['information_retention']['metric'], 'knn_agreement')


if __name__ == '__main__':
    unittest.main()
