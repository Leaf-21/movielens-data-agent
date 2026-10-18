#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
聚类评价指标（纯标准库实现，成员B）

每个指标附定义与适用说明（任务书要求"实际计算的指标和其适用说明"）：
  · silhouette    轮廓系数：s=(b-a)/max(a,b)，a=同簇平均距离，b=最近异簇平均距离。
                  需要 >=2 簇且存在非孤立样本；孤立样本按惯例 s=0 计入均值。
  · DBI           Davies-Bouldin 指数：簇间"散布比"的最大值平均，越低越好；
                  只适用于有质心的硬划分，噪声点不参与。
  · SSE           簇内平方误差和（到各自质心），K-Means 目标函数值。
  · 噪声占比       DBSCAN 专有：噪声点数 / 总点数。
定义字符串会随工具结果一起输出（metrics[*].definition），
保证前端与报告能原样展示口径。
"""

import math


def euclid(a, b):
    # math.dist 为 C 实现（Python>=3.8），全对距离扫描依赖其性能（环境 3.10）
    return math.dist(a, b)


def centroid(points):
    n = len(points)
    if n == 0:
        return None
    d = len(points[0])
    return [sum(p[i] for p in points) / float(n) for i in range(d)]


def sse(vectors, labels, centroids_):
    """簇内平方误差和。labels 中的 -1（噪声）不计。"""
    s = 0.0
    for v, lab in zip(vectors, labels):
        if lab < 0 or centroids_[lab] is None:
            continue
        d = euclid(v, centroids_[lab])
        s += d * d
    return s


def sample_indices(n, size, seed):
    """确定性抽样下标（sorted 保证可复现）。size>=n 时返回全量。"""
    import random
    if size >= n:
        return list(range(n))
    rng = random.Random(seed * 7919 + size)
    return sorted(rng.sample(range(n), size))


def silhouette_sampled(vectors, labels, sample_idx):
    """
    抽样估计的整体轮廓系数：仅 i 取样本，a/b 均相对**全体**成员计算。
    簇数<2 -> None。孤立样本（同簇只有自己）s 记 0（与全量口径一致）。
    不存储距离矩阵（内存敏感环境实测大矩阵会触发解释器崩溃，见运行报告）。
    """
    clusters = {}
    for j, lab in enumerate(labels):
        if lab < 0:
            continue
        clusters.setdefault(lab, []).append(j)
    ks = sorted(clusters)
    if len(ks) < 2:
        return None
    vals = []
    for i in sample_idx:
        ci = labels[i]
        if ci < 0:
            continue
        si = clusters[ci]
        singleton = len(si) == 1
        if singleton:
            vals.append(0.0)
            continue
        vi = vectors[i]
        a = sum(euclid(vi, vectors[j]) for j in si if j != i) / float(len(si) - 1)
        b = None
        for k2 in ks:
            if k2 == ci:
                continue
            m = sum(euclid(vi, vectors[j]) for j in clusters[k2]) / float(len(clusters[k2]))
            if b is None or m < b:
                b = m
        denom = max(a, b)
        vals.append(0.0 if denom <= 1e-12 else (b - a) / denom)
    return sum(vals) / float(len(vals)) if vals else None


def silhouette(vectors, labels):
    """
    返回 (整体均值, 每簇均值)。孤立样本（同簇只有自己）s 记 0（惯例，需在适用说明注明）。
    簇数 < 2 时返回 (None, {}) —— 如实"无法计算"，不伪造。
    """
    clusters = {}
    for i, lab in enumerate(labels):
        if lab < 0:
            continue
        clusters.setdefault(lab, []).append(i)
    ks = sorted(clusters)
    if len(ks) < 2:
        return None, {}
    per_sample = [0.0] * len(vectors)
    for k in ks:
        idx = clusters[k]
        for i in idx:
            if len(idx) == 1:
                per_sample[i] = 0.0
                continue
            a = sum(euclid(vectors[i], vectors[j]) for j in idx if j != i) / float(len(idx) - 1)
            b = None
            for k2 in ks:
                if k2 == k:
                    continue
                m = sum(euclid(vectors[i], vectors[j]) for j in clusters[k2]) / float(len(clusters[k2]))
                if b is None or m < b:
                    b = m
            denom = max(a, b)
            per_sample[i] = 0.0 if denom <= 1e-12 else (b - a) / denom
    fit_idx = [i for k in ks for i in clusters[k]]
    overall = sum(per_sample[i] for i in fit_idx) / float(len(fit_idx))
    per_cluster = {k: sum(per_sample[i] for i in clusters[k]) / float(len(clusters[k]))
                   for k in ks}
    return overall, per_cluster


def davies_bouldin(vectors, labels, centroids_):
    """
    DBI：R_ij=(s_i+s_j)/d(c_i,c_j)，每簇取 max，再对簇平均。
    要求 >=2 个非空簇且质心互不重合；否则返回 None（不适用）。
    """
    clusters = {}
    for i, lab in enumerate(labels):
        if lab < 0:
            continue
        clusters.setdefault(lab, []).append(i)
    ks = sorted(clusters)
    if len(ks) < 2:
        return None
    scatter = {}
    for k in ks:
        c = centroids_[k]
        if c is None:
            return None
        scatter[k] = sum(euclid(vectors[i], c) for i in clusters[k]) / float(len(clusters[k]))
    total = 0.0
    for i_k in ks:
        worst = 0.0
        for j_k in ks:
            if j_k == i_k:
                continue
            d = euclid(centroids_[i_k], centroids_[j_k])
            if d <= 1e-12:
                return None      # 质心重合，指标不适用，如实报告
            r = (scatter[i_k] + scatter[j_k]) / d
            worst = max(worst, r)
        total += worst
    return total / float(len(ks))


METRIC_DEFINITIONS = {
    'silhouette': ("轮廓系数 mean((b-a)/max(a,b))；a=同簇其他样本平均距离，"
                   "b=最近异簇平均距离；范围[-1,1]，越高越好；"
                   "孤立样本 s 记 0；簇数<2 时为 null。"),
    'davies_bouldin': ("DBI = mean_k max_j≠k (scatter_k+scatter_j)/dist(c_k,c_j)，"
                       "scatter 为簇内到质心平均距离；越低越好；仅硬划分适用，"
                       "噪声点不参与；簇数<2 或质心重合时为 null。"),
    'sse': '簇内平方误差和（到质心距离平方和）；噪声点不计；仅对质心型算法有意义。',
    'noise_ratio': '噪声点比例 count(-1)/N；仅 DBSCAN 类密度算法适用。',
    'k_selection_table': '每个候选 k 在拟合集合上实际计算的 SSE/轮廓系数/DBI。',
    'validation_drift': ("固定模型/质心下，把训练期+验证期累计画像分配回原簇，"
                         "统计目标簇不变率（K-Means 可外推分配；DBSCAN 无预测分配"
                         "语义，记 null 并说明）。只用于参数选择参考，不参与拟合。"),
}
