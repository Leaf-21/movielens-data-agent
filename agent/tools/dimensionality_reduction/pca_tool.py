#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PCA 降维工具（dimensionality_reduction_pca，成员C）

口径（任务书 §2/§3，数据与实验规范 §五）：
  · 输入：profile-v1 画像 z-score 向量（27 维，训练期 Timestamp<=T1）；
  · 拟合集：画像拟合用户（status=OK），历史不足用户只做样本外投影
    （reliability_low=true），无训练记录用户排除；
  · 拟合方式：对**拟合集**做协方差矩阵 + 对称特征分解（np.linalg.eigh，
    实对称矩阵，非近似幂迭代）；不重新标准化——画像向量已 z-score；
  · 分量**符号规范化**：每个主成分内绝对值最大的载荷取正号，
    以保证同数据同实现可逐位复现、前端轴方向稳定（记录于符号约定字段）；
  · 信息保留：报告各分量解释方差比、累计解释方差比、达到阈值的维数；
  · 降维前后聚类对照：同一用户集合，K-Means 固定 k（参数来自 analysis.json
    kmeans 登记的 seed），复用 kmeans_tool.fit_one_k 与 metrics.py，
    指标口径与聚类工具完全一致。

独立运行（交付清单"工具可独立运行"）：
  python3 -I agent/tools/dimensionality_reduction/pca_tool.py \
      --user 1000 --user 2000 [--target-dim 2] [--k 6]

子进程协议（成员B调度器）：
  python3 -I <file> --request req.json --output out.json
