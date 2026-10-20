#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
降维组件统一入口（成员C，供在线调度器与线下复现共用）

与聚类 run_fit.py 同构：一次调用在同一进程内顺序执行该组降维工具，产出：
  · agent/artifacts/dimensionality_reduction/<method>-v1.json       统一信封
  · agent/artifacts/dimensionality_reduction/<method>-v1.meta.json  工件登记
并把结果摘要打印到 stdout（JSON）。

独立运行：
  python3 -I agent/tools/dimensionality_reduction/run_fit.py
  python3 -I .../run_fit.py --user 1000 --user 2000 --method pca
"""

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS_DIR = os.path.dirname(_HERE)
_SRC_DIR = os.path.join(os.path.dirname(_TOOLS_DIR), 'src')
for _p in (_HERE, os.path.join(_TOOLS_DIR, 'clustering'), _TOOLS_DIR, _SRC_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config                                   # noqa: E402
import registry                                 # noqa: E402
from common import AnalysisError, sha256_file, now_utc  # noqa: E402
import dr_common as D                           # noqa: E402

CATEGORY = 'dimensionality_reduction'


def artifact_paths(acfg, method):
    out_dir = config.resolve_repo_path('agent/artifacts/dimensionality_reduction')
    os.makedirs(out_dir, exist_ok=True)
    return (os.path.join(out_dir, '%s-v1.json' % method),
            os.path.join(out_dir, '%s-v1.meta.json' % method))


def run_one(method, payload, acfg=None, rcfg=None):
    """动态导入工具 -> 统一信封 + 工件落盘 + meta 登记。返回 (envelope, meta_path)。"""
    acfg = acfg or config.load_analysis()
    rcfg = rcfg or config.load_rules()
    envelope = registry.in_process_run(CATEGORY, method, payload, acfg, rcfg)
    res_path, meta_path = artifact_paths(acfg, method)
    D.write_envelope_file(envelope, res_path)
    kmeans = envelope['clustering_comparison']['kmeans']
    meta = {
        'method': method,
        'result_version': envelope['result_version'],
        'model_version': envelope['model_version'],
        'parameters': envelope['parameters'],
        'data_version': envelope['data_version'],
        'profile_version': envelope['profile_version'],
        'feature_version': envelope['feature_version'],
        'code_version': envelope['code_version'],
        'created_at': envelope['created_at'],
        'result_sha256': sha256_file(res_path),
        'result_file': os.path.relpath(res_path, config.REPO_DIR),
        'info_retention_metric': envelope['information_retention'].get('metric'),
        'kmeans_silhouette_before': kmeans['before']['metrics']['silhouette'],
        'kmeans_silhouette_after': kmeans['after']['metrics']['silhouette'],
        'registered_by': 'run_fit.py',
        'registered_at': now_utc(),
    }
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return envelope, meta_path


def run(payload, methods=None, acfg=None, rcfg=None):
    """runner 侧入口：payload 已由 router 切成 {user_ids, parameters}。"""
    acfg = acfg or config.load_analysis()
    rcfg = rcfg or config.load_rules()
    methods = list(methods or registry.algorithm_names(CATEGORY, acfg))
    if not methods:
        raise AnalysisError('MODEL_NOT_FOUND', '降维类别下没有已登记算法实现')
    out = []
    for m in methods:
        env, meta_path = run_one(m, payload, acfg, rcfg)
        out.append({'algorithm': m, 'result': env, 'meta_path': meta_path})
    return out


def _summary_entry(r):
    env = r['result']
    info = env['information_retention']
    if info.get('metric') == 'knn_agreement':
        retention = {'metric': 'knn_agreement', 'value': info.get('knn_agreement')}
    else:
        retention = {'metric': info.get('metric'),
                     'value': info.get('top2_cumulative')}
    return {
        'algorithm': r['algorithm'],
        'model_version': env['model_version'],
        'result_version': env['result_version'],
        'meta_path': os.path.relpath(r['meta_path'], config.REPO_DIR),
        'information_retention': retention,
        'elapsed_ms': env['resource_usage']['elapsed_ms'],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description='降维组件入口（PCA / t-SNE）')
    ap.add_argument('--method', action='append', default=[],
                    help='降维方法（pca/tsne），可重复；缺省=全部已登记算法')
    ap.add_argument('--user', action='append', default=[], help='目标用户 ID，可重复')
    ap.add_argument('--request', default=None, help='payload JSON 文件')
    args = ap.parse_args(argv)
    if args.request:
        with open(args.request, 'r', encoding='utf-8') as f:
            payload = json.load(f)
    else:
        payload = {'user_ids': [int(x) for x in args.user] or None}
    try:
        results = run(payload, methods=args.method or None)
    except AnalysisError as e:
        json.dump({'status': 'FAILED', 'error': e.to_error_dict()},
                  sys.stdout, ensure_ascii=False)
        sys.stdout.write('\n')
        return 2
    print(json.dumps({'status': 'SUCCESS',
                      'results': [_summary_entry(r) for r in results]},
                     ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main())
