#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
聚类工具的输入校验与统一输出信封（成员B）

依据 docs/迭代二/分工/迭代二接口扩展规范.md：
  §2.1 错误码枚举、§4.1 创建请求字段、§4.2 结果结构、§七 工具命名约定。

统一约定：
  · 工具结果 = {algorithm, algorithm_tool, model_version, result_version,
    parameters, profile_version, data_version, T1, T2, code_version,
    created_at, fit_scope, metrics, assignments, cluster_summaries,
    limitations, elapsed_ms}
  · Agent 层只做结构校验与透传，不改写算法原始指标（任务书 §3）。
  · target 用户状态语义：
      存在于画像且 fit=True      -> 该算法的正常归属
      画像存在但 fit=False        -> 状态 INSUFFICIENT_HISTORY：
          K-Means 给出最近质心参考簇（reliability_low=true），
          DBSCAN 无法为新点定义归属（cluster_id=null, is_noise=null）。
      不在 users.dat             -> UNKNOWN_USER（整体请求级）。
"""

import os as _os
import sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
for _p in (_HERE, _os.path.dirname(_HERE)):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

from common import AnalysisError, INVALID_PARAMETER, UNKNOWN_USER

DIM = 27  # profile-v1：9 个行为统计 + 18 个类型占比（顺序以画像 meta 为准）


def _num(x, lo, hi):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and lo <= x <= hi


def validate_parameters(algo, params, allowed):
    """未登记参数名/超范围取值 -> INVALID_PARAMETER（绝不静默忽略）。"""
    out = {}
    spec = (allowed or {}).get(algo, {})
    for k, v in (params or {}).items():
        if k not in spec:
            raise AnalysisError(INVALID_PARAMETER,
                                '%s 不支持参数 %r；允许参数: %s'
                                % (algo, k, sorted(spec)),
                                {'allowed': sorted(spec)})
        lo, hi = spec[k]
        if not _num(v, lo, hi):
            raise AnalysisError(INVALID_PARAMETER,
                                '%s 参数 %s=%r 超出允许范围 [%s, %s]' % (algo, k, v, lo, hi))
        out[k] = v
    return out


def normalize_targets(payload):
    """user_id / user_ids -> 去重升序 int 列表；两者都缺 -> INVALID_REQUEST。"""
    ids = []
    if payload.get('user_id') is not None:
        ids.append(payload['user_id'])
    raw = payload.get('user_ids')
    if isinstance(raw, list):
        ids += raw
    elif raw is not None:
        raise AnalysisError('INVALID_REQUEST', 'user_ids 必须是数组')
    if not ids:
        raise AnalysisError('INVALID_REQUEST',
                            'user_id 与 user_ids 至少提供其一（接口扩展规范 §4.1）')
    out = set()
    for x in ids:
        try:
            xi = int(str(x).strip())
        except (TypeError, ValueError):
            raise AnalysisError('INVALID_REQUEST', '无法解析的用户 ID: %r' % x)
        if xi <= 0:
            raise AnalysisError('INVALID_REQUEST', '用户 ID 必须为正整数: %r' % x)
        out.add(xi)
    if len(out) > 20000:
        raise AnalysisError('INVALID_REQUEST', '单次请求用户数超过上限 20000')
    return sorted(out)


def user_statuses(target_ids, profile_users):
    """请求级检查：任一目标不在 users.dat -> UNKNOWN_USER（规范 §六）。"""
    known = [t for t in target_ids if t in profile_users]
    if not known:
        raise AnalysisError(
            UNKNOWN_USER,
            '目标用户均不存在于清洗快照 users.dat（版本 movielens-1m-v2-clean-v1）',
            {'unknown': [str(t) for t in target_ids]})
    unknown = [str(t) for t in target_ids if t not in profile_users]
    return known, unknown


def _topn(items, n):
    """按 (计数, 热度) 降序取前 n；items: (key, cnt, pop)。"""
    return sorted(items, key=lambda x: (-x[1], -x[2]))[:n]


def cluster_summaries(labels, profile_users, rated, movies, fnames, cfg):
    """
    群体摘要：全部数字来自真实统计（任务书 §2"不得凭模型名生成"）。
    代表性内容 = 群成员训练期 Rating>=4 计数前列的电影（含片名年份与依据计数）。
    """
    rep_cfg = cfg['representative_movies']
    top_n = int(rep_cfg['top_n'])
    min_votes = int(rep_cfg['min_member_votes'])
    groups = {}
    for uid, lab in labels.items():
        if lab is None or lab < 0:
            continue
        groups.setdefault(lab, []).append(uid)
    out = []
    for k in sorted(groups):
        uids = groups[k]
        n = len(uids)
        feats = [profile_users[u]['features'] for u in uids if profile_users[u].get('features')]

        def mean_of(name):
            vals = [f[name] for f in feats if f and name in f]
            return sum(vals) / len(vals) if vals else None

        genre_mean = {fn: mean_of(fn) for fn in fnames if fn.startswith('genre_share_')}
        top_genres = sorted(genre_mean.items(), key=lambda x: -(x[1] or 0))[:3]
        vote = {}
        for u in uids:
            for mid, r in rated.get(u, {}).items():
                if r >= 4:
                    vote[mid] = vote.get(mid, 0) + 1
        pop = {mid: sum(1 for u2 in rated if mid in rated[u2]) for mid in vote}
        reps = []
        for mid, cnt, _ in _topn([(m, c, pop.get(m, 0)) for m, c in vote.items()],
                                 top_n + 5):
            if cnt < min_votes and len(reps) < top_n:
                continue
            if len(reps) >= top_n:
                break
            t, y, _g = movies.get(mid, ('#%d(缺失)' % mid, None, set()))
            reps.append({'movie_id': mid, 'title': t, 'year': y,
                         'high_raters_in_cluster': cnt})
        out.append({
            'cluster_id': k,
            'size': n,
            'avg_rating_mean': mean_of('avg_rating'),
            'n_ratings_mean': mean_of('n_ratings'),
            'high_share_mean': mean_of('high_share'),
            'active_span_days_mean': mean_of('active_span_days'),
            'top_genre_shares': [{'genre': g.replace('genre_share_', ''), 'v': v}
                                 for g, v in top_genres],
            'representative_movies': reps,
            'summary_basis': ('均值与计数均为群内真实统计；代表性内容为群成员'
                              '训练期评分>=4 的人数（>= %d 人）' % min_votes),
        })
    return out


def versions_block(algo, acfg, meta, fit_fp):
    """版本标识块：model_version 由 画像版本|算法|拟合指纹 派生，可复现。"""
    import hashlib
    mv_src = '%s|%s|%s' % (meta['profile_version'], algo, fit_fp)
    return {
        'model_version': 'mdl-%s' % hashlib.sha256(mv_src.encode()).hexdigest()[:10],
        'data_version': acfg['input']['data_version'],
        'profile_version': meta['profile_version'],
        'T1': meta['T1'], 'T2': meta['T2'],
        'code_version': meta['code_version'],
    }


def result_version_of(model_version, assignments, metrics, summaries):
    import hashlib, json
    core = json.dumps({'m': model_version, 'a': assignments,
                       'mt': metrics, 's': summaries}, sort_keys=True,
                      ensure_ascii=False, default=str)
    return 'res-%s' % hashlib.sha256(core.encode()).hexdigest()[:12]


def tool_envelope(algorithm, params, versions, metrics, labels, summaries,
                  limitations, fit_scope, elapsed_ms):
    """组装统一工具信封（字段命名对齐接口扩展规范 §4.2/§2.4）。"""
    return {
        'algorithm': algorithm,
        'algorithm_tool': 'clustering_%s' % algorithm,   # §七 命名约定
        'model_version': versions['model_version'],
        'result_version': versions['result_version'],
        'parameters': params,
        'data_version': versions['data_version'],
        'profile_version': versions['profile_version'],
        'T1': versions['T1'], 'T2': versions['T2'],
        'code_version': versions['code_version'],
        'created_at': versions['created_at'],
        'fit_scope': fit_scope,
        'metrics': metrics,
        'assignments': labels,
        'cluster_summaries': summaries,
        'limitations': limitations,
        'elapsed_ms': elapsed_ms,
    }
