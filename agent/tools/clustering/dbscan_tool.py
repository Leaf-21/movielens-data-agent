#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DBSCAN 密度聚类工具（clustering_dbscan，成员B）

实现口径（agent/config/analysis.json algorithms.clustering.dbscan）：
  · min_samples=15（邻域含自身，sklearn 惯例）；
  · eps 默认由启发式给出：对拟合集合做确定性抽样(种子42, 800人)，
    取每个抽样点到其第 min_samples 近邻（不含自身）的距离，
    再取这些 k 距离的第 90 百分位；eps/k 距离分布写入 metrics；
    请求方可用白名单参数 eps 显式覆盖。
  · 距离扫描"即时计算 + eps² 提前截断"，**不驻留全距离矩阵**
    （本机实测大矩阵长进程有解释器级崩溃风险，且即时计算更快，见运行报告）；
  · 迭代式区域扩张（显式队列，避免递归深度问题）；噪声点 cluster_id=-1；
  · 无样本外分配语义：历史不足/无训练记录用户不投影，如实报未分配。
来源登记：经典密度聚类（支持噪声标记）；课程 PPT 章节/页码待团队核对后登记。

独立运行 / 子进程协议：同 kmeans_tool。
"""

import argparse
import json
import os
import sys
import time
from collections import deque

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS_DIR = os.path.dirname(_HERE)
_SRC_DIR = os.path.join(os.path.dirname(_TOOLS_DIR), 'src')
# _HERE 显式入径：python3 -I 隔离模式不含脚本目录（子进程协议要求）
for _p in (_HERE, _SRC_DIR, _TOOLS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config                                        # noqa: E402
import build_profile as bp                            # noqa: E402
import metrics as M                                   # noqa: E402
from common import (AnalysisError, ALGORITHM_ERROR,   # noqa: E402
                    now_utc)
from schemas import (validate_parameters, normalize_targets,       # noqa: E402
                     user_statuses, cluster_summaries,             # noqa: E402
                     versions_block, result_version_of)

ALGO = 'dbscan'
NOISE = -1
UNSEEN = -2

LIMITATIONS_BASE = [
    'DBSCAN 的簇由密度连通性定义，高维 z-score 空间存在链接(chaining)效应：'
    'eps 偏大时多个语义群会连成巨簇、偏小噪声过多，故结果对 eps 敏感，'
    'eps_kdistance 分布与口径写入 metrics，群体划分主视角应以 K-Means 对照。',
    'DBSCAN 无样本外分配语义：历史不足与无训练记录用户不投影到密度簇'
    '（状态如实标 INSUFFICIENT_HISTORY / NO_TRAIN_HISTORY，cluster_id=null），'
    '这是算法性质而非缺陷。',
    '特征只用训练期(Timestamp<=T1)记录；未纳入人口学属性'
    '（见 analysis.json feature_dict._excluded）。',
    '噪声点不是群体，不给出摘要；噪声占比写入 metrics.noise_ratio。',
]


def kdistance_eps(vectors, sample_idx, min_samples, method_note):
    """
    确定性抽样点的第 min_samples 近邻距离（不含自身），取 p90 作为 eps。
    返回 (eps, 分布摘要)。抽样规模 < min_samples 时如实报错。
    """
    if not sample_idx or min_samples > len(vectors) - 1:
        raise AnalysisError(ALGORITHM_ERROR,
                            'eps 启发式不可用：样本数 %d 不足以取第 %d 近邻'
                            % (len(vectors), min_samples))
    kdist = []
    n = len(vectors)
    for i in sample_idx:
        vi = vectors[i]
        ds = [M.euclid(vi, vectors[j]) for j in range(n) if j != i]
        ds.sort()
        kdist.append(ds[min_samples - 1])
    kdist.sort()
    m = len(kdist)
    p = lambda q: kdist[min(m - 1, int(q * (m - 1) + 0.5))]
    eps = p(0.90)
    dist = {'method': method_note,
            'sample_size': m,
            'k_percentiles': {'min': kdist[0], 'p50': p(0.50), 'p75': p(0.75),
                              'p90': eps, 'p95': p(0.95), 'max': kdist[-1]}}
    return eps, dist


def _region(vectors, i, eps2):
    """eps 邻域（含自身），逐维平方和提前截断，不存矩阵。"""
    vi = vectors[i]
    out = []
    for j, vj in enumerate(vectors):
        if j == i:
            out.append(j)
            continue
        s = 0.0
        for a, b in zip(vi, vj):
            t = a - b
            s += t * t
            if s > eps2:
                break
        if s <= eps2:
            out.append(j)
    return out


def dbscan(vectors, eps, min_samples):
    """
    标准 DBSCAN（迭代队列扩张，避免递归）。labels[i]: 簇号(0..)/NOISE(-1)/UNSEEN(-2)。
    不变式：visited[j]=True ⇔ 邻域已定（核心或噪声）；已入簇 ⇒ 已访问。
    暂定噪声点若后来被核心点密度可达，转为该簇边界（不再扩散，其邻域<min_samples）。
    扫描顺序固定（拟合用户 ID 升序）+ FIFO 队列 ⇒ 同参数同输入逐位可复现。
    """
    n = len(vectors)
    eps2 = eps * eps
    labels = [UNSEEN] * n
    visited = [False] * n
    cid = -1
    for i in range(n):
        if visited[i]:
            continue
        ri = _region(vectors, i, eps2)
        visited[i] = True
        if len(ri) < min_samples:
            labels[i] = NOISE              # 暂定噪声，可被后续核心点吸收为边界
            continue
        cid += 1
        labels[i] = cid
        queue = deque(x for x in ri if x != i)
        while queue:
            j = queue.popleft()
            if labels[j] >= 0:
                continue                   # 已属某个簇（本簇或更早的簇），边界归属先到先得
            if visited[j]:                 # 必为暂定噪声 → 吸收为边界
                labels[j] = cid
                continue
            rj = _region(vectors, j, eps2)
            visited[j] = True
            labels[j] = cid
            if len(rj) >= min_samples:     # 核心点：继续扩散
                queue.extend(x for x in rj if not visited[x] or labels[x] == NOISE)
    return labels, cid + 1


def run(payload, acfg=None, rcfg=None, quiet=True):
    t0 = time.time()
    acfg = acfg or config.load_analysis()
    rcfg = rcfg or config.load_rules()
    algo_cfg = acfg['algorithms']['clustering'][ALGO]
    params = dict(algo_cfg['parameters'])
    override = validate_parameters(ALGO, payload.get('parameters'),
                                   acfg['allowed_parameters'])
    params.update(override)
    min_samples = int(params['min_samples'])
    seed = int(params['seed'])
    sample_size = int(params.get('eps_sample_size', 800))

    targets = normalize_targets(payload)
    prof_path, meta = bp.build_profile(acfg, rcfg, force=False, quiet=quiet)
    users = bp.load_profile(prof_path)
    known, unknown = user_statuses(targets, users)

    fit_uids = sorted(u for u, r in users.items() if r.get('fit') and r.get('vector'))
    if len(fit_uids) < min_samples + 1:
        raise AnalysisError(ALGORITHM_ERROR,
                            '拟合用户 %d 人 < min_samples+1，密度定义不可用'
                            % len(fit_uids))
    vectors = [users[u]['vector'] for u in fit_uids]

    if 'eps' in override:
        eps = float(override['eps'])
        kd_dist = {'method': 'user_provided_eps', 'sample_size': 0}
    else:
        sidx = M.sample_indices(len(vectors), sample_size, seed)
        eps, kd_dist = kdistance_eps(vectors, sidx, min_samples,
                                     'kdistance_p90（第%d近邻距离的P90，不含自身）'
                                     % min_samples)
        kd_dist['seed'] = seed

    labels, n_clusters = dbscan(vectors, eps, min_samples)
    uid_label = {u: labels[i] for i, u in enumerate(fit_uids)}

    # ---- 指标（噪声不参与轮廓/DBI，口径写入 definition）----
    non_noise = [(u, l) for u, l in uid_label.items() if l != NOISE]
    n_noise = sum(1 for l in labels if l == NOISE)
    sizes = {}
    cen_vec = {}
    for l in labels:
        if l != NOISE:
            sizes[l] = sizes.get(l, 0) + 1
    sh_sampled = M.silhouette_sampled(vectors, labels,
                                      M.sample_indices(len(vectors), sample_size, seed))
    if n_clusters >= 2:
        full_sh, _ = M.silhouette(vectors, labels)
        for c in sorted(sizes):
            cen_vec[c] = M.centroid([vectors[i] for i, l in enumerate(labels)
                                     if l == c])
        dbi = M.davies_bouldin(vectors, labels, cen_vec)
    else:
        full_sh, dbi = (None, None)

    assignments = []
    for u in known:
        rec = users[u]
        if u in uid_label:
            l = uid_label[u]
            if l == NOISE:
                assignments.append({'user_id': u, 'cluster_id': None,
                                    'status': 'UNASSIGNED_BY_DENSITY',
                                    'is_noise': True, 'reliability_low': True,
                                    'note': 'eps=%.4f 邻域密度不足（第 %d 近邻口径），'
                                            '不赋予群体结论' % (eps, min_samples)})
            else:
                assignments.append({'user_id': u, 'cluster_id': l,
                                    'status': 'SUCCESS', 'is_noise': False,
                                    'reliability_low': False})
        elif rec.get('vector') is not None:
            assignments.append({'user_id': u, 'cluster_id': None,
                                'status': 'INSUFFICIENT_HISTORY',
                                'is_noise': None, 'reliability_low': True,
                                'note': '未参与密度拟合；DBSCAN 无样本外分配语义，不投影'})
        else:
            assignments.append({'user_id': u, 'cluster_id': None,
                                'status': 'NO_TRAIN_HISTORY',
                                'is_noise': None, 'reliability_low': True,
                                'note': rec.get('note')})

    fnames = meta['feature_names']
    limitations = list(LIMITATIONS_BASE)
    limitations.append('18 个类型占比之和恒为 1，该组维度线性冗余（有效自由度 17），'
                       '稀有类型经 z-score 后对欧氏距离影响较大，已如实登记。')
    if meta.get('n_train_users_not_in_users_dat'):
        limitations.append('训练期有 %d 个评分用户不在 users.dat（迭代一孤儿引用），'
                           '未纳入画像与拟合域。'
                           % meta['n_train_users_not_in_users_dat'])
    if unknown:
        limitations.append('本次请求含未知用户: %s，未给出归属。' % ','.join(unknown))
    if n_clusters <= 1:
        limitations.append('本次 eps=%.4f/min_samples=%d 下仅得到 %d 个密度簇，'
                           '轮廓系数与 DBI 不适用（null），可显式调参重试。'
                           % (eps, min_samples, n_clusters))

    summaries = []
    if payload.get('with_summaries', True):
        rated, movies = bp.snapshot_for_summaries(acfg)
        summaries = cluster_summaries(uid_label, users, rated, movies, fnames, acfg)

    fit_fp = '%s|%s|%s|%s' % (meta['config_fingerprint'],
                              json.dumps(sorted(params.items()), default=str),
                              ('%.10f' % eps), meta['input_sha256']['ratings.dat'][:12])
    versions = versions_block(ALGO, acfg, meta, fit_fp)
    created = now_utc()
    metrics = {
        'n_clusters': n_clusters,
        'eps_used': eps,
        'eps_method': ('user_provided' if 'eps' in override
                       else algo_cfg['parameters']['eps_method']),
        'eps_kdistance': kd_dist,
        'min_samples': min_samples,
        'noise_count': n_noise,
        'noise_ratio': n_noise / float(len(vectors)),
        'cluster_sizes': {str(k): v for k, v in sorted(sizes.items())},
        'silhouette_sampled': sh_sampled,
        'silhouette_full': full_sh,
        'davies_bouldin_full': dbi,
        'n_fit_users': len(fit_uids),
        'n_non_noise_assigned': len(non_noise),
        'determinism_note': '邻域扫描按拟合用户ID升序 + 迭代队列顺序固定，同参数同输入逐位可复现',
        'definition': {
            'silhouette': M.METRIC_DEFINITIONS['silhouette'],
            'davies_bouldin': M.METRIC_DEFINITIONS['davies_bouldin'],
            'noise_ratio': M.METRIC_DEFINITIONS['noise_ratio'],
            'eps': ('eps 为邻域半径（标准化空间欧氏距离）；核心点定义：含自身邻域数'
                    '>= min_samples；k 距离为不含自身的第 min_samples 近邻距离。'),
            'validation_drift': M.METRIC_DEFINITIONS['validation_drift'],
        },
    }
    envelope = {
        'algorithm': ALGO,
        'algorithm_tool': 'clustering_dbscan',
        'model_version': versions['model_version'],
        'result_version': None,
        'parameters': params,
        'data_version': versions['data_version'],
        'profile_version': versions['profile_version'],
        'T1': versions['T1'], 'T2': versions['T2'],
        'code_version': versions['code_version'],
        'created_at': created,
        'fit_scope': {'population': 'profile-v1 中 status=OK 的训练期画像用户',
                      'n_fit_users': len(fit_uids),
                      'vector_dim': len(fnames)},
        'cluster_centroids_reference': {str(k): v for k, v in cen_vec.items()},
        'feature_names': fnames,
        'metrics': metrics,
        'assignments': assignments,
        'cluster_summaries': summaries,
        'limitations': limitations,
        'algorithm_source': algo_cfg['algorithm_source'],
        'elapsed_ms': int((time.time() - t0) * 1000),
    }
    envelope['result_version'] = result_version_of(
        envelope['model_version'], assignments, metrics, summaries)
    return envelope


def write_envelope_file(res, out_path):
    d = os.path.dirname(os.path.abspath(out_path))
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = out_path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    os.replace(tmp, out_path)


def main():
    ap = argparse.ArgumentParser(description='DBSCAN 密度聚类工具（独立运行/子进程协议）')
    ap.add_argument('--user', action='append', default=[], help='目标用户 ID，可重复')
    ap.add_argument('--eps', type=float, default=None, help='显式 eps（覆盖启发式）')
    ap.add_argument('--min-samples', type=int, default=None)
    ap.add_argument('--no-summaries', action='store_true')
    ap.add_argument('--request', default=None, help='payload JSON 文件（调度器模式）')
    ap.add_argument('--output', default=None, help='信封输出 JSON（调度器模式）')
    ap.add_argument('--out', default=None, help='结果 JSON 输出路径（兼容旧参数）')
    args = ap.parse_args()
    p = {}
    if args.eps is not None:
        p['eps'] = args.eps
    if args.min_samples is not None:
        p['min_samples'] = args.min_samples
    try:
        if args.request:
            with open(args.request, 'r', encoding='utf-8') as f:
                payload = json.load(f)
        else:
            payload = {'user_ids': [int(x) for x in args.user] or None,
                       'parameters': p,
                       'with_summaries': not args.no_summaries}
            if not payload['user_ids']:
                acfg = config.load_analysis()
                prof, _ = bp.build_profile(acfg, config.load_rules(), quiet=True)
                payload['user_ids'] = sorted(bp.load_profile(prof).keys())
        res = run(payload, quiet=(args.output is not None))
    except AnalysisError as e:
        json.dump({'status': 'FAILED', 'error': e.to_error_dict()},
                  sys.stdout, ensure_ascii=False)
        sys.stdout.write('\n')
        return 2
    out_path = args.output or args.out
    if out_path:
        write_envelope_file(res, out_path)
        print(json.dumps({'status': 'SUCCESS', 'result_version': res['result_version'],
                          'output': out_path, 'elapsed_ms': res['elapsed_ms']},
                         ensure_ascii=False))
    else:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
