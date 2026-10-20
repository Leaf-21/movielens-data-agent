#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
降维工具公共件（成员C）

两种降维工具（PCA / t-SNE）与 run_fit 共用：
  · 输入校验、用户集合选择（含"未传 user_ids=已登记分析集"口径）；
  · 拟合/投影/可视化坐标系（同一用户集合、同一 profile-v1 向量）；
  · 降维前/降维后聚类对照（K-Means + DBSCAN，参数取自 analysis.json 登记值）；
  · 统一信封组装（接口扩展规范 §5.2）与派生 result_version。

严格口径（数据与实验规范 §五 / 任务书 §2）：
  · 降维模型只用 profile-v1 的拟合用户（status=OK，即训练期画像）拟合；
    其余用户（历史不足但有向量 / 无训练记录）按登记方式投影或如实给出 None，
    绝不补值、绝不冒充拟合用户。
  · 信息保留指标随算法而异，只在能定义时报告，否则 null + 说明；
    PCA 报告各分量解释方差比；t-SNE 不报告解释方差（不适用，记 null）。
  · 资源开销只报告真实测量项：elapsed_ms 真实测量；峰值内存用标准库
    tracemalloc 在同一进程内测量（见 memory 字段的 method 说明）。
"""

import datetime
import hashlib
import json
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))                 # .../dimensionality_reduction
_TOOLS_DIR = os.path.dirname(_HERE)                                # agent/tools
_CLUSTERING_DIR = os.path.join(_TOOLS_DIR, 'clustering')
_SRC_DIR = os.path.join(os.path.dirname(_TOOLS_DIR), 'src')        # agent/src
# 顺序关键：agent/tools 下的 common 是成员A的数据包（无 AnalysisError），
# 必须先找到 clustering/common.py，故 _TOOLS_DIR 不入 path。
for _p in (_CLUSTERING_DIR, _SRC_DIR, _HERE):
    if _p in sys.path:
        sys.path.remove(_p)
    sys.path.insert(0, _p)

import config                                              # noqa: E402
import build_profile as bp                                 # noqa: E402
import metrics as M                                        # noqa: E402
from common import (AnalysisError, ALGORITHM_ERROR,        # noqa: E402
                    INVALID_PARAMETER, now_utc)
import schemas as _S                                       # noqa: E402  (聚类侧约定)
from kmeans_tool import fit_one_k                          # noqa: E402  (复用同一拟合口径)
from dbscan_tool import dbscan as dbscan_run               # noqa: E402  (复用同一密度口径)

DR_CATEGORY = 'dimensionality_reduction'

# 降维参数白名单（analysis.json allowed_parameters -> 校验范围）
DR_ALLOWED = {
    'target_dimensions': [2, 27],
    'information_retention_threshold': [0.0, 1.0],
    'clustering_k': [2, 30],
    'clustering_seed': [0, 2147483647],
    'clustering_eps': [0.01, 50.0],
    'clustering_min_samples': [3, 100],
    'perplexity': [5.0, 50.0],
    'n_iter': [250, 5000],
    'learning_rate': [10.0, 1000.0],
    'early_exaggeration': [1.0, 40.0],
    'knn_k': [5, 50],
    'random_state': [0, 2147483647],
}

# 组件内坐标轴说明（前端"轴含义"必须可见，数据与实验规范 §五.6）
AXIS_NOTE = {
    ('pca', 'pc1'): '第1主成分（线性组合，方差最大方向；方差来自画像 z-score 空间）',
    ('pca', 'pc2'): '第2主成分（与第1主成分正交，解释剩余方差最大方向）',
    ('tsne', 'tsne1'): 't-SNE 嵌入维1（非线性；轴为抽象坐标，无线性特征含义）',
    ('tsne', 'tsne2'): 't-SNE 嵌入维2（非线性；轴为抽象坐标，无线性特征含义）',
}

TSNE_LIMITATIONS = [
    't-SNE 不保留全局结构：点间距离与簇间距离不能直接当作相似度或簇大小解读，'
    '不同运行的簇位置/朝向可旋转翻转（本实现固定 random_state 保证同机可复现）。',
    't-SNE 没有统一的信息保留指标，本工具不报告"解释方差"，'
    'information_retention 为 null；可比较的只有与簇结构相关的指标（见 clustering_comparison）。',
    't-SNE 的困惑度 perplexity 受样本数限制（需 3*perplexity < n）；大样本时耗时显著高于 PCA。',
]

TRUST_LIMITATIONS = [
    '降维模型只在 profile-v1 的拟合用户（训练期画像 OK 用户）上拟合；'
    '历史不足/无训练记录用户为样本外投影，可靠性低(reliability_low=true)，'
    '不得据此下群体结论。',
    '二维图只用于观察结构，不能仅凭视觉分离宣称算法更优（数据与实验规范 §五.6）；'
    '优劣结论必须同时参考 clustering_comparison 的指标。',
]


# ---------------------------------------------------------------------------
# 参数与用户集合
# ---------------------------------------------------------------------------

def validate_dr_params(params):
    out = {}
    for k, v in (params or {}).items():
        if k not in DR_ALLOWED:
            raise AnalysisError(INVALID_PARAMETER,
                                '降维不支持参数 %r；允许参数: %s'
                                % (k, sorted(DR_ALLOWED)),
                                {'allowed': sorted(DR_ALLOWED)})
        lo, hi = DR_ALLOWED[k]
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not (lo <= v <= hi):
            raise AnalysisError(INVALID_PARAMETER,
                                '参数 %s=%r 超出允许范围 [%s, %s]' % (k, v, lo, hi))
        out[k] = v
    return out


def normalize_user_ids(payload):
    """
    user_ids 可缺省：未传时使用已登记分析集（profile-v1 全部拟合用户）。
    用户集合语义是"要展示/分析的用户"，不能为空集合，也不做用户代选。
    """
    raw = payload.get('user_ids')
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise AnalysisError('INVALID_REQUEST', 'user_ids 必须是数组或 null')
    out = set()
    for x in raw:
        try:
            xi = int(str(x).strip())
        except (TypeError, ValueError):
            raise AnalysisError('INVALID_REQUEST', '无法解析的用户 ID: %r' % x)
        if xi <= 0:
            raise AnalysisError('INVALID_REQUEST', '用户 ID 必须为正整数: %r' % x)
        out.add(xi)
    if not out:
        raise AnalysisError('INVALID_REQUEST',
                            'user_ids 为空数组；不传表示使用已登记分析集，传则至少一个用户')
    return sorted(out)


def versions_of(acfg, rcfg, meta, method, params):
    """版本标识块：model_version 由 画像版本|降维方法|拟合指纹 派生，可复现。"""
    fit_fp = '%s|%s|%s|%s' % (meta['profile_version'], method,
                              json.dumps(params, sort_keys=True, default=str),
                              meta['input_sha256']['ratings.dat'][:12])
    mv_src = '%s|%s|%s' % (meta['profile_version'], method, fit_fp)
    return {
        'model_version': 'dr-%s' % hashlib.sha256(mv_src.encode()).hexdigest()[:10],
        'data_version': acfg['input']['data_version'],
        'profile_version': meta['profile_version'],
        'feature_version': 'profile-v1',      # 画像即输入特征
        'T1': meta.get('T1_epoch'), 'T2': meta.get('T2_epoch'),
        'T1_date': meta.get('T1'), 'T2_date': meta.get('T2'),
        'code_version': meta.get('code_version'),
        'created_at': now_utc(),
    }


def result_version_of(model_version, coordinates, comparison, info):
    core = json.dumps({'m': model_version, 'c': coordinates, 'cc': comparison,
                       'i': info}, sort_keys=True, ensure_ascii=False, default=str)
    return 'drres-%s' % hashlib.sha256(core.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# 聚类对照（降维前 / 降维后使用同一用户集合、同一聚类算法与参数）
# ---------------------------------------------------------------------------

def _kmeans_compare(orig_vecs, red_vecs, params, seed):
    """同一聚类算法（K-Means，固定 k）分别在原始空间与降维空间拟合。"""
    k = int(params.get('clustering_k', 6))
    if not (2 <= k <= len(orig_vecs)):
        raise AnalysisError(INVALID_PARAMETER,
                            'clustering_k=%d 需满足 2<=k<=用户数(%d)' % (k, len(orig_vecs)))
    max_iter = 100
    out = {}
    for name, vecs in (('before', orig_vecs), ('after', red_vecs)):
        dim = len(vecs[0])
        fit = fit_one_k(vecs, k, seed, max_iter, 1e-6)
        cent = fit['centers']
        sh, _per = M.silhouette(vecs, fit['labels'])
        out[name] = {
            'dimensions': dim,
            'labels': fit['labels'],
            'metrics': {
                'silhouette': sh,
                'davies_bouldin': M.davies_bouldin(vecs, fit['labels'], cent),
                'sse': M.sse(vecs, fit['labels'], cent),
            },
        }
    return {
        'algorithm': 'kmeans',
        'algorithm_tool': 'clustering_kmeans',
        'parameters': {'k': k, 'seed': seed, 'max_iter': max_iter, 'tol': 1e-6,
                       'init': 'kmeans++'},
        'same_user_set': True,
        'before': {'dimensions': out['before']['dimensions'],
                   'metrics': out['before']['metrics']},
        'after': {'dimensions': out['after']['dimensions'],
                  'metrics': out['after']['metrics']},
        'delta': {m: (_diff(out['after']['metrics'][m], out['before']['metrics'][m]))
                  for m in ('silhouette', 'davies_bouldin', 'sse')},
        'labels_before': out['before']['labels'],
        'labels_after': out['after']['labels'],
        'metric_definitions': {
            'silhouette': M.METRIC_DEFINITIONS['silhouette'],
            'davies_bouldin': M.METRIC_DEFINITIONS['davies_bouldin'],
            'sse': M.METRIC_DEFINITIONS['sse'],
        },
        'comparability_note': ('降维前后使用完全相同的用户集合与同一聚类算法/k 值；'
                               'SSE 在降维空间天然更小，不能跨空间直接比较绝对大小，'
                               '应以轮廓系数与 DBI（无量纲）为主要参照。'),
    }


def _dbscan_compare(orig_vecs, red_vecs, eps, min_samples):
    """DBSCAN 为密度算法：eps 尺度随空间变化，显式声明不跨空间比较 eps。"""
    out = {}
    for name, vecs in (('before', orig_vecs), ('after', red_vecs)):
        labels, n_clusters = dbscan_run(vecs, eps, min_samples)
        n_noise = sum(1 for l in labels if l < 0)
        out[name] = {
            'dimensions': len(vecs[0]),
            'n_clusters': n_clusters,
            'noise_ratio': n_noise / float(len(labels)),
            'silhouette': M.silhouette(vecs, labels)[0],
        }
    return {
        'algorithm': 'dbscan',
        'algorithm_tool': 'clustering_dbscan',
        'parameters': {'eps': eps, 'min_samples': min_samples},
        'same_user_set': True,
        'before': out['before'],
        'after': out['after'],
        'metric_definitions': {
            'silhouette': M.METRIC_DEFINITIONS['silhouette'],
            'noise_ratio': M.METRIC_DEFINITIONS['noise_ratio'],
        },
        'comparability_note': ('DBSCAN 的 eps 是绝对距离阈值，原始 27 维与 2 维空间的'
                               '距离尺度不同，同一 eps 不代表同等密度条件；本次使用同一 eps '
                               '仅作记录，簇数/噪声比例差异不能直接归因于降维方法。'),
    }


def _diff(a, b):
    if a is None or b is None:
        return None
    return a - b


def build_clustering_comparison(orig_vecs, red_vecs, params, seed):
    """K-Means 对照必做；DBSCAN 对照仅当显式给出 clustering_eps 时追加
    （eps 是绝对距离阈值，跨维度不可直接沿用，要求调用方显式指定）。"""
    out = {'kmeans': _kmeans_compare(orig_vecs, red_vecs, params, seed)}
    if params.get('clustering_eps') is not None:
        eps = float(params['clustering_eps'])
        ms = int(params.get('clustering_min_samples', 15))
        out['dbscan'] = _dbscan_compare(orig_vecs, red_vecs, eps, ms)
    return out


# ---------------------------------------------------------------------------
# 用户集合装配（拟合用户 + 样本外投影用户）
# ---------------------------------------------------------------------------

def resolve_users(acfg, rcfg, target_ids, quiet=True):
    """
    返回 dict：
      prof_path, meta, fit_uids, orig_vectors (拟合用户 z-score 向量),
      out_of_sample: {uid: {'vector': [...], 'status': str, 'note': str}}
      missing (不在 users.dat 的请求 ID)
    """
    prof_path, meta = bp.build_profile(acfg, rcfg, force=False, quiet=quiet)
    users = bp.load_profile(prof_path)
    fit_uids = sorted(u for u, r in users.items() if r.get('fit') and r.get('vector'))
    if len(fit_uids) < 3:
        raise AnalysisError(ALGORITHM_ERROR,
                            '拟合用户不足 3 人，无法进行有意义的降维',
                            {'n_fit': len(fit_uids)})
    keep = set(target_ids) if target_ids else set(fit_uids)
    fit_sel = [u for u in fit_uids if u in keep]
    oos = {}
    missing = []
    for u in sorted(keep):
        rec = users.get(u)
        if rec is None:
            missing.append(str(u))
            continue
        if rec.get('fit'):
            continue
        oos[u] = {'vector': rec.get('vector'), 'features': rec.get('features'),
                  'status': rec.get('status'), 'note': rec.get('note'),
                  'reliability_low': True}
    if len(fit_sel) < 3:
        raise AnalysisError(ALGORITHM_ERROR,
                            '所选用户中可用于拟合降维模型的用户不足 3 人（%d）' % len(fit_sel),
                            {'n_fit_selected': len(fit_sel),
                             'hint': '降维模型只在训练期画像用户上拟合，请加入更多有历史的用户'})
    return {
        'prof_path': prof_path, 'meta': meta,
        'fit_uids': fit_sel,
        'orig_vectors': [users[u]['vector'] for u in fit_sel],
        'out_of_sample': oos,
        'missing': missing,
    }


def project_coordinates(fit_uids, fit_coords, oos, projector):
    """
    组装坐标列表：拟合用户给二维坐标；样本外用户按 projector(vector) 投影，
    无向量（无训练记录）时坐标 null，绝不补值。
    """
    coords = []
    for uid, xy in zip(fit_uids, fit_coords):
        coords.append({'user_id': uid, 'x': float(xy[0]), 'y': float(xy[1]),
                       'status': 'SUCCESS', 'reliability_low': False,
                       'is_fit_user': True})
    for uid in sorted(oos):
        rec = oos[uid]
        vec = rec.get('vector')
        if vec is None:
            coords.append({'user_id': uid, 'x': None, 'y': None,
                           'status': 'NO_TRAIN_HISTORY', 'reliability_low': True,
                           'is_fit_user': False, 'note': rec.get('note')})
            continue
        xy = projector(vec)
        coords.append({'user_id': uid, 'x': float(xy[0]), 'y': float(xy[1]),
                       'status': 'PROJECTED_FROM_FITTED_MODEL',
                       'reliability_low': True, 'is_fit_user': False,
                       'note': rec.get('note')})
    return coords


def envelope(method, algorithm_name, algorithm_source, params, versions,
             orig_dim, red_dim, info_retention, resource, coords, comparison,
             fit_scope, limitations, axis_meaning, extra=None):
    env = {
        'algorithm': method,
        'algorithm_name': algorithm_name,
        'algorithm_tool': 'dimensionality_reduction_%s' % method,
        'algorithm_source': algorithm_source,
        'model_version': versions['model_version'],
        'result_version': None,
        'parameters': params,
        'data_version': versions['data_version'],
        'profile_version': versions['profile_version'],
        'feature_version': versions['feature_version'],
        'T1': versions['T1'], 'T2': versions['T2'],
        'code_version': versions['code_version'],
        'created_at': versions['created_at'],
        'original_dimensions': orig_dim,
        'reduced_dimensions': red_dim,
        'axis_meaning': axis_meaning,
        'fit_scope': fit_scope,
        'information_retention': info_retention,
        'resource_usage': resource,
        'coordinates': coords,
        'clustering_comparison': comparison,
        'limitations': limitations,
    }
    if extra:
        env.update(extra)
    env['result_version'] = result_version_of(
        env['model_version'], coords, comparison, info_retention)
    return env


def write_envelope_file(res, out_path):
    d = os.path.dirname(os.path.abspath(out_path))
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = out_path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    os.replace(tmp, out_path)


def fail_stdout_and_exit2(e):
    json.dump({'status': 'FAILED', 'error': e.to_error_dict()},
              sys.stdout, ensure_ascii=False)
    sys.stdout.write('\n')
    sys.exit(2)
