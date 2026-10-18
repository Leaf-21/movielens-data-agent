#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
迭代二自然语言路由（成员B）

职责：把 POST /api/analysis/{类别}/tasks 的请求体路由成结构化的分析计划。
与迭代一 parser.py 同构的两级思路：
  1) 关键词规则优先（本机 LLM 默认关闭，规则必须全路径可用）；
  2) 规则未命中且 LLM 可用时可选兜底（沿用 llm_used 语义）；
  3) 信息不足时如实返回 INVALID_REQUEST 提示，绝不猜一个算法/用户来"制造结果"
     （接口扩展规范 §七 三规则）。

约定：
  · URL 类别是权威（规范 §2.2），query 明显描述别的类别 -> 报错引导换路径；
  · query 与 body 字段冲突时 body 优先，notes 说明（同 parser.py 的模式）；
  · 未指定算法 -> 聚类类别内默认跑登记的两个算法做对照（K-Means 主视角 +
    DBSCAN 密度/噪声视角），不是"猜"，是配置驱动的完整对照，结果分列；
  · 参数只接受 analysis.json allowed_parameters 白名单，且按算法裁剪：
    对某算法非法但对他法合法 -> 只传给合法方并在 notes 登记。
"""

import os
import re
import sys

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)
_TOOLS_DIR = os.path.join(os.path.dirname(_SRC_DIR), 'tools')
for _p in (_TOOLS_DIR, os.path.join(_TOOLS_DIR, 'clustering')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config  # noqa: E402
import registry  # noqa: E402
from clustering.schemas import (validate_parameters, normalize_targets)  # noqa: E402
from common import (AnalysisError, INVALID_REQUEST,      # noqa: E402
                    VERSION_MISMATCH)

URL_CATEGORY = {'clustering': 'clustering',
                'classification': 'classification',
                'dimensionality-reduction': 'dimensionality_reduction'}

# 类别关键词（小写匹配；中文直接子串）
CATEGORY_KEYWORDS = {
    'clustering': ['聚类', '分群', '群体', '人群', '簇', 'cluster', 'kmeans',
                   'k-means', 'k 均值', 'k均值', 'dbscan', '密度聚类'],
    'classification': ['分类', '预测', '会喜欢', '会不会喜欢', '高分', '是否喜欢',
                       'predict', 'classification'],
    'dimensionality_reduction': ['降维', '主成分', '坐标', '二维', '投影',
                                 '可视化', 'pca', 't-sne', 'tsne', 'umap'],
}

ALGO_KEYWORDS = {
    'clustering': {'kmeans': ['kmeans', 'k-means', 'k 均值', 'k均值'],
                   'dbscan': ['dbscan', '密度聚类', '密度可达']},
}

_USER_ID_RES = (re.compile(r'用户\s*(\d+)'),
                re.compile(r'user[_\s]*(?:id)?\s*[=:：]?\s*(\d+)', re.I))


def _extract_user_ids(text):
    ids = set()
    for rx in _USER_ID_RES:
        for m in rx.finditer(text or ''):
            ids.add(int(m.group(1)))
    return sorted(ids)


def _detect_categories(text):
    low = (text or '').lower()
    return [c for c, kws in CATEGORY_KEYWORDS.items()
            if any(k.lower() in low for k in kws)]


def route(url_category, payload):
    """
    返回 plan dict：
      {task_type, algorithms:[...], user_ids:[...], parameters:{...},
       data_version, profile_version, notes}
    协议级问题抛 AnalysisError(INVALID_REQUEST/VERSION_MISMATCH/
    INVALID_PARAMETER/MODEL_NOT_FOUND/UNKNOWN_USER)。
    """
    if url_category not in URL_CATEGORY:
        raise AnalysisError(INVALID_REQUEST, '未知分析类别: %s' % url_category)
    category = URL_CATEGORY[url_category]
    if not isinstance(payload, dict):
        raise AnalysisError(INVALID_REQUEST, '请求体必须是 JSON 对象')

    acfg = config.load_analysis()
    rcfg = config.load_rules()
    text = payload.get('query') or payload.get('prompt') or ''
    if not isinstance(text, str) or len(text) > 2000:
        raise AnalysisError(INVALID_REQUEST, 'query 必须是不超过 2000 字符的字符串')
    notes = []

    # ---- 0) 类别一致性：URL 权威，query 描述别处 -> 引导（规范 §2.2/§七）----
    det = _detect_categories(text)
    if det and category not in det:
        raise AnalysisError(
            INVALID_REQUEST,
            '查询内容属于 %s 类别，请在 /api/analysis/%s/tasks 提交'
            % ('/'.join(det), 'clustering' if 'clustering' in det
               else ('classification' if 'classification' in det
                     else 'dimensionality-reduction')))
    if len(det) > 1:
        raise AnalysisError(
            INVALID_REQUEST,
            '查询同时涉及多个分析类别（%s），一次任务只做一个类别，请拆分提交'
            % '、'.join(det))

    # ---- 1) 版本校验（配置口径唯一，不匹配即 VERSION_MISMATCH）----
    dv = payload.get('data_version')
    if dv is None:
        dv = acfg['input']['data_version']
    else:
        dv_known, err = config.validate_data_version(dv, rcfg)
        if err:
            # 迭代一码 INVALID_DATA_VERSION 在分析接口按规范 §2.1 归为
            # VERSION_MISMATCH（统一分析错误码集，不向调用方泄漏双码表）
            raise AnalysisError('VERSION_MISMATCH',
                                '%s（分析任务要求版本 %s）'
                                % (err['message'], acfg['input']['data_version']),
                                err.get('detail'))
        if dv != acfg['input']['data_version']:
            raise AnalysisError(
                VERSION_MISMATCH,
                '本迭代分析口径固定使用 %s，请求版本 %s 与画像/时间窗不匹配'
                % (acfg['input']['data_version'], dv))
    pv = payload.get('profile_version')
    if pv is None:
        pv = acfg['profile_version']
    elif pv != acfg['profile_version']:
        raise AnalysisError(VERSION_MISMATCH,
                            '画像版本 %r 未登记（当前: %s）' % (pv, acfg['profile_version']))

    # ---- 2) 算法解析（配置注册表权威）----
    impl = registry.algorithm_names(category, acfg)
    algo_raw = payload.get('algorithm')
    if isinstance(algo_raw, str) and algo_raw.strip():
        slug = algo_raw.strip().lower().replace('-', '').replace('_', '')
        alias = {'kmeans': 'kmeans', 'k均值': 'kmeans', 'dbscan': 'dbscan'}
        algo = alias.get(slug, slug)
        if algo not in impl:
            raise AnalysisError(
                'MODEL_NOT_FOUND',
                '算法 %r 在类别 %s 下未登记实现；可用: %s' % (algo_raw, category, impl or '无'))
        algorithms = [algo]
        if algo not in _query_algos(text, category):
            notes.append('算法由请求字段指定（query 未提及）')
    else:
        qalgos = _query_algos(text, category)
        if len(qalgos) > 1:
            algorithms = sorted(qalgos)  # 登记顺序执行，保证结果顺序确定
            notes.append('query 同时提到多种算法，逐一执行并分列结果')
        elif len(qalgos) == 1:
            algorithms = qalgos
        else:
            if not impl:
                raise AnalysisError(
                    'MODEL_NOT_FOUND',
                    '类别 %s 尚无登记算法。已注册工具: %s'
                    % (category, registry.implemented_tools(acfg)))
            algorithms = impl
            notes.append('未指定算法，按登记顺序执行 %s 做对照' % impl)

    # ---- 3) 目标用户 ----
    body_ids = []
    if payload.get('user_id') is not None:
        body_ids.append(payload['user_id'])
    if payload.get('user_ids') is not None:
        if not isinstance(payload['user_ids'], list):
            raise AnalysisError(INVALID_REQUEST, 'user_ids 必须是数组')
        body_ids += payload['user_ids']
    if body_ids:
        user_ids = normalize_targets({'user_ids': body_ids})
        qids = _extract_user_ids(text)
        extra = [x for x in qids if x not in set(user_ids)]
        if extra:
            notes.append('query 提到的用户 %s 未在请求字段中，以请求字段为准' % extra)
        if not qids:
            notes.append('目标用户来自请求字段（query 未含用户 ID）')
    else:
        user_ids = _extract_user_ids(text)
        if not user_ids:
            raise AnalysisError(
                INVALID_REQUEST,
                '无法确定目标用户：请在 user_id/user_ids 字段给出，或在 query 中写明'
                '"用户 1000" 之类的 ID；Agent 不会替你挑选用户')

    # ---- 3b) 创建时快速拒绝"全部目标用户未知"（规范 §六，不产生僵尸任务）。
    #      users.dat 可读时做请求级检查；不可读则留给工具执行时如实报错。----
    try:
        import build_profile as _bp
        known_set = _bp.load_users(
            config.resolve_repo_path(acfg['input']['clean_dir']))
        if all(u not in known_set for u in user_ids):
            raise AnalysisError(
                'UNKNOWN_USER',
                '目标用户均不存在于 users.dat（清洗快照 %s）' % acfg['input']['data_version'],
                {'unknown': [str(u) for u in user_ids]})
        unknown_some = [u for u in user_ids if u not in known_set]
        if unknown_some:
            notes.append('用户 %s 不在 users.dat，将按 UNKNOWN_USER 逐用户标注，'
                         '不给出归属' % unknown_some)
            user_ids = [u for u in user_ids if u in known_set]
            if not user_ids:
                raise AnalysisError('UNKNOWN_USER', '过滤未知用户后无可执行目标')
    except AnalysisError:
        raise
    except Exception:
        pass  # 快照不可读不在此处判死，执行环节兜底

    # ---- 4) 参数白名单（按算法裁剪）----
    raw_params = payload.get('parameters') or {}
    if not isinstance(raw_params, dict):
        raise AnalysisError(INVALID_REQUEST, 'parameters 必须是对象')
    allowed = acfg.get('allowed_parameters', {})
    params_by_algo = {}
    unknown_keys = set(raw_params) - set().union(
        *[set(allowed.get(a, {})) for a in algorithms]) if algorithms else set(raw_params)
    if unknown_keys:
        raise AnalysisError(
            'INVALID_PARAMETER',
            '参数 %s 不在任何所选算法的允许清单内；允许清单: %s'
            % (sorted(unknown_keys), {a: sorted(allowed.get(a, {})) for a in algorithms}))
    for a in algorithms:
        sub = {k: v for k, v in raw_params.items() if k in allowed.get(a, {})}
        dropped = sorted(set(raw_params) - set(sub))
        params_by_algo[a] = validate_parameters(a, sub, allowed)
        if dropped:
            notes.append('参数 %s 对算法 %s 不适用，已忽略' % (dropped, a))

    plan = {
        'task_type': category,
        'algorithms': algorithms,
        'user_ids': user_ids,
        'parameters_by_algorithm': params_by_algo,
        'data_version': dv,
        'profile_version': pv,
        'notes': '；'.join(notes) if notes else
                 '按 query 与请求字段解析：类别=%s，算法=%s，用户=%d 个'
                 % (category, algorithms, len(user_ids)),
    }
    return plan


def _query_algos(text, category):
    low = (text or '').lower()
    found = []
    for algo, kws in ALGO_KEYWORDS.get(category, {}).items():
        if any(k.lower() in low for k in kws):
            found.append(algo)
    return [a for a in found if a in _impl_names(category)]


def _impl_names(category):
    try:
        return registry.algorithm_names(category)
    except Exception:
        return []
