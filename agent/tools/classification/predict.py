#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分类预测入口（成员A，迭代二）。

两种用法：

1. 命令行（供独立运行、联调与报告复现）::

       python3 agent/tools/classification/predict.py --user-id 4169 --movie-id 260

2. 进程内调用（供成员B的 Agent 层）::

       from classification import predict
       result = predict.classify(user_id=4169, movie_id=260, algorithm=None)

输出遵循《迭代二接口扩展规范》§3.2：``predicted_class`` 取 ``HIGH_RATING`` /
``LOW_RATING``，``positive_probability`` 为算法真实输出的正类概率（未校准时
在 limitations 中说明），``decision_score`` 同步给出。
"""

import argparse
import glob
import json
import os
import pickle
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from common import split as split_mod                              # noqa: E402
from classification import common_features, schemas                # noqa: E402

REPO_DIR = split_mod.REPO_DIR
DEFAULT_ARTIFACTS = os.path.join(REPO_DIR, 'artifacts', 'classification')

LIMITATIONS = [
    '概率未经校准，不能当作真实概率直接展示；决策阈值在验证期选定。',
    '用户或电影在训练期历史不足时，相关特征回退到训练期全局均分，预测可信度下降。',
    '模型只使用 T1 之前的数据训练，不反映 T1 之后的偏好变化。',
]


def _model_dir(slug, artifacts_dir=None, model_version=None):
    base = os.path.join(artifacts_dir or DEFAULT_ARTIFACTS, slug)
    if model_version:
        path = os.path.join(base, model_version)
        if not os.path.isdir(path):
            raise schemas.ToolError(schemas.MODEL_NOT_FOUND,
                                    '模型版本不存在: %s' % model_version,
                                    {'algorithm': slug, 'model_version': model_version})
        return path
    candidates = [p for p in glob.glob(os.path.join(base, '*')) if os.path.isdir(p)]
    if not candidates:
        raise schemas.ToolError(schemas.MODEL_NOT_FOUND,
                                '尚未训练 %s 模型（%s 为空）' % (slug, base),
                                {'algorithm': slug, 'artifacts_dir': base})
    candidates.sort(key=lambda p: os.path.getmtime(p))
    return candidates[-1]


def load_model(slug, artifacts_dir=None, model_version=None):
    """返回 (model, meta)。版本或特征不匹配时抛 VERSION_MISMATCH。"""
    if slug not in schemas.ALGORITHM_SLUGS:
        raise schemas.ToolError(schemas.INVALID_PARAMETER, '未知算法: %s' % slug,
                                {'allowed': list(schemas.ALGORITHM_SLUGS)})
    path = _model_dir(slug, artifacts_dir, model_version)
    meta_path = os.path.join(path, 'meta.json')
    model_path = os.path.join(path, 'model.pkl')
    if not os.path.exists(meta_path) or not os.path.exists(model_path):
        raise schemas.ToolError(schemas.MODEL_NOT_FOUND,
                                '模型文件不完整: %s' % path, {'path': path})
    with open(meta_path, 'r', encoding='utf-8') as f:
        meta = json.load(f)
    if meta.get('feature_version') != schemas.FEATURE_VERSION:
        raise schemas.ToolError(
            schemas.VERSION_MISMATCH,
            '模型特征版本 %s 与当前特征版本 %s 不一致' % (meta.get('feature_version'), schemas.FEATURE_VERSION),
            {'model_feature_version': meta.get('feature_version'),
             'current_feature_version': schemas.FEATURE_VERSION})
    with open(model_path, 'rb') as f:
        model = pickle.load(f)
    return model, meta


def classify(user_id, movie_id, prediction_time=None, algorithm=None,
             artifacts_dir=None, model_version=None, data_dir=None):
    """预测单个 (用户, 电影) 组合。

    ``algorithm`` 为 None 时返回两种算法的对照；为 ``gnb`` / ``cart`` 时只跑一种。
    返回接口扩展规范 §3.2 的结果对象；失败抛 ``schemas.ToolError``。
    """
    slugs = list(schemas.ALGORITHM_SLUGS) if algorithm in (None, '', 'both') else [algorithm]
    for slug in slugs:
        if slug not in schemas.ALGORITHM_SLUGS:
            raise schemas.ToolError(schemas.INVALID_PARAMETER, '未知算法: %s' % slug,
                                    {'allowed': list(schemas.ALGORITHM_SLUGS)})

    dataset = common_features.Dataset(clean_dir=data_dir)
    row, info = dataset.build_row(user_id, movie_id, prediction_time)

    results = []
    for slug in slugs:
        model, meta = load_model(slug, artifacts_dir, model_version)
        score = float(model.predict_proba(row)[0, 1])
        threshold = float(meta.get('threshold', 0.5))
        predicted = schemas.HIGH_RATING if score >= threshold else schemas.LOW_RATING
        explain = None
        if slug == 'cart':
            from classification import modeling
            explain = modeling.tree_path(model, row)
        results.append(schemas.prediction_result(
            algorithm=meta['algorithm'],
            model_version=meta['model_version'],
            predicted_class=predicted,
            positive_probability=round(score, 6),
            decision_score=round(score, 6),
            parameters=meta.get('parameters'),
            metrics={'threshold': threshold,
                     'valid_roc_auc': meta.get('valid_roc_auc'),
                     'valid_pr_auc': meta.get('valid_pr_auc'),
                     'test_roc_auc': meta.get('test_roc_auc'),
                     'test_pr_auc': meta.get('test_pr_auc')},
            limitations=LIMITATIONS + list(info.get('limitations', [])),
            score_type='positive_probability',
            features_used=info['features'],
            explain=explain,
            prediction_time_basis=info['prediction_time_basis'],
        ))

    return {
        'task_type': schemas.TASK_TYPE,
        'status': 'SUCCESS',
        'data_version': split_mod.data_version(dataset.rules),
        'cleaning_rule_version': split_mod.rule_version(dataset.rules),
        'feature_version': schemas.FEATURE_VERSION,
        'split_version': schemas.SPLIT_VERSION,
        'target': {'user_id': int(user_id), 'movie_id': int(movie_id)},
        'T1': dataset.T1,
        'T2': dataset.T2,
        'results': results,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description='迭代二分类预测')
    ap.add_argument('--user-id', type=int, required=True)
    ap.add_argument('--movie-id', type=int, required=True)
    ap.add_argument('--prediction-time', type=int, default=None,
                    help='历史事件回测时给出目标事件时间戳；不给出则按训练期快照预测')
    ap.add_argument('--algorithm', default='both', choices=('both',) + schemas.ALGORITHM_SLUGS)
    ap.add_argument('--artifacts-dir', default=None)
    ap.add_argument('--model-version', default=None)
    ap.add_argument('--data-dir', default=None)
    args = ap.parse_args(argv)

    try:
        result = classify(args.user_id, args.movie_id, args.prediction_time,
                          args.algorithm, args.artifacts_dir, args.model_version, args.data_dir)
    except schemas.ToolError as e:
        print(json.dumps(e.to_dict(), ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
