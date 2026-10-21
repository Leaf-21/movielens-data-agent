#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
t-SNE 降维工具（dimensionality_reduction_tsne，成员C）

口径（任务书 §2/§3，数据与实验规范 §五）：
  · 输入：profile-v1 画像 z-score 向量（27 维，训练期 Timestamp<=T1）；
  · 拟合集：画像拟合用户（status=OK）；历史不足用户**不投影**：
    t-SNE 是非参数嵌入，没有可复用的"投影矩阵"，不能把新点可靠地
    放到同一张图上（直接给出错误坐标本质是伪造），
    故坐标记为 null + status=NOT_PROJECTED_BY_TSNE；
    无训练记录用户同为 null；
  · 算法：标准 t-SNE（t-SNE paper, van der Maaten & Hinton 2008）：
      高维条件概率 P_{j|i} ∝ exp(-||x_i-x_j||^2 / 2σ_i^2)，σ_i 二分搜索到
      目标 perplexity；对称化 P_{ij}=(P_{j|i}+P_{i|j})/(2n)；
      低维学生 t 分布 q_{ij} ∝ (1+||y_i-y_j||^2)^-1；
      早期夸张 early_exaggeration 提升簇分离；动量 + 学习率梯度下降；
      固定 random_state 保证同机可复现（旋转/翻转不保证跨实现一致，已如实说明）；
  · 信息保留：不报告解释方差（不适用，记 null）；报告"高维 vs 低维 K 近邻
    一致率"作为**结构保留的相对指标**（经验参考，不构成算法优劣的绝对证据）；
  · 聚类对照：低维空间 K-Means（与 PCA 同一实现/k），高维空间对照
    直接复用聚类工具的 K-Means 结果（同一用户集合）。

独立运行：
  python3 -I agent/tools/dimensionality_reduction/tsne_tool.py \
      --user 1000 --user 2000 [--perplexity 30] [--k 6]

子进程协议（成员B调度器）：
  python3 -I <file> --request req.json --output out.json
