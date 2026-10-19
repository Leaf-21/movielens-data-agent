#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模型构建、阈值选择与评价（供 train.py / predict.py 共用）。

两种算法：
- ``gnb``：StandardScaler + GaussianNB。标准化器在 Pipeline 内，只 fit 训练集。
- ``cart``：DecisionTreeClassifier(criterion="entropy")。课件讲的是信息熵/
  信息增益与 C4.5；sklearn 的实现是二叉 CART，属对 ID3 多叉划分的近似，
  模型卡中已注明。

评价口径：验证期选超参与阈值，测试期只评一次。主指标 ROC-AUC、PR-AUC
（与作业四一致），Precision/Recall/F1 在冻结阈值后作为辅助指标。
"""

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.naive_bayes import GaussianNB
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

from . import schemas

DEFAULT_PARAMS = {
    'gnb': {'var_smoothing': 1e-9},
    'cart': {'max_depth': 12, 'min_samples_leaf': 100},
}

# 验证期网格（小规模，避免在 70 万行上做昂贵搜索）
PARAM_GRID = {
    'gnb': [{'var_smoothing': 1e-9}, {'var_smoothing': 1e-8}],
    'cart': [
        {'max_depth': 8, 'min_samples_leaf': 200},
        {'max_depth': 12, 'min_samples_leaf': 100},
        {'max_depth': 16, 'min_samples_leaf': 50},
    ],
}


def make_model(slug, params=None, seed=42):
    params = dict(DEFAULT_PARAMS.get(slug, {}))
    params.update(params or {})
    if slug == 'gnb':
        return Pipeline([
            ('scaler', StandardScaler()),
            ('clf', GaussianNB(var_smoothing=float(params.get('var_smoothing', 1e-9)))),
        ]), params
    if slug == 'cart':
        return DecisionTreeClassifier(
            criterion='entropy',
            max_depth=int(params.get('max_depth', 12)),
            min_samples_leaf=int(params.get('min_samples_leaf', 100)),
            random_state=seed,
        ), params
    raise schemas.ToolError(schemas.INVALID_PARAMETER, '未知算法: %s' % slug,
                            {'algorithm': slug, 'allowed': list(schemas.ALGORITHM_SLUGS)})


def scores(model, X):
    """正类分数：优先概率，其次 decision_function。"""
    if hasattr(model, 'predict_proba'):
        return model.predict_proba(X)[:, 1]
    if hasattr(model, 'decision_function'):
        raw = model.decision_function(X)
        return 1.0 / (1.0 + np.exp(-raw))
    raise schemas.ToolError(schemas.ALGORITHM_ERROR, '模型不支持概率或决策分数输出')


def best_threshold(y_true, score, max_positive_rate=None):
    """在给定集合上按 F1 选阈值（只允许在验证集调用）。

    ``max_positive_rate`` 给定时，只在"预测正类比例不超过该值"的候选阈值中选。
    用途：朴素贝叶斯的后验未经校准，纯 F1 最优会退化到"几乎全判正类"
    （实测阈值 0.022、判定率 90%），加入判定率约束可得到可解释的操作点。
    """
    y_true = np.asarray(y_true).astype(np.int8)
    order = np.argsort(-score)
    y_sorted = y_true[order]
    tp = np.cumsum(y_sorted)
    fp = np.cumsum(1 - y_sorted)
    n = len(y_true)
    positives = int(y_true.sum())
    fn = positives - tp
    precision = tp / np.maximum(tp + fp, 1)
    recall = tp / np.maximum(positives, 1)
    f1 = 2 * precision * recall / np.maximum(precision + recall, 1e-12)
    rate = (tp + fp) / float(n)
    if max_positive_rate is not None:
        allowed = rate <= max_positive_rate
        if allowed.any():
            f1 = np.where(allowed, f1, -1.0)
    k = int(np.argmax(f1))
    threshold = float(score[order][k])
    # 阈值取「>=」判定，避免把分数相同的样本切到负类
    return min(max(threshold, 1e-6), 1.0 - 1e-6), float(f1[k])


def evaluate(model, X, y_true, threshold=None, max_positive_rate=None):
    """返回指标字典。``threshold`` 为 None 时在本次数据上按 F1 重新选阈值。"""
    score = scores(model, X)
    y_true = np.asarray(y_true).astype(np.int8)
    result = {
        'n': int(len(y_true)),
        'positive_rate': round(float(y_true.mean()), 6),
        'roc_auc': round(float(roc_auc_score(y_true, score)), 6) if len(np.unique(y_true)) > 1 else None,
        'pr_auc': round(float(average_precision_score(y_true, score)), 6) if len(np.unique(y_true)) > 1 else None,
    }
    if threshold is None:
        threshold, _ = best_threshold(y_true, score, max_positive_rate=max_positive_rate)
    pred = (score >= threshold).astype(np.int8)
    cm = confusion_matrix(y_true, pred, labels=[0, 1])
    result.update({
        'threshold': round(float(threshold), 6),
        'accuracy': round(float(accuracy_score(y_true, pred)), 6),
        'precision': round(float(precision_score(y_true, pred, zero_division=0)), 6),
        'recall': round(float(recall_score(y_true, pred, zero_division=0)), 6),
        'f1': round(float(f1_score(y_true, pred, zero_division=0)), 6),
        'predicted_positive_rate': round(float(pred.mean()), 6),
        'confusion_matrix': {
            'tn': int(cm[0][0]), 'fp': int(cm[0][1]),
            'fn': int(cm[1][0]), 'tp': int(cm[1][1]),
        },
    })
    return result, score


def evaluate_strata(model, X, y_true, strata, threshold):
    """按分层（如「用户是否在训练期出现」）分别评价。"""
    out = {}
    score = scores(model, X)
    for name, mask in strata.items():
        mask = np.asarray(mask, dtype=bool)
        if not mask.any():
            out[name] = {'n': 0}
            continue
        y = y_true[mask]
        s = score[mask]
        pred = (s >= threshold).astype(np.int8)
        item = {
            'n': int(mask.sum()),
            'positive_rate': round(float(y.mean()), 6),
            'precision': round(float(precision_score(y, pred, zero_division=0)), 6),
            'recall': round(float(recall_score(y, pred, zero_division=0)), 6),
            'f1': round(float(f1_score(y, pred, zero_division=0)), 6),
        }
        if len(np.unique(y)) > 1:
            item['roc_auc'] = round(float(roc_auc_score(y, s)), 6)
            item['pr_auc'] = round(float(average_precision_score(y, s)), 6)
        out[name] = item
    return out


def tree_path(model, row):
    """返回决策树的决策路径（仅 cart 有意义）。"""
    clf = model
    if isinstance(model, Pipeline):
        clf = model.steps[-1][1]
    if not hasattr(clf, 'tree_'):
        return None
    node = 0
    tree = clf.tree_
    path = []
    while tree.children_left[node] != tree.children_right[node]:
        feature = int(tree.feature[node])
        threshold = float(tree.threshold[node])
        value = float(row[0, feature])
        go_left = value <= threshold
        path.append({
            'node': int(node),
            'feature_index': feature,
            'threshold': round(threshold, 6),
            'value': round(value, 6),
            'direction': 'left' if go_left else 'right',
        })
        node = int(tree.children_left[node]) if go_left else int(tree.children_right[node])
    path.append({'node': int(node), 'leaf_samples': int(tree.n_node_samples[node]),
                 'leaf_positive_rate': round(float(tree.value[node][0][1] / max(tree.n_node_samples[node], 1)), 6)})
    return path