本文件只用标准库 + numpy（requirements.txt 登记）。
"""

import argparse
import os
import sys
import time
import tracemalloc

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS_DIR = os.path.dirname(_HERE)
_CLUSTERING_DIR = os.path.join(_TOOLS_DIR, 'clustering')
_SRC_DIR = os.path.join(os.path.dirname(_TOOLS_DIR), 'src')
# python3 -I 不含脚本目录，显式入径（子进程协议要求）。
# 顺序关键：agent/tools 下的 common 是成员A的数据包（无 AnalysisError），
# 因此**不把 agent/tools 入 path**，必须先命中 clustering/common.py。
for _p in (_CLUSTERING_DIR, _SRC_DIR, _HERE):
    if _p in sys.path:
        sys.path.remove(_p)
    sys.path.insert(0, _p)

import config                                    # noqa: E402
from common import AnalysisError                 # noqa: E402
import dr_common as D                            # noqa: E402

METHOD = 'pca'

ALGORITHM_NAME = 'Principal Component Analysis (协方差矩阵 + 对称特征分解)'
ALGORITHM_SOURCE = ('PCA 标准定义：协方差矩阵前 d 个特征向量；'
                    '课程 PPT 章节/页码尚未核实')

LIMITATIONS = [
    'PCA 是线性方法：只捕获特征空间的线性方差结构，非线性簇结构（如类别占比的'
    '条件关系）不会被主成分显式建模。',
    '画像 18 个类型占比之和恒为 1，该组维度线性冗余（有效自由度 17），'
    'PCA 会把冗余反映到零方差方向上（解释方差比≈0），不视为信息丢失。',
    '主成分轴的"意义"是载荷线性组合：具体语义需查看 loadings，'
    '不能直接用原特征名命名；二维图只用于观察结构，不能仅凭视觉分离宣称更优。',
    '降维前后聚类对照使用同一用户集合与同一 K-Means 实现/k 值；SSE 在低维空间天然更小，'
    '跨空间比较应以轮廓系数与 DBI（无量纲）为准。',
]

SYMBOL_NOTE = ('每个主成分内 |载荷| 最大的特征载荷取正号（确定性符号规范化），'
               '保证同一数据/实现下坐标逐位可复现')


def _numpy():
    try:
        import numpy as np
    except ImportError:   # pragma: no cover - 依赖缺失时如实报错，不静默降级
        raise AnalysisError('ALGORITHM_ERROR',
                            'PCA 需要 numpy（requirements.txt 已登记）：pip install -r requirements.txt')
    return np


def fit_pca(vectors, target_dim, threshold=None):
    """
    在拟合集向量上做 PCA。返回 dict：
      coords (n x d), components (d x p), explained_ratio (p,), cumulative (p,),
      loadings 说明、符号约定、达到阈值所需维数等。
    """
    np = _numpy()
    X = np.asarray(vectors, dtype=float)
    n, p = X.shape
    if n < 3:
        raise AnalysisError('ALGORITHM_ERROR', 'PCA 拟合需要至少 3 个用户，实际 %d' % n)
    if not (1 <= target_dim <= p):
        raise AnalysisError('INVALID_PARAMETER',
                            'target_dimensions=%d 超出画像维度范围 [1, %d]' % (target_dim, p))
    # 中心化（画像已 z-score，均值≈0；显式再中心化保证数值稳定）
    mu = X.mean(axis=0)
    Xc = X - mu
    cov = (Xc.T @ Xc) / float(n - 1)
    # 实对称矩阵：eigh 返回升序特征值/特征向量
    vals, vecs = np.linalg.eigh(cov)
    order = np.argsort(vals)[::-1]
    vals = vals[order]
    vecs = vecs[:, order]
    # 负特征值来自数值误差，截断为 0（不改变解释方差比的分母 >0 部分）
    vals_clipped = np.where(vals < 0, 0.0, vals)
    total = float(vals_clipped.sum())
    if total <= 0:
        raise AnalysisError('ALGORITHM_ERROR', 'PCA 总方差为 0（拟合向量退化），无法降维')
    explained = vals_clipped / total
    cumulative = explained.cumsum()

    # 确定性符号规范化
    comp = vecs[:, :target_dim].copy()
    for j in range(target_dim):
        col = comp[:, j]
        k = int(np.argmax(np.abs(col)))
        if col[k] < 0:
            comp[:, j] = -col
    coords = Xc @ comp
    # 零方差方向：特征值相对总方差极小（<1e-12），用于"有效自由度"说明
    zero_dirs = int((vals_clipped / total < 1e-12).sum()) if total > 0 else 0
    keep_dims = target_dim
    if threshold is not None:
        keep_dims = 0
        for i, c in enumerate(cumulative):
            if c >= threshold:
                keep_dims = i + 1
                break
        else:
            keep_dims = p
    return {
        'n_fit': n, 'n_features': p,
        'mean': mu.tolist(),
        'coords': coords,
        'components': comp,
        'explained_ratio': explained.tolist(),
        'cumulative': cumulative.tolist(),
        'eigenvalues': vals_clipped.tolist(),
        'sign_convention': SYMBOL_NOTE,
        'zero_variance_directions': zero_dirs,
        'keep_dimensions_for_threshold': keep_dims,
    }


def run(payload, acfg=None, rcfg=None, quiet=True):
    t0 = time.time()
    tracemalloc.start()
    acfg = acfg or config.load_analysis()
    rcfg = rcfg or config.load_rules()
    params = D.validate_dr_params(payload.get('parameters'))
    method_cfg = acfg['algorithms']['dimensionality_reduction'].get(METHOD, {})
    base_params = dict(method_cfg.get('parameters') or {})
    base_params.update(params)
    target_dim = int(base_params.get('target_dimensions', 2))
    threshold = base_params.get('information_retention_threshold')
    threshold = None if threshold is None else float(threshold)

    target_ids = D.normalize_user_ids(payload)
    users = D.resolve_users(acfg, rcfg, target_ids, quiet=quiet)
    meta = users['meta']

    fit = fit_pca(users['orig_vectors'], target_dim, threshold)
    np = _numpy()
    comp = fit['components']

    # 样本外投影：同一 mean/主成分
    def projector(vec):
        return ((np.asarray(vec, dtype=float) - fit['mean']) @ comp).tolist()

    fit_coords = fit['coords'].tolist()
    coords = D.project_coordinates(users['fit_uids'], fit_coords,
                                   users['out_of_sample'], projector)

    # 轴上载荷（前端展示"轴含义"时给出真实特征名+载荷，绝不臆造）
    loadings = []
    for j in range(target_dim):
        w = comp[:, j]
        idx = np.argsort(np.abs(w))[::-1][:5]
        loadings.append({
            'component': 'PC%d' % (j + 1),
            'explained_variance_ratio': fit['explained_ratio'][j],
            'top_features': [{'feature': meta['feature_names'][int(i)],
                              'loading': float(w[int(i)])} for i in idx],
        })

    comparison = D.build_clustering_comparison(
        users['orig_vectors'], fit_coords, base_params, int(base_params.get('clustering_seed', 42)))

    info = {
        'metric': 'explained_variance_ratio',
        'explained_variance_ratio': fit['explained_ratio'][:max(target_dim, 10)],
        'cumulative_explained_variance': fit['cumulative'][:max(target_dim, 10)],
        'top2_cumulative': fit['cumulative'][min(1, len(fit['cumulative']) - 1)],
        'dimensions_for_threshold': fit['keep_dimensions_for_threshold'],
        'threshold': threshold,
        'eigenvalues_top10': fit['eigenvalues'][:10],
        'zero_variance_directions': fit['zero_variance_directions'],
        'sign_convention': fit['sign_convention'],
        'definition': ('解释方差比 = 第 i 个特征值 / 全部特征值之和（协方差矩阵，'
                       '样本自由度 n-1）；累计解释方差 = 前 d 个之比和。'),
    }
    axis_meaning = {
        'x': D.AXIS_NOTE[('pca', 'pc1')],
        'y': D.AXIS_NOTE[('pca', 'pc2')] if target_dim >= 2 else None,
        'loadings': loadings,
    }
    versions = D.versions_of(acfg, rcfg, meta, METHOD, base_params)
    fit_scope = {
        'population': 'profile-v1 中 status=OK 的训练期画像用户（Timestamp<=T1）',
        'n_fit_users': fit['n_fit'],
        'original_dimensions': fit['n_features'],
        'projected_out_of_sample': len(users['out_of_sample']),
        'missing_user_ids': users['missing'],
    }
    limitations = list(LIMITATIONS) + list(D.TRUST_LIMITATIONS)
    if users['missing']:
        limitations.append('请求包含不在 users.dat 的用户: %s，未给出坐标。'
                           % ','.join(users['missing']))
    if user_cold := [c for c in coords if c['status'] == 'NO_TRAIN_HISTORY']:
        limitations.append('有 %d 个请求用户训练期无评分记录，坐标为 null（不补值）。'
                           % len(user_cold))

    cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    resource = {
        'elapsed_ms': int((time.time() - t0) * 1000),
        'peak_alloc_bytes': int(peak),
        'memory_method': 'tracemalloc 进程内峰值（仅计 Python 分配，不含解释器/Numpy C 分配）',
        'n_fit': fit['n_fit'], 'n_features': fit['n_features'],
    }
    env = D.envelope(
        METHOD, ALGORITHM_NAME, ALGORITHM_SOURCE, base_params, versions,
        fit['n_features'], target_dim, info, resource, coords, comparison,
        fit_scope, limitations, axis_meaning)
    return env


def main(argv=None):
    ap = argparse.ArgumentParser(description='PCA 降维工具（独立运行 / 子进程协议）')
    ap.add_argument('--user', action='append', default=[], help='目标用户 ID，可重复；缺省=全部拟合用户')
    ap.add_argument('--target-dim', type=int, default=None)
    ap.add_argument('--k', type=int, default=None, help='降维前后聚类对照的 K-Means k')
    ap.add_argument('--request', default=None, help='payload JSON 文件（调度器模式）')
    ap.add_argument('--output', default=None, help='信封输出 JSON（调度器模式）')
    args = ap.parse_args(argv)
    params = {}
    if args.target_dim is not None:
        params['target_dimensions'] = args.target_dim
    if args.k is not None:
        params['clustering_k'] = args.k
    try:
        if args.request:
            import json as _json
            with open(args.request, 'r', encoding='utf-8') as f:
                payload = _json.load(f)
        else:
            payload = {'user_ids': [int(x) for x in args.user] or None,
                       'parameters': params}
        res = run(payload, quiet=bool(args.output))
    except AnalysisError as e:
        D.fail_stdout_and_exit2(e)
        return 2
    if args.output:
        import json as _json
        D.write_envelope_file(res, args.output)
        print(_json.dumps({'status': 'SUCCESS', 'result_version': res['result_version'],
                           'output': args.output, 'elapsed_ms': res['resource_usage']['elapsed_ms']},
                          ensure_ascii=False))
    else:
        import json as _json
        print(_json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
