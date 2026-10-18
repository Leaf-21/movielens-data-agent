#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K-Means 聚类工具（clustering_kmeans，成员B）

实现口径（agent/config/analysis.json algorithms.clustering.kmeans）：
  · kmeans++ 初始化，random.Random(seed=42) 确定性抽样；
  · Lloyd 迭代 max_iter=100 / tol=1e-6，空簇按"离自身质心最远的点"重建；
  · 候选 k=[2..8]：每个候选在拟合集合（画像 OK 用户）上实际拟合，
    按确定性 800 人抽样的轮廓系数估计选最优（同分取较小 k），
    选定 k 后在全体拟合用户上复算全量轮廓系数与 DBI；
  · 非拟合用户（历史不足但有向量）给出最近质心参考簇，
    status=ASSIGNED_FROM_FITTED_CENTROIDS、reliability_low=true，
    不参与拟合、不影响质心；无训练记录用户 NO_TRAIN_HISTORY。
来源登记：经典划分聚类；课程 PPT 章节/页码待团队核对后登记。

独立运行 / 子进程协议（analysis_runner 以 subprocess 隔离执行，崩溃不拖垮 API 服务）：
  python3 agent/tools/clustering/kmeans_tool.py [--user 42 --user 100 ...]
  python3 agent/tools/clustering/kmeans_tool.py --request req.json --output out.json
  失败时以退出码 2 结束并把 AnalysisError 的 {code,message,details} JSON 打到 stdout，
  供调度层原样转写错误（不伪造结果）。
