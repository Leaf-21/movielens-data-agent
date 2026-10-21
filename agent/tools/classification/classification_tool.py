#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分类工具的 registry 适配层（成员A）。

成员B的 `agent/tools/registry.py` 规定六个工具同构：

    run(payload: dict, acfg=None, rcfg=None) -> 统一信封 dict
    CLI: python3 -I <file> --request req.json --output out.json

本文件把已有的 `classification.predict.classify()` 包装成该契约，算法本身不重写。

payload（由 runner 传入）::

    {
      "algorithm": "gnb" | "cart",     # 必填：调用哪个工具（与 registry 条目一一对应）
      "user_id": 1,
      "movie_id": 1193,
      "prediction_time": 974862386,    # 可选；缺省按训练期快照预测
      "data_version": "movielens-1m-v2-clean-v1",   # 可选，传入则校验
      "feature_version": "feat-v1"                  # 可选，传入则校验
    }

说明：一个工具只跑一种算法。原因是 registry 按“类别 + 算法名”登记条目，
runner 逐条调用；两种算法对照由 runner 调用两次完成（与聚类的 kmeans/dbscan 同构）。

隔离模式：runner 用 `python3 -I` 启动，`-I` 不把当前目录加入 sys.path，
因此本文件自行把 `agent/tools` 加入路径，不依赖 PYTHONPATH。
"""

import argparse
import datetime
import hashlib
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS_DIR = os.path.dirname(_HERE)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from common import split as split_mod                       # noqa: E402
from classification import predict, schemas                 # noqa: E402

TASK_TYPE = 'classification'

ALGORITHM_SOURCE = {
    'gnb': '课程课件 26Fall-008-分类1010+1014.pdf 第 25–36 页（朴素贝叶斯）',
    'cart': '课程课件 26Fall-008-分类1010+1014.pdf 第 38–61 页（决策树，信息增益）',
}


class ClassificationError(Exception):
    """带错误码的工具失败，供 CLI 输出 FAILED 信封。"""

    def __init__(self, code, message, details=None):
        self.code = code
        self.message = message
        self.details = details or {}
        super(ClassificationError, self).__init__(message)

    def to_error_dict(self):
        return {'code': self.code, 'message': self.message, 'details': self.details}


def _as_error(exc):
    if isinstance(exc, ClassificationError):
        return exc
    if isinstance(exc, schemas.ToolError):
        return ClassificationError(exc.code, exc.message, exc.detail)
    return ClassificationError(schemas.ALGORITHM_ERROR, str(exc))


def _result_version(model_version, target, item):
    raw = '|'.join([
        str(model_version), str(target.get('user_id')), str(target.get('movie_id')),
        str(item.get('predicted_class')), str(item.get('positive_probability')),
        str((item.get('metrics') or {}).get('threshold')),
    ])
    return 'cls-' + hashlib.sha1(raw.encode('utf-8')).hexdigest()[:12]


def run(payload, acfg=None, rcfg=None):
    """按 registry 契约执行一次分类，返回统一信封。失败抛 ClassificationError。"""
    t0 = time.time()
    payload = dict(payload or {})

    algorithm = payload.get('algorithm')
    if not algorithm:
        raise ClassificationError(
            schemas.INVALID_PARAMETER,
            'payload 缺少 algorithm（应为 gnb 或 cart）',
            {'allowed': list(schemas.ALGORITHM_SLUGS)})
    if algorithm not in schemas.ALGORITHM_SLUGS:
        raise ClassificationError(
            schemas.INVALID_PARAMETER, '未知算法: %s' % algorithm,
            {'allowed': list(schemas.ALGORITHM_SLUGS)})

    if payload.get('user_id') is None or payload.get('movie_id') is None:
        raise ClassificationError(
            schemas.INVALID_PARAMETER, 'payload 缺少 user_id 或 movie_id',
            {'user_id': payload.get('user_id'), 'movie_id': payload.get('movie_id')})

    rules = split_mod.load_rules()
    expect_data_version = split_mod.data_version(rules)
    given = payload.get('data_version')
    if given and given != expect_data_version:
        raise ClassificationError(
            schemas.VERSION_MISMATCH,
            '数据版本不匹配：%s != %s' % (given, expect_data_version),
            {'given': given, 'expected': expect_data_version})
    given_feature = payload.get('feature_version')
    if given_feature and given_feature != schemas.FEATURE_VERSION:
        raise ClassificationError(
            schemas.VERSION_MISMATCH,
            '特征版本不匹配：%s != %s' % (given_feature, schemas.FEATURE_VERSION),
            {'given': given_feature, 'expected': schemas.FEATURE_VERSION})

    artifacts_dir = None
    if isinstance(rcfg, dict):
        artifacts_dir = rcfg.get('artifacts_dir')

    try:
        _model, meta = predict.load_model(algorithm, artifacts_dir=artifacts_dir,
                                          model_version=payload.get('model_version'))
        result = predict.classify(
            payload['user_id'], payload['movie_id'],
            prediction_time=payload.get('prediction_time'),
            algorithm=algorithm,
            artifacts_dir=artifacts_dir,
            model_version=payload.get('model_version'),
            data_dir=payload.get('data_dir'),
        )
    except schemas.ToolError as e:
        raise _as_error(e)

    item = result['results'][0]
    envelope = {
        'task_type': TASK_TYPE,
        'status': 'SUCCESS',
        'algorithm': algorithm,
        'algorithm_name': item.get('algorithm'),
        'algorithm_tool': 'classification_%s' % algorithm,
        'algorithm_source': ALGORITHM_SOURCE[algorithm],
        'model_version': item.get('model_version'),
        'result_version': _result_version(item.get('model_version'), result['target'], item),
        'parameters': meta.get('parameters') or {},
        'data_version': result.get('data_version'),
        # 分类特征（feat-v1）不用画像工件，此字段是 runner 信封契约的必需键；
        # 调度器会透传 plan 里的画像版本，直接命令行运行时回落到默认版本。
        'profile_version': payload.get('profile_version') or 'profile-v1',
        'cleaning_rule_version': result.get('cleaning_rule_version'),
        'feature_version': result.get('feature_version'),
        'split_version': result.get('split_version'),
        'T1': result.get('T1'),
        'T2': result.get('T2'),
        'code_version': meta.get('code_commit'),
        'created_at': datetime.datetime.now().isoformat(timespec='seconds'),
        'target': result['target'],
        'prediction_time_basis': item.get('prediction_time_basis'),
        'results': result['results'],
        'metrics': dict(item.get('metrics') or {},
                        valid_pr_auc=meta.get('valid_pr_auc'),
                        test_pr_auc=meta.get('test_pr_auc')),
        'limitations': item.get('limitations') or [],
        'elapsed_ms': int((time.time() - t0) * 1000),
    }
    return envelope


def write_envelope_file(res, out_path):
    d = os.path.dirname(os.path.abspath(out_path))
    if d and not os.path.isdir(d):
        os.makedirs(d)
    tmp = out_path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    os.replace(tmp, out_path)


def main(argv=None):
    ap = argparse.ArgumentParser(description='分类工具（独立运行 / 子进程协议）')
    ap.add_argument('--user-id', type=int, default=None)
    ap.add_argument('--movie-id', type=int, default=None)
    ap.add_argument('--prediction-time', type=int, default=None)
    ap.add_argument('--algorithm', default='gnb', choices=schemas.ALGORITHM_SLUGS)
    ap.add_argument('--request', default=None, help='payload JSON 文件（调度器模式）')
    ap.add_argument('--output', default=None, help='信封输出 JSON（调度器模式）')
    args = ap.parse_args(argv)

    try:
        if args.request:
            with open(args.request, 'r', encoding='utf-8') as f:
                payload = json.load(f)
        else:
            payload = {
                'algorithm': args.algorithm,
                'user_id': args.user_id,
                'movie_id': args.movie_id,
                'prediction_time': args.prediction_time,
            }
        res = run(payload)
    except ClassificationError as e:
        json.dump({'status': 'FAILED', 'error': e.to_error_dict()},
                  sys.stdout, ensure_ascii=False)
        sys.stdout.write('\n')
        return 2

    if args.output:
        write_envelope_file(res, args.output)
        print(json.dumps({'status': 'SUCCESS', 'result_version': res['result_version'],
                          'output': args.output, 'elapsed_ms': res['elapsed_ms']},
                         ensure_ascii=False))
    else:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
