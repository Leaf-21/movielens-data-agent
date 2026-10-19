#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""迭代二统一数据读取与时间切分。

单一事实来源
------------
- 时间边界只从 ``hadoop/config/rules.json`` 的 ``time.T1_epoch`` /
  ``time.T2_epoch`` 读取，本模块不写死任何日历日期（迭代二数据与实验规范 §一.3）。
- 数据版本号从同一文件的 ``output_version`` 读取，避免多处手抄。

切分口径（迭代二数据与实验规范 §二）
----------------------------------
    训练集：``Timestamp <= T1``
    验证集：``T1 < Timestamp <= T2``
    测试集：``Timestamp > T2``

清洗快照路径
------------
默认 ``data/<output_version>/``（当前为 ``data/movielens-1m-v2-clean-v1/``），
可用环境变量 ``ML_CLEAN_DIR`` 或参数覆盖。快照文件不进 Git（``*.dat`` 已忽略），
校验和登记在 ``data/DATASETS.md`` 与本模块生成的切分快照中。

用法::

    python3 agent/tools/common/split.py                    # 打印摘要
    python3 agent/tools/common/split.py --out reports/experiments/split-v1.json
"""

import argparse
import hashlib
import json
import os
import sys

SPLIT_VERSION = 'split-v1'

TRAIN = 'train'
VALIDATE = 'validate'
TEST = 'test'
SPLITS = (TRAIN, VALIDATE, TEST)

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
DEFAULT_RULES = os.path.join(REPO_DIR, 'hadoop', 'config', 'rules.json')


class DataUnavailable(Exception):
    """清洗快照缺失或不可读。调用方应转成 DATA_UNAVAILABLE，不得返回占位结果。"""


# ---------------------------------------------------------------------------
# 配置读取
# ---------------------------------------------------------------------------
def load_rules(path=None):
    """读取规则文件（唯一口径来源）。"""
    path = path or DEFAULT_RULES
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (IOError, OSError, ValueError) as e:
        raise DataUnavailable('无法读取规则文件 %s: %s' % (path, e))


def time_bounds(rules=None):
    """返回 (T1_epoch, T2_epoch)。"""
    rules = rules or load_rules()
    try:
        t1 = int(rules['time']['T1_epoch'])
        t2 = int(rules['time']['T2_epoch'])
    except (KeyError, TypeError, ValueError) as e:
        raise DataUnavailable('规则文件缺少合法的 T1_epoch/T2_epoch: %s' % e)
    if not t1 < t2:
        raise DataUnavailable('时间边界非法：T1(%d) 必须小于 T2(%d)' % (t1, t2))
    return t1, t2


def data_version(rules=None):
    """返回清洗数据版本号（rules.json 的 output_version）。"""
    rules = rules or load_rules()
    v = rules.get('output_version')
    if not v:
        raise DataUnavailable('规则文件缺少 output_version')
    return v


def rule_version(rules=None):
    rules = rules or load_rules()
    return rules.get('rule_version')


def clean_dir(rules=None, path=None):
    """清洗快照目录：显式参数 > 环境变量 ML_CLEAN_DIR > 仓库默认位置。"""
    if path:
        return path
    env = os.environ.get('ML_CLEAN_DIR')
    if env:
        return env
    return os.path.join(REPO_DIR, 'data', data_version(rules))


def ratings_path(clean=None, rules=None, path=None):
    return os.path.join(clean_dir(rules, path) if clean is None else clean, 'ratings.dat')


# ---------------------------------------------------------------------------
# 核心切分逻辑（纯函数，便于单元测试）
# ---------------------------------------------------------------------------
def split_of(timestamp, t1, t2):
    """返回记录所属子集：train / validate / test。

    ``Timestamp == T1`` 属于训练集，``Timestamp == T2`` 属于验证集。
    """
    ts = int(timestamp)
    if ts <= t1:
        return TRAIN
    if ts <= t2:
        return VALIDATE
    return TEST


def iter_ratings(path):
    """逐行读取 ratings.dat，产出 (UserID, MovieID, Rating, Timestamp)。"""
    try:
        f = open(path, 'rb')
    except (IOError, OSError) as e:
        raise DataUnavailable('无法读取 %s: %s' % (path, e))
    with f:
        for lineno, line in enumerate(f, 1):
            line = line.rstrip(b'\r\n')
            if not line:
                continue
            parts = line.split(b'::')
            if len(parts) != 4:
                raise DataUnavailable('%s 第 %d 行字段数为 %d（期望 4）' % (os.path.basename(path), lineno, len(parts)))
            try:
                yield (int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]))
            except ValueError:
                raise DataUnavailable('%s 第 %d 行含非整数字段' % (os.path.basename(path), lineno))


def _empty_bucket():
    return {
        'records': 0,
        'positives': 0,
        'users': set(),
        'movies': set(),
        'time_min': None,
        'time_max': None,
    }


def summarize_list(rows, t1, t2):
    """对 (u, m, r, ts) 序列做切分统计。

    返回可直接序列化为 JSON 的 dict（集合已转成计数）。
    """
    buckets = {name: _empty_bucket() for name in SPLITS}
    invalid = 0
    total = 0
    tmin = tmax = None
    for u, m, r, ts in rows:
        total += 1
        tmin = ts if tmin is None else min(tmin, ts)
        tmax = ts if tmax is None else max(tmax, ts)
        name = split_of(ts, t1, t2)
        b = buckets[name]
        b['records'] += 1
        if r >= 4:
            b['positives'] += 1
        b['users'].add(u)
        b['movies'].add(m)
        b['time_min'] = ts if b['time_min'] is None else min(b['time_min'], ts)
        b['time_max'] = ts if b['time_max'] is None else max(b['time_max'], ts)

    out = {}
    for name in SPLITS:
        b = buckets[name]
        n = b['records']
        out[name] = {
            'records': n,
            'ratio': round(n / total, 6) if total else 0.0,
            'positives': b['positives'],
            'positive_rate': round(b['positives'] / n, 6) if n else 0.0,
            'users': len(b['users']),
            'movies': len(b['movies']),
            'time_min': b['time_min'],
            'time_max': b['time_max'],
        }
    out['_meta'] = {
        'records': total,
        'invalid_rows': invalid,
        'time_min': tmin,
        'time_max': tmax,
        'T1_epoch': t1,
        'T2_epoch': t2,
        'split_rule': 'train: ts <= T1; validate: T1 < ts <= T2; test: ts > T2',
    }
    return out


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def count_lines(path):
    with open(path, 'rb') as f:
        return sum(1 for _ in f)


def summarize(clean=None, rules=None, check_unique=True):
    """读取清洗快照并生成完整切分描述（含文件校验和）。"""
    rules = rules or load_rules()
    t1, t2 = time_bounds(rules)
    cdir = clean_dir(rules, clean)
    rpath = os.path.join(cdir, 'ratings.dat')
    if not os.path.exists(rpath):
        raise DataUnavailable('清洗快照不存在：%s' % rpath)

    rows = []
    duplicates = 0
    seen = set()
    for row in iter_ratings(rpath):
        if check_unique:
            key = (row[0], row[1])
            if key in seen:
                duplicates += 1
            seen.add(key)
        rows.append(row)

    stats = summarize_list(rows, t1, t2)
    stats['_meta']['duplicate_pairs'] = duplicates
    stats['_meta']['split_version'] = SPLIT_VERSION
    stats['_meta']['data_version'] = data_version(rules)
    stats['_meta']['cleaning_rule_version'] = rule_version(rules)

    files = {}
    for name in ('ratings.dat', 'movies.dat', 'users.dat'):
        p = os.path.join(cdir, name)
        if os.path.exists(p):
            files[name] = {
                'lines': count_lines(p),
                'bytes': os.path.getsize(p),
                'sha256': sha256_file(p),
            }
        else:
            files[name] = None
    if os.path.isabs(cdir) and cdir.startswith(REPO_DIR):
        shown = os.path.relpath(cdir, REPO_DIR).replace('\\', '/')
    else:
        shown = cdir.replace('\\', '/')
    stats['source'] = {
        'dir': shown,
        'files': files,
    }
    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description='迭代二统一时间切分统计')
    ap.add_argument('--data-dir', default=None, help='清洗快照目录（默认 data/<output_version>）')
    ap.add_argument('--rules', default=None, help='规则文件路径')
    ap.add_argument('--out', default=None, help='输出 JSON 路径')
    ap.add_argument('--no-unique-check', action='store_true', help='跳过 (UserID, MovieID) 重复检查')
    args = ap.parse_args(argv)

    stats = summarize(clean=args.data_dir, rules=load_rules(args.rules), check_unique=not args.no_unique_check)

    if args.out:
        d = os.path.dirname(os.path.abspath(args.out))
        if d and not os.path.isdir(d):
            os.makedirs(d)
        with open(args.out, 'w', encoding='utf-8') as f:
            json.dump(stats, f, ensure_ascii=False, indent=2, sort_keys=False)
            f.write('\n')
        print('已写入 %s' % args.out)

    meta = stats['_meta']
    print('data_version=%s rule=%s split=%s' % (
        meta['data_version'], meta['cleaning_rule_version'], meta['split_version']))
    print('T1=%d T2=%d  总记录=%d  重复对=%d  非法行=%d' % (
        meta['T1_epoch'], meta['T2_epoch'], meta['records'], meta['duplicate_pairs'],
        meta['invalid_rows']))
    for name in SPLITS:
        s = stats[name]
        print('%-8s records=%-7d (%6.2f%%) positives=%-7d (%5.2f%%) users=%-5d movies=%-5d' % (
            name, s['records'], 100.0 * s['ratio'], s['positives'],
            100.0 * s['positive_rate'], s['users'], s['movies']))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except DataUnavailable as e:
        sys.stderr.write('数据不可用: %s\n' % e)
        sys.exit(2)