"""

import argparse
import json
import os
import sys
import time
import tracemalloc

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS_DIR = os.path.dirname(_HERE)
_CLUSTERING_DIR = os.path.join(_TOOLS_DIR, 'clustering')
_SRC_DIR = os.path.join(os.path.dirname(_TOOLS_DIR), 'src')
# 顺序关键：agent/tools 下的 common 是成员A的数据包（无 AnalysisError），
# 必须先找到 clustering/common.py，故 agent/tools 不入 path，_HERE 放最后。
if _TOOLS_DIR in sys.path:
    sys.path.remove(_TOOLS_DIR)
for _p in (_CLUSTERING_DIR, _SRC_DIR, _HERE):
    if _p in sys.path:
        sys.path.remove(_p)
    sys.path.insert(0, _p)

import config                                    # noqa: E402
from common import AnalysisError                 # noqa: E402
import dr_common as D                            # noqa: E402

METHOD = 'tsne'

ALGORITHM_NAME = 't-Distributed Stochastic Neighbor Embedding (van der Maaten & Hinton 2008)'
ALGORITHM_SOURCE = ('van der Maaten & Hinton, "Visualizing Data using t-SNE", JMLR 2008；'
                    '课程 PPT 章节/页码尚未核实')

LIMITATIONS = list(D.TSNE_LIMITATIONS) + [
    '历史不足用户不进行样本外投影：t-SNE 没有可复用投影矩阵，强行给出坐标为伪造；'
    '这类用户坐标为 null（status=NOT_PROJECTED_BY_TSNE）。',
    'kNN 一致率是结构保留的**相对参考指标**（同一数据高维近邻在低维是否仍近邻），'
    '不构成 t-SNE 优于/劣于 PCA 的绝对证据，需结合聚类指标综合判断。',
]

def _numpy():
    try:
        import numpy as np
    except ImportError:   # pragma: no cover
        raise AnalysisError('ALGORITHM_ERROR',
                            't-SNE 需要 numpy（requirements.txt 已登记）：pip install -r requirements.txt')
    return np


def _pairwise_sqdist(X):
    np = _numpy()
    s = (X * X).sum(axis=1)
    d2 = s[:, None] + s[None, :] - 2.0 * (X @ X.T)
    np.maximum(d2, 0.0, out=d2)
    np.fill_diagonal(d2, 0.0)
    return d2


def _student_t_distribution(Y):
    """Return Student-t numerators and their normalized low-dimensional probabilities."""
    np = _numpy()
    num = 1.0 / (1.0 + _pairwise_sqdist(Y))
    np.fill_diagonal(num, 0.0)
    total = num.sum()
    if total <= 0:
        raise AnalysisError('ALGORITHM_ERROR', 't-SNE 低维相似度总和为 0')
    return num, num / total


def _kl_gradient(Y, P, num, Q):
    """Gradient of KL(P || Q) for the Student-t low-dimensional distribution."""
    np = _numpy()
    weighted = (P - Q) * num
    return 4.0 * (weighted.sum(axis=1)[:, None] * Y - weighted @ Y)


def _binary_search_sigma(d2_row, target_perp, tol, max_iter):
    """对单个点的条件分布做二分搜索，返回 (P_row, sigma, perp)。"""
    np = _numpy()
    beta = 1.0
    lo, hi = float('-inf'), float('inf')
    for _ in range(max_iter):
        p_row = np.exp(-beta * d2_row)
        s = p_row.sum()
        p_row = p_row / s if s > 0 else p_row
        ent = -np.sum(p_row * np.log(p_row + 1e-300))
        perp = np.exp(ent)
        if abs(perp - target_perp) < tol:
            return p_row, (1.0 / beta if beta > 0 else 0.0), float(perp)
        if perp > target_perp:
            hi = beta
            beta = (beta + lo) / 2.0 if lo != float('-inf') else beta * 2.0
        else:
            lo = beta
            beta = (beta + hi) / 2.0 if hi != float('inf') else beta / 2.0
        if abs(beta) < 1e-300:
            beta = 1e-300
    return p_row, (1.0 / beta if beta > 0 else 0.0), float(perp)


def fit_tsne(X, perplexity=30.0, n_iter=1000, early_exaggeration=12.0,
             lr=200.0, seed=42):
    """标准 t-SNE。返回 dict：coords, sigma, kl, iterations_run, P 保留等。"""
    np = _numpy()
    X = np.asarray(X, dtype=float)
    n = X.shape[0]
    if n < 3:
        raise AnalysisError('ALGORITHM_ERROR', 't-SNE 拟合需要至少 3 个用户，实际 %d' % n)
    if not (3 * perplexity < n):
        raise AnalysisError('INVALID_PARAMETER',
                            'perplexity=%.1f 需要 3*perplexity < 样本数(%d)（数据与实验规范），'
                            '实际 3p=%.1f' % (perplexity, n, 3 * perplexity))

    Xc = X - X.mean(axis=0)
    d2 = _pairwise_sqdist(Xc)
    # 条件概率
    P = np.zeros((n, n), dtype=float)
    sigmas = np.zeros(n, dtype=float)
    for i in range(n):
        # 自身距离置极大值，使其在条件分布中概率≈0（随后显式清零并归一）
        d2_row = d2[i].copy()
        d2_row[i] = 1e30
        p_row, sigma_i, _perp = _binary_search_sigma(
            d2_row, float(perplexity), 1e-4, 200)
        p_row[i] = 0.0
        s = p_row.sum()
        if s > 0:
            p_row = p_row / s
        P[i] = p_row
        sigmas[i] = sigma_i
    P = (P + P.T) / (2.0 * n)
    np.maximum(P, 1e-12, out=P)
    np.fill_diagonal(P, 0.0)
    P /= P.sum()

    # 初始化：标准随机初始化（固定随机种子）
    rng = np.random.RandomState(seed)
    Y = rng.normal(0.0, 1e-4, size=(n, 2))
    dY = np.zeros_like(Y)
    gains = np.ones_like(Y)

    early_end = int(max(250, n_iter // 4)) if early_exaggeration > 0 else 0
    for it in range(n_iter):
        exag = early_exaggeration if it < early_end else 1.0
        P_eff = P * exag
        num, Q = _student_t_distribution(Y)
        G = _kl_gradient(Y, P_eff, num, Q)
        # 动量
        gains = np.where(np.sign(G) != np.sign(dY), gains + 0.2, gains * 0.8)
        np.maximum(gains, 0.01, out=gains)
        dY = 0.8 * dY if it < early_end else 0.9 * dY
        dY = dY - lr * gains * G
        Y = Y + dY
        Y -= Y.mean(axis=0)   # 居中
    # KL 散度（最终）
    _num, Q = _student_t_distribution(Y)
    kl = float(np.sum(P * np.log((P + 1e-12) / (Q + 1e-12))))
    return {
        'coords': Y.tolist(),
        'sigmas_mean': float(sigmas.mean()),
        'sigmas_min': float(sigmas.min()),
        'sigmas_max': float(sigmas.max()),
        'perplexity': float(perplexity),
        'early_exaggeration': float(early_exaggeration),
        'early_exaggeration_iters': int(early_end),
        'learning_rate': float(lr),
        'n_iter': int(n_iter),
        'final_kl': kl,
        'random_seed': int(seed),
    }


def knn_agreement(X_hi, Y_lo, k=10):
    """
    结构保留的相对指标：高维最近 k 个邻居中，有多少个在低维仍处于最近 k 邻域。
    返回每点一致率均值（random baseline≈k/(n-1)）。
    """
    np = _numpy()
    n = X_hi.shape[0]
    if n <= k + 1:
        return None, None
    d2hi = _pairwise_sqdist(X_hi)
    np.fill_diagonal(d2hi, 1e30)
    k_hi = np.argsort(d2hi, axis=1)[:, :k]
    d2lo = _pairwise_sqdist(Y_lo)
    np.fill_diagonal(d2lo, 1e30)
    k_lo = np.argsort(d2lo, axis=1)[:, :k]
    agrees = [len(set(k_hi[i]) & set(k_lo[i])) / float(k) for i in range(n)]
    baseline = k / float(n - 1)
    return float(np.mean(agrees)), baseline


def run(payload, acfg=None, rcfg=None, quiet=True):
    t0 = time.time()
    tracemalloc.start()
    acfg = acfg or config.load_analysis()
    rcfg = rcfg or config.load_rules()
    params = D.validate_dr_params(payload.get('parameters'))
    method_cfg = acfg['algorithms']['dimensionality_reduction'].get(METHOD, {})
    base_params = dict(method_cfg.get('parameters') or {})
    base_params.update(params)
    base_params.setdefault('target_dimensions', 2)
    if int(base_params['target_dimensions']) != 2:
        raise AnalysisError('INVALID_PARAMETER',
                            't-SNE 本工具只支持二维输出（target_dimensions=2）；'
                            '三维可视化不在本迭代范围')
    # 报错语义：用户错误（参数非法/越界）必须先于环境错误（缺 numpy）暴露，
    # 否则「依赖缺失」会掩盖「参数非法」。故 numpy 在参数校验之后才解析。
    np = _numpy()
    perplexity = float(base_params.get('perplexity', 30))
    n_iter = int(base_params.get('n_iter', 1000))
    early_exag = float(base_params.get('early_exaggeration', 12.0))
    lr = float(base_params.get('learning_rate', 200.0))
    seed = int(base_params.get('random_state', 42))
    knn_k = int(base_params.get('knn_k', 10))

    target_ids = D.normalize_user_ids(payload)
    users = D.resolve_users(acfg, rcfg, target_ids, quiet=quiet)
    meta = users['meta']
    X = np.asarray(users['orig_vectors'], dtype=float)

    fit = fit_tsne(X, perplexity=perplexity, n_iter=n_iter,
                   early_exaggeration=early_exag, lr=lr, seed=seed)
    Y = np.asarray(fit['coords'], dtype=float)
    agreement, baseline = knn_agreement(X, Y, k=knn_k)

    # t-SNE：样本外用户不投影（无投影矩阵）
    coords = []
    for uid, (x, y) in zip(users['fit_uids'], Y.tolist()):
        coords.append({'user_id': uid, 'x': float(x), 'y': float(y),
                       'status': 'SUCCESS', 'reliability_low': False,
                       'is_fit_user': True})
    for uid in sorted(users['out_of_sample']):
        rec = users['out_of_sample'][uid]
        status = ('NOT_PROJECTED_BY_TSNE' if rec.get('vector') is not None
                  else 'NO_TRAIN_HISTORY')
        note = ('t-SNE 为非参数嵌入，没有可复用投影矩阵：历史不足用户不强行放入同一张图'
                '（给出坐标即为伪造）' if rec.get('vector') is not None
                else rec.get('note'))
        coords.append({'user_id': uid, 'x': None, 'y': None,
                       'status': status, 'reliability_low': True,
                       'is_fit_user': False, 'note': note})

    comparison = D.build_clustering_comparison(
        users['orig_vectors'], Y.tolist(), base_params,
        int(base_params.get('clustering_seed', 42)))

    info = {
        'metric': 'knn_agreement',
        'knn_agreement': agreement,
        'knn_baseline': baseline,
        'knn_k': knn_k,
        'explained_variance_ratio': None,
        'definition': (('t-SNE 不适用解释方差：本工具以"高维 K 近邻在低维仍保留的比例"'
                        '（kNN 一致率，k=%d）作为结构保留的相对指标；随机基线≈k/(n-1)=%.4f。'
                        '该指标为相对参考，不构成绝对优劣结论。')
                       % (knn_k, baseline if baseline is not None else float('nan'))),
        'final_kl': fit['final_kl'],
        'perplexity': fit['perplexity'],
        'sigmas': {'mean': fit['sigmas_mean'], 'min': fit['sigmas_min'],
                   'max': fit['sigmas_max']},
        'early_exaggeration': fit['early_exaggeration'],
        'early_exaggeration_iters': fit['early_exaggeration_iters'],
        'learning_rate': fit['learning_rate'],
        'n_iter': fit['n_iter'],
        'random_seed': fit['random_seed'],
    }
    axis_meaning = {'x': D.AXIS_NOTE[('tsne', 'tsne1')],
                    'y': D.AXIS_NOTE[('tsne', 'tsne2')],
                    'loadings': None}
    versions = D.versions_of(acfg, rcfg, meta, METHOD, base_params)
    fit_scope = {
        'population': 'profile-v1 中 status=OK 的训练期画像用户（Timestamp<=T1）',
        'n_fit_users': len(users['fit_uids']),
        'original_dimensions': X.shape[1],
        'not_projected': len(users['out_of_sample']),
        'missing_user_ids': users['missing'],
    }
    limitations = list(LIMITATIONS)
    if users['missing']:
        limitations.append('请求包含不在 users.dat 的用户: %s，未给出坐标。'
                           % ','.join(users['missing']))
    if users['out_of_sample']:
        limitations.append('有 %d 个请求用户属于历史不足/无训练记录，t-SNE 坐标为 null（不投影）。'
                           % len(users['out_of_sample']))

    cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    resource = {
        'elapsed_ms': int((time.time() - t0) * 1000),
        'peak_alloc_bytes': int(peak),
        'memory_method': 'tracemalloc 进程内峰值（仅计 Python 分配，不含解释器/Numpy C 分配）',
        'n_fit': int(X.shape[0]), 'n_features': int(X.shape[1]),
    }
    return D.envelope(
        METHOD, ALGORITHM_NAME, ALGORITHM_SOURCE, base_params, versions,
        int(X.shape[1]), 2, info, resource, coords, comparison,
        fit_scope, limitations, axis_meaning)


def main(argv=None):
    ap = argparse.ArgumentParser(description='t-SNE 降维工具（独立运行 / 子进程协议）')
    ap.add_argument('--user', action='append', default=[], help='目标用户 ID，可重复；缺省=全部拟合用户')
    ap.add_argument('--perplexity', type=float, default=None)
    ap.add_argument('--n-iter', type=int, default=None)
    ap.add_argument('--k', type=int, default=None)
    ap.add_argument('--request', default=None, help='payload JSON 文件（调度器模式）')
    ap.add_argument('--output', default=None, help='信封输出 JSON（调度器模式）')
    args = ap.parse_args(argv)
    params = {}
    if args.perplexity is not None:
        params['perplexity'] = args.perplexity
    if args.n_iter is not None:
        params['n_iter'] = args.n_iter
    if args.k is not None:
        params['clustering_k'] = args.k
    try:
        if args.request:
            with open(args.request, 'r', encoding='utf-8') as f:
                payload = json.load(f)
        else:
            payload = {'user_ids': [int(x) for x in args.user] or None,
                       'parameters': params}
        res = run(payload, quiet=bool(args.output))
    except AnalysisError as e:
        D.fail_stdout_and_exit2(e)
        return 2
    if args.output:
        D.write_envelope_file(res, args.output)
        print(json.dumps({'status': 'SUCCESS', 'result_version': res['result_version'],
                          'output': args.output, 'elapsed_ms': res['resource_usage']['elapsed_ms']},
                         ensure_ascii=False))
    else:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