"""

import argparse
import json
import os
import random
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS_DIR = os.path.dirname(_HERE)
_SRC_DIR = os.path.join(os.path.dirname(_TOOLS_DIR), 'src')
# _HERE 显式入径：python3 -I 隔离模式不含脚本目录（子进程协议要求）
for _p in (_HERE, _SRC_DIR, _TOOLS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config                                        # noqa: E402
import build_profile as bp                           # noqa: E402
import metrics as M                                  # noqa: E402
from common import (AnalysisError, ALGORITHM_ERROR,   # noqa: E402
                    INVALID_PARAMETER, now_utc)
from schemas import (validate_parameters, normalize_targets,      # noqa: E402
                     user_statuses, cluster_summaries,            # noqa: E402
                     versions_block, result_version_of)

ALGO = 'kmeans'

LIMITATIONS_BASE = [
    'K-Means 假设簇为凸形且大小相近，对非凸密度结构不适用；结果对初始点敏感，'
    '本实现以固定种子(42)的 kmeans++ 保证可复现。',
    '特征只用训练期(Timestamp<=T1)行为统计与类型占比；未纳入人口学属性'
    '（迭代一已确认其可信性局限，见 analysis.json feature_dict._excluded）。',
    '历史不足用户(训练期评分 < min_train_ratings)的簇归属仅为"最近质心参考"，'
    '可靠性低(reliability_low=true)，不构成对其群体的结论。',
    '候选 k 的轮廓系数按 800 人确定性抽样估计（全量 O(n²) 代价过高），'
    '选定 k 后在全体拟合用户上复算；两者均写入 metrics。',
]


def kmeanspp_init(vectors, k, rng):
    """kmeans++：首个点均匀随机，其后按 D² 加权抽样。确定性由 rng 保证。"""
    n = len(vectors)
    centers = [list(vectors[rng.randrange(n)])]
    for _ in range(1, k):
        d2 = []
        for v in vectors:
            m = min(M.euclid(v, c) ** 2 for c in centers)
            d2.append(m)
        total = sum(d2)
        if total <= 1e-12:            # 全部点与现有质心重合：均匀补足
            centers.append(list(vectors[rng.randrange(n)]))
            continue
        r = rng.random() * total
        acc = 0.0
        pick = n - 1
        for i, x in enumerate(d2):
            acc += x
            if acc >= r:
                pick = i
                break
        centers.append(list(vectors[pick]))
    return centers


def _assign(vectors, centers):
    labels = []
    dists = []
    for v in vectors:
        best_i, best_d = 0, float('inf')
        for ci, c in enumerate(centers):
            d = M.euclid(v, c)
            if d < best_d:
                best_i, best_d = ci, d
        labels.append(best_i)
        dists.append(best_d)
    return labels, dists


def lloyd(vectors, centers, max_iter, tol):
    """Lloyd 主循环。返回 (labels, centers, iterations, converged, n_empty_fixed)。"""
    n = len(vectors)
    k = len(centers)
    labels, dists = _assign(vectors, centers)
    empty_fixed = 0
    converged = False
    it = 0
    for it in range(1, max_iter + 1):
        groups = [[] for _ in range(k)]
        for i, lab in enumerate(labels):
            groups[lab].append(i)
        new_centers = []
        move = 0.0
        for c_i, g in enumerate(groups):
            if not g:                                    # 空簇：以离自身质心最远的点重建
                far = max(range(n), key=lambda i: dists[i])
                g = [far]
                labels[far] = c_i
                empty_fixed += 1
            c = M.centroid([vectors[i] for i in g])
            move = max(move, M.euclid(c, centers[c_i]))
            new_centers.append(c)
        labels, dists = _assign(vectors, new_centers)
        centers = new_centers
        if move < tol:
            converged = True
            break
    return labels, centers, it, converged, empty_fixed


def fit_one_k(vectors, k, seed, max_iter, tol):
    rng = random.Random(seed * 100003 + k)   # 每个候选 k 的确定性种子
    centers = kmeanspp_init(vectors, k, rng)
    labels, centers, iters, conv, empty = lloyd(vectors, centers, max_iter, tol)
    return {'labels': labels, 'centers': centers, 'iterations': iters,
            'converged': conv, 'empty_cluster_fixes': empty}


# 抽样与抽样轮廓系数实现已上移至 metrics.py（两算法共用同一估计口径）




def run(payload, acfg=None, rcfg=None, quiet=True):
    """
    入口（registry 动态导入调用）。payload 已由路由层做协议校验，这里做
    语义/参数校验并返回统一信封；失败一律抛 AnalysisError。
    payload: {'user_ids': [...], 'parameters': {...}}
    """
    t0 = time.time()
    acfg = acfg or config.load_analysis()
    rcfg = rcfg or config.load_rules()
    algo_cfg = acfg['algorithms']['clustering'][ALGO]
    base_params = dict(algo_cfg['parameters'])
    override = validate_parameters(ALGO, payload.get('parameters'),
                                   acfg['allowed_parameters'])
    # 白名单允许显式固定 k / 迭代数 / 种子；候选表等在 base 上覆盖
    params = dict(base_params)
    params.update(override)

    targets = normalize_targets(payload)
    prof_path, meta = bp.build_profile(acfg, rcfg, force=False, quiet=quiet)
    users = bp.load_profile(prof_path)
    known, unknown = user_statuses(targets, users)

    fit_uids = sorted(u for u, r in users.items() if r.get('fit') and r.get('vector'))
    if len(fit_uids) < 2:
        raise AnalysisError(ALGORITHM_ERROR,
                            '拟合用户不足 2 人，K-Means 无意义', {'n_fit': len(fit_uids)})
    vectors = [users[u]['vector'] for u in fit_uids]

    candidates = ([int(params['k'])] if 'k' in override
                  else [int(x) for x in params['k_candidates']])
    seed = int(params['seed'])
    max_iter = int(params['max_iter'])
    tol = float(params['tol'])
    sample_size = int(params.get('silhouette_sample_size', 800))
    sample_idx = M.sample_indices(len(vectors), sample_size, seed)

    table = []
    fits = {}
    for k in candidates:
        if not (2 <= k <= len(vectors)):
            raise AnalysisError(INVALID_PARAMETER,
                                '候选 k=%d 超过拟合样本数 %d，需满足 2<=k<=n'
                                % (k, len(vectors)))
        fit = fit_one_k(vectors, k, seed, max_iter, tol)
        sh = M.silhouette_sampled(vectors, fit['labels'], sample_idx)
        dbi = M.davies_bouldin(vectors, fit['labels'], fit['centers'])
        s = M.sse(vectors, fit['labels'], fit['centers'])
        fits[k] = fit
        table.append({'k': k, 'silhouette_sampled': sh,
                      'silhouette_basis': 'sample_%d_seed_%d' % (
                          min(sample_size, len(vectors)), seed),
                      'davies_bouldin': dbi, 'sse': s,
                      'iterations': fit['iterations'], 'converged': fit['converged'],
                      'empty_cluster_fixes': fit['empty_cluster_fixes']})
    with_s = [t for t in table if t['silhouette_sampled'] is not None]
    if not with_s:
        raise AnalysisError(ALGORITHM_ERROR, '所有候选 k 的轮廓系数均无法计算')
    best = max(with_s, key=lambda t: (t['silhouette_sampled'], -t['k']))
    k_star = best['k']
    chosen = fits[k_star]

    # 选定 k 的全量轮廓系数（O(n²)，一次性成本，异步任务内可接受）
    full_sh, per_cluster_sh = M.silhouette(vectors, chosen['labels'])

    # 标签：拟合用户 -> 正常归属；其余按向量给最近质心参考
    uid_label = {u: chosen['labels'][i] for i, u in enumerate(fit_uids)}
    assignments = []
    for u in known:
        rec = users[u]
        if u in uid_label:
            assignments.append({
                'user_id': u, 'cluster_id': uid_label[u], 'status': 'SUCCESS',
                'reliability_low': False,
                'distance_to_centroid': M.euclid(rec['vector'],
                                                 chosen['centers'][uid_label[u]]),
            })
        elif rec.get('vector') is not None:
            dists = [M.euclid(rec['vector'], c) for c in chosen['centers']]
            bi = min(range(len(dists)), key=lambda i: dists[i])
            assignments.append({
                'user_id': u, 'cluster_id': bi, 'status': 'ASSIGNED_FROM_FITTED_CENTROIDS',
                'reliability_low': True, 'distance_to_centroid': dists[bi],
                'note': rec.get('note'),
            })
        else:
            assignments.append({'user_id': u, 'cluster_id': None,
                               'status': 'NO_TRAIN_HISTORY', 'reliability_low': True,
                               'distance_to_centroid': None, 'note': rec.get('note')})

    fnames = meta['feature_names']
    limitations = list(LIMITATIONS_BASE)
    limitations.append('18 个类型占比之和恒为 1（多标签影片计入每个类型），该组维度存在'
                       '线性冗余，有效自由度为 17；这是登记的特征工程选择，不是缺陷掩盖。')
    if meta.get('n_train_users_not_in_users_dat'):
        limitations.append('训练期有 %d 个评分用户不在 users.dat（迭代一孤儿引用），'
                           '未纳入画像与拟合域，详见画像 meta.orphan_user_ids。'
                           % meta['n_train_users_not_in_users_dat'])
    if unknown:
        limitations.append('本次请求含未知用户（不存在于 users.dat）: %s，'
                           '未给出归属。' % ','.join(unknown))
    if override.get('k'):
        limitations.append('k=%d 由请求方显式指定，未执行候选选择；k_selection_table '
                           '仅含该 k。' % k_star)

    summaries = []
    if payload.get('with_summaries', True):
        rated, movies = bp.snapshot_for_summaries(acfg)
        # 群体统计对**全体拟合用户**计算（即使不在本次 target 列表内），
        # 摘要数字必须是真实群内统计，不因请求范围不同而变化。
        summaries = cluster_summaries(uid_label, users, rated, movies, fnames, acfg)

    fit_fp = '%s|%s|%s' % (meta['config_fingerprint'],
                           json.dumps(sorted(params.items()), default=str),
                           meta['input_sha256']['ratings.dat'][:12])
    versions = versions_block(ALGO, acfg, meta, fit_fp)
    versions['created_at'] = now_utc()
    metrics = {
        'k_selected': k_star,
        'k_selection_rule': algo_cfg['selection_rule'],
        'k_selection_table': table,
        'silhouette_full': full_sh,
        'silhouette_per_cluster_full': {str(k): v for k, v in per_cluster_sh.items()},
        'davies_bouldin_full': M.davies_bouldin(vectors, chosen['labels'],
                                                chosen['centers']),
        'sse_full': M.sse(vectors, chosen['labels'], chosen['centers']),
        'n_fit_users': len(fit_uids),
        'n_non_fit_reference': sum(1 for a in assignments
                                   if a['status'] == 'ASSIGNED_FROM_FITTED_CENTROIDS'),
        'definition': {
            'silhouette': M.METRIC_DEFINITIONS['silhouette'],
            'davies_bouldin': M.METRIC_DEFINITIONS['davies_bouldin'],
            'sse': M.METRIC_DEFINITIONS['sse'],
            'k_selection_table': M.METRIC_DEFINITIONS['k_selection_table'],
        },
    }
    envelope = {
        'algorithm': ALGO,
        'algorithm_tool': 'clustering_kmeans',
        'model_version': versions['model_version'],
        'result_version': None,
        'parameters': params,
        'data_version': versions['data_version'],
        'profile_version': versions['profile_version'],
        'T1': versions['T1'], 'T2': versions['T2'],
        'code_version': versions['code_version'],
        'created_at': versions['created_at'],
        'fit_scope': {'population': 'profile-v1 中 status=OK 的训练期画像用户',
                      'n_fit_users': len(fit_uids),
                      'centroid_dim': len(fnames)},
        'centroids': chosen['centers'],
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
    ap = argparse.ArgumentParser(description='K-Means 聚类工具（独立运行/子进程协议）')
    ap.add_argument('--user', action='append', default=[], help='目标用户 ID，可重复')
    ap.add_argument('--k', type=int, default=None, help='显式指定 k（跳过候选选择）')
    ap.add_argument('--no-summaries', action='store_true')
    ap.add_argument('--request', default=None, help='payload JSON 文件（调度器模式）')
    ap.add_argument('--output', default=None, help='信封输出 JSON（调度器模式）')
    ap.add_argument('--out', default=None, help='结果 JSON 输出路径（兼容旧参数）')
    args = ap.parse_args()
    try:
        if args.request:
            with open(args.request, 'r', encoding='utf-8') as f:
                payload = json.load(f)
        else:
            payload = {'user_ids': [int(x) for x in args.user] or None,
                       'parameters': ({'k': args.k} if args.k else {}),
                       'with_summaries': not args.no_summaries}
            if not payload['user_ids']:
                # 独立运行默认对全量画像用户给出归属
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
