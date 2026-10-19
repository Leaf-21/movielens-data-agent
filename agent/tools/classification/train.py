#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""训练与评价入口（成员A，迭代二）。

流程（数据与实验规范 §二）：

1. 读清洗快照，按 T1/T2 切分；
2. 在**训练期**拟合特征处理与模型；
3. 在**验证期**做超参与阈值选择；
4. 方案冻结后，在**测试期**只评价一次；
5. 保存模型、元数据、指标、实验记录与模型卡。

用法::

    python3 agent/tools/classification/train.py --algorithm both
    python3 agent/tools/classification/train.py --algorithm cart --max-depth 12
"""

import argparse
import datetime
import hashlib
import json
import os
import pickle
import subprocess
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from common import split as split_mod                     # noqa: E402
from classification import common_features, modeling, schemas  # noqa: E402

REPO_DIR = split_mod.REPO_DIR


def git_commit():
    """返回训练时 HEAD；若代码目录有未提交改动，追加 ``-dirty``。"""
    try:
        out = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'], cwd=REPO_DIR,
            stderr=subprocess.DEVNULL)
        sha = out.decode('ascii').strip()
    except Exception:
        return 'unknown'
    try:
        st = subprocess.check_output(
            ['git', 'status', '--porcelain', '--', 'agent', 'hadoop', 'tests',
             'docs', 'requirements.txt', 'README.md'],
            cwd=REPO_DIR, stderr=subprocess.DEVNULL)
        if st.strip():
            return sha + '-dirty'
    except Exception:
        pass
    return sha


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def write_json(path, obj):
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write('\n')


def update_registry(path, slug, meta):
    """维护 reports/classification/model-registry.json（模型产物登记表）。

    模型文件本身不进 Git（`artifacts/` 已忽略），因此把路径、SHA256、版本与
    关键指标登记到仓库内的这份 JSON，供成员B/C 与迭代三定位产物。
    """
    registry = {'artifact_storage': '模型文件随 Git 仓库提交于 artifacts/classification/<algorithm>/<model_version>/；'
                                   '重训生成新的 model_version 目录，不覆盖历史版本。'}
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                registry = json.load(f)
        except ValueError:
            registry = {'models': {}}
    registry.setdefault('artifact_storage', '随仓库提交（artifacts/classification/）')
    if 'models' not in registry:
        registry['models'] = {}
    registry['models'][slug] = {
        'model_version': meta['model_version'],
        'algorithm': meta['algorithm'],
        'parameters': meta['parameters'],
        'data_version': meta['data_version'],
        'cleaning_rule_version': meta['cleaning_rule_version'],
        'feature_version': meta['feature_version'],
        'split_version': meta['split_version'],
        'T1': meta['T1'],
        'T2': meta['T2'],
        'code_commit': meta['code_commit'],
        'trained_at': meta['trained_at'],
        'threshold': meta['threshold'],
        'model_path': meta['model_path'],
        'model_sha256': meta['model_sha256'],
        'valid_roc_auc': meta['valid_roc_auc'],
        'test_roc_auc': meta['test_roc_auc'],
    }
    write_json(path, registry)


def train_algorithm(slug, dataset, X, y, split_codes, args):
    tr = split_codes == 0
    va = split_codes == 1
    te = split_codes == 2
    X_tr, y_tr = X[tr], y[tr]
    X_va, y_va = X[va], y[va]
    X_te, y_te = X[te], y[te]

    grid = [{}] if args.no_grid else modeling.PARAM_GRID[slug]
    if slug == 'cart' and (args.max_depth is not None or args.min_samples_leaf is not None):
        grid = [{
            'max_depth': args.max_depth if args.max_depth is not None
            else modeling.DEFAULT_PARAMS['cart']['max_depth'],
            'min_samples_leaf': args.min_samples_leaf if args.min_samples_leaf is not None
            else modeling.DEFAULT_PARAMS['cart']['min_samples_leaf'],
        }]
    # 阈值约束：预测正类比例不超过验证期真实正类比例的 1.10 倍。
    # 理由见 modeling.best_threshold：不加约束时朴素贝叶斯会退化到「几乎全判正类」。
    max_rate = 1.10 * float(y_va.mean())

    selection = []
    best = None
    for params in grid:
        model, used = modeling.make_model(slug, params, seed=args.seed)
        model.fit(X_tr, y_tr)
        metrics_va, _ = modeling.evaluate(model, X_va, y_va, max_positive_rate=max_rate)
        selection.append({'parameters': used, 'valid_roc_auc': metrics_va['roc_auc'],
                          'valid_pr_auc': metrics_va['pr_auc'],
                          'valid_f1_at_selected_threshold': metrics_va['f1'],
                          'valid_predicted_positive_rate': metrics_va['predicted_positive_rate']})
        key = (metrics_va['roc_auc'] or 0.0, metrics_va['pr_auc'] or 0.0)
        if best is None or key > best[0]:
            best = (key, used, model, metrics_va)

    _, params, model, metrics_va = best
    threshold = metrics_va['threshold']

    # 阈值冻结后，测试期只评一次
    metrics_te, _ = modeling.evaluate(model, X_te, y_te, threshold=threshold)
    metrics_te_05, _ = modeling.evaluate(model, X_te, y_te, threshold=0.5)

    user_seen = np.isin(dataset.u[te], list(dataset.train_users))
    movie_seen = np.isin(dataset.m[te], list(dataset.train_movies))
    strata = {
        'user_seen_in_train': user_seen,
        'user_unseen_in_train': ~user_seen,
        'movie_seen_in_train': movie_seen,
        'movie_unseen_in_train': ~movie_seen,
    }
    strata_te = modeling.evaluate_strata(model, X_te, y_te, strata, threshold)

    return {
        'model': model,
        'parameters': params,
        'grid': selection,
        'validation': metrics_va,
        'test': metrics_te,
        'test_threshold_0.5': metrics_te_05,
        'test_strata': strata_te,
        'threshold': threshold,
    }


def model_card(path, slug, result, meta, dataset, args):
    v = result['validation']
    t = result['test']
    lines = [
        '# 模型卡：%s（`%s`）' % (schemas.ALGORITHM_NAMES[slug], meta['model_version']),
        '',
        '## 算法与出处',
        '',
        '- 算法：%s' % schemas.ALGORITHM_NAMES[slug],
        '- 课件：`26Fall-008-分类1010+1014.pdf`（Tieke He, Big Data Analytics）',
        '- 页码：朴素贝叶斯 第 25–36 页；决策树 第 37–61 页（信息熵 46、信息增益 47、C4.5 59）',
        '- 实现说明：%s' % (
            'StandardScaler + GaussianNB' if slug == 'gnb'
            else 'DecisionTreeClassifier(criterion="entropy")，二叉 CART 结构，是对课件 ID3 多叉划分的近似'
        ),
        '',
        '## 训练与评价口径',
        '',
        '| 项 | 值 |',
        '|---|---|',
        '| 数据版本 | `%s` |' % meta['data_version'],
        '| 清洗规则版本 | `%s` |' % meta['cleaning_rule_version'],
        '| 特征版本 | `%s`（%d 维） |' % (meta['feature_version'], meta['n_features']),
        '| 切分版本 | `%s` |' % meta['split_version'],
        '| T1 / T2 | %d / %d |' % (meta['T1'], meta['T2']),
        '| 训练 / 验证 / 测试 | %s / %s / %s |' % (
            format(meta['train_rows'], ','), format(meta['valid_rows'], ','), format(meta['test_rows'], ',')),
        '| 随机种子 | %d |' % meta['seed'],
        '| 代码版本 | `%s` |' % meta['code_commit'],
        '| 超参数 | `%s` |' % json.dumps(result['parameters'], ensure_ascii=False),
        '',
        '验证期用于选超参与阈值，测试期只评价一次；阈值冻结后未再用测试期数据调整。',
        '',
        '## 指标',
        '',
        '| 指标 | 验证期 | 测试期 |',
        '|---|---:|---:|',
        '| ROC-AUC | %s | %s |' % (v['roc_auc'], t['roc_auc']),
        '| PR-AUC | %s | %s |' % (v['pr_auc'], t['pr_auc']),
        '| 阈值 | %.6f | %.6f |' % (v['threshold'], t['threshold']),
        '| Precision | %.4f | %.4f |' % (v['precision'], t['precision']),
        '| Recall | %.4f | %.4f |' % (v['recall'], t['recall']),
        '| F1 | %.4f | %.4f |' % (v['f1'], t['f1']),
        '| Accuracy | %.4f | %.4f |' % (v['accuracy'], t['accuracy']),
        '| 预测正类比例 | %.4f | %.4f |' % (v.get('predicted_positive_rate', 0), t.get('predicted_positive_rate', 0)),
        '',
        '阈值策略：%s。测试期固定使用验证期选出的阈值；另附阈值 0.5 的灵敏度结果供参考。' % (
            '验证期最大化 F1，并要求预测正类比例不超过真实正类比例的 1.10 倍'
        ),
        '',
        '阈值灵敏度（测试期，阈值 0.5）：Precision=%.4f，Recall=%.4f，F1=%.4f，Accuracy=%.4f。' % (
            result['test_threshold_0.5']['precision'], result['test_threshold_0.5']['recall'],
            result['test_threshold_0.5']['f1'], result['test_threshold_0.5']['accuracy']),
        '',
        '测试期混淆矩阵（阈值 %.6f）：TN=%d, FP=%d, FN=%d, TP=%d。' % (
            t['threshold'], t['confusion_matrix']['tn'], t['confusion_matrix']['fp'],
            t['confusion_matrix']['fn'], t['confusion_matrix']['tp']),
        '',
        '参考基线：测试期多数类比例 %.4f（全判正类的准确率）；作业四记录的确定性规则基线准确率 0.5420。' % t['positive_rate'],
        '',
        '## 分层表现（测试期，按训练期是否出现）',
        '',
        '| 分层 | 样本数 | 正类率 | ROC-AUC | PR-AUC | F1 |',
        '|---|---:|---:|---:|---:|---:|',
    ]
    for name, m in result['test_strata'].items():
        lines.append('| %s | %s | %s | %s | %s | %s |' % (
            name, format(m.get('n', 0), ','), m.get('positive_rate'),
            m.get('roc_auc'), m.get('pr_auc'), m.get('f1')))
    lines += [
        '',
        '## 适用限制',
        '',
        '1. 用户级冷启动比例高：验证期约 76.6%、测试期约 47.9% 的评分来自训练窗口内未出现的用户，',
        '   其用户历史特征走全局均分回退，分层指标应优先于总体指标阅读。',
        '2. %s' % (
            '朴素贝叶斯的条件独立假设在本特征下不成立（同一用户共享统计量），后验概率未校准，'
            '不能当作真实概率直接展示。' if slug == 'gnb'
            else '决策树的叶结点比例是频率估计，不是校准概率；树结构无平滑，冷启动样本会快速落到单一分支。'
        ),
        '3. 2,994 条评分（15 个 UserID）在 users.dat 中无属性，职业/年龄走 unknown 编码。',
        '4. 标签含无法消除的噪声：4,328 个主键冲突在清洗阶段整组隔离，剩余样本仍可能受注入值影响。',
        '5. 本模型只使用 T1 之前的数据训练，不随时间自动更新（周期重训见作业四第 7 节）。',
        '',
        '## 复现',
        '',
        '```bash',
        'python3 agent/tools/classification/train.py --algorithm %s --seed %d' % (slug, meta['seed']),
        '```',
        '',
    ]
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def main(argv=None):
    ap = argparse.ArgumentParser(description='迭代二分类训练与评价')
    ap.add_argument('--data-dir', default=None)
    ap.add_argument('--algorithm', default='both', choices=('both',) + schemas.ALGORITHM_SLUGS)
    ap.add_argument('--out-dir', default=os.path.join(REPO_DIR, 'artifacts', 'classification'))
    ap.add_argument('--reports-dir', default=os.path.join(REPO_DIR, 'reports', 'classification'))
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--max-depth', type=int, default=None)
    ap.add_argument('--min-samples-leaf', type=int, default=None)
    ap.add_argument('--no-grid', action='store_true')
    args = ap.parse_args(argv)

    dataset = common_features.Dataset(clean_dir=args.data_dir)
    X, y, split_codes, feat_meta = dataset.build_matrix()
    commit = git_commit()
    today = datetime.date.today().strftime('%Y%m%d')

    print('数据：%s  特征：%s（%d 维）' % (feat_meta['data_version'], feat_meta['feature_version'], X.shape[1]))
    print('切分：训练 %s / 验证 %s / 测试 %s' % (
        format(int((split_codes == 0).sum()), ','),
        format(int((split_codes == 1).sum()), ','),
        format(int((split_codes == 2).sum()), ',')))

    slugs = list(schemas.ALGORITHM_SLUGS) if args.algorithm == 'both' else [args.algorithm]
    summary = []
    for slug in slugs:
        print('\n== 训练 %s ==' % slug)
        result = train_algorithm(slug, dataset, X, y, split_codes, args)
        model_version = '%s-%s' % (slug, today)
        meta = {
            'model_version': model_version,
            'algorithm': schemas.ALGORITHM_NAMES[slug],
            'algorithm_slug': slug,
            'parameters': result['parameters'],
            'seed': args.seed,
            'data_version': feat_meta['data_version'],
            'cleaning_rule_version': feat_meta['cleaning_rule_version'],
            'feature_version': feat_meta['feature_version'],
            'split_version': schemas.SPLIT_VERSION,
            'T1': dataset.T1,
            'T2': dataset.T2,
            'train_rows': int((split_codes == 0).sum()),
            'valid_rows': int((split_codes == 1).sum()),
            'test_rows': int((split_codes == 2).sum()),
            'n_features': feat_meta['n_features'],
            'feature_names': feat_meta['feature_names'],
            'code_commit': commit,
            'trained_at': datetime.datetime.now().isoformat(timespec='seconds'),
            'threshold': result['threshold'],
            'threshold_policy': '验证期最大化 F1，且预测正类比例 <= 1.10 x 真实正类比例',
            'valid_roc_auc': result['validation']['roc_auc'],
            'valid_pr_auc': result['validation']['pr_auc'],
            'test_roc_auc': result['test']['roc_auc'],
            'test_pr_auc': result['test']['pr_auc'],
        }

        model_dir = os.path.join(args.out_dir, slug, model_version)
        os.makedirs(model_dir, exist_ok=True)
        model_path = os.path.join(model_dir, 'model.pkl')
        with open(model_path, 'wb') as f:
            pickle.dump(result['model'], f, protocol=4)
        meta['model_path'] = os.path.relpath(model_path, REPO_DIR).replace('\\', '/')
        meta['model_sha256'] = sha256_file(model_path)
        write_json(os.path.join(model_dir, 'meta.json'), meta)
        update_registry(os.path.join(args.reports_dir, 'model-registry.json'), slug, meta)

        metrics = {
            'algorithm': meta['algorithm'],
            'algorithm_slug': slug,
            'model_version': model_version,
            'validation': result['validation'],
            'test': result['test'],
            'test_threshold_0.5': result['test_threshold_0.5'],
            'test_strata': result['test_strata'],
            'selection': result['grid'],
            'threshold_selected_on': 'validation',
        }
        write_json(os.path.join(args.reports_dir, 'metrics-%s.json' % slug), metrics)
        write_json(os.path.join(args.reports_dir, 'experiment-%s.json' % slug), {
            'experiment_id': 'cls-%s-%s' % (slug, today),
            'task_type': 'classification',
            'data_version': meta['data_version'],
            'cleaning_rule_version': meta['cleaning_rule_version'],
            'T1': meta['T1'],
            'T2': meta['T2'],
            'split_version': meta['split_version'],
            'feature_or_profile_version': meta['feature_version'],
            'algorithm': meta['algorithm'],
            'algorithm_source': '26Fall-008-分类1010+1014.pdf 第 25–36 页（NB）/ 第 37–61 页（DT）',
            'parameters': meta['parameters'],
            'code_commit': meta['code_commit'],
            'metrics': {
                'validation': {k: result['validation'][k] for k in ('roc_auc', 'pr_auc', 'f1', 'threshold')},
                'test': {k: result['test'][k] for k in ('roc_auc', 'pr_auc', 'f1', 'threshold')},
            },
            'artifact_paths': [meta['model_path']],
            'limitations': [
                '用户级冷启动比例高，分层指标优先于总体指标',
                '概率未校准，不能当作真实概率展示',
                '标签含 4,328 个冲突键带来的噪声',
            ],
        })
        model_card(os.path.join(args.reports_dir, 'model-card-%s.md' % slug),
                   slug, result, meta, dataset, args)

        print('验证 ROC-AUC=%.4f PR-AUC=%.4f F1=%.4f（阈值 %.6f）' % (
            result['validation']['roc_auc'], result['validation']['pr_auc'],
            result['validation']['f1'], result['validation']['threshold']))
        print('测试 ROC-AUC=%.4f PR-AUC=%.4f F1=%.4f Acc=%.4f' % (
            result['test']['roc_auc'], result['test']['pr_auc'],
            result['test']['f1'], result['test']['accuracy']))
        print('模型：%s' % meta['model_path'])
        summary.append({
            'algorithm': meta['algorithm'], 'slug': slug,
            'valid_roc_auc': result['validation']['roc_auc'],
            'valid_pr_auc': result['validation']['pr_auc'],
            'test_roc_auc': result['test']['roc_auc'],
            'test_pr_auc': result['test']['pr_auc'],
            'test_f1': result['test']['f1'],
            'test_accuracy': result['test']['accuracy'],
            'threshold': result['threshold'],
            'parameters': result['parameters'],
        })

    if len(summary) > 1:
        write_json(os.path.join(args.reports_dir, 'comparison.json'), summary)
        lines = ['# 两种分类算法对照', '',
                 '口径：训练 t <= T1；验证 T1 < t <= T2（选超参与阈值）；测试 t > T2（只评一次）。', '',
                 '| 算法 | 验证 ROC-AUC | 验证 PR-AUC | 测试 ROC-AUC | 测试 PR-AUC | 测试 F1 | 测试 Acc | 阈值 |',
                 '|---|---:|---:|---:|---:|---:|---:|---:|']
        for s in summary:
            lines.append('| %s | %.4f | %.4f | %.4f | %.4f | %.4f | %.4f | %.6f |' % (
                s['algorithm'], s['valid_roc_auc'], s['valid_pr_auc'], s['test_roc_auc'],
                s['test_pr_auc'], s['test_f1'], s['test_accuracy'], s['threshold']))
        lines += ['', '完整指标见 `metrics-*.json`，单模型说明见 `model-card-*.md`。', '']
        with open(os.path.join(args.reports_dir, 'comparison.md'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except schemas.ToolError as e:
        print(json.dumps(e.to_dict(), ensure_ascii=False), file=sys.stderr)
        sys.exit(2)
