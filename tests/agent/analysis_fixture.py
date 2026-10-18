# -*- coding: utf-8 -*-
"""
迭代二分析测试夹具：把 ML_ANALYSIS_BASE / ML_ANALYSIS_CONFIG / ML_RULES
指向临时目录中的合成小数据与收紧后的口径，工具代码本身用仓库内生产版本。

数据设计（7 个拟合用户 = 剧情群 1-3 / 恐怖低分群 4-6 / 孤儿群 10，
另有 INSUFFICIENT(7)、NO_TRAIN(8，仅验证期评分)、无评分(9)，
以及不在 users.dat 的孤儿评分用户 99）：
  两个团簇特征差异足够大，K-Means/DBSCAN 在玩具规模下也能稳定分开。
数值均为测试数据，不代表真实执行结果（纪律同 test_api.py）。
"""

import json
import os
import shutil
import sys
import tempfile

import _paths  # noqa: F401
from _paths import AGENT_TOOLS  # noqa: F401

_CLU = os.path.join(AGENT_TOOLS, 'clustering')
if _CLU not in sys.path:
    sys.path.insert(0, _CLU)

import config

_CLU = os.path.join(_paths.AGENT_TOOLS, 'clustering')
if _CLU not in sys.path:
    sys.path.insert(0, _CLU)

T1_EPOCH = 1000
T2_EPOCH = 2000
MIN_TRAIN_RATINGS = 8

GENRES = ['Drama', 'Horror', "Children's"]

MOVIES = {
    1: ('Movie One (1990)', 'Drama'),
    2: ('Movie Two (1991)', 'Drama'),
    3: ('Movie Three (1992)', 'Horror'),
    4: ('Movie Four (1993)', 'Horror'),
    5: ("Movie Five (1994)", "Children's"),
    6: ('Movie Six (1995)', 'Drama|Horror'),
}
# 孤儿群用户 10 用电影 5；剧情群用 1/2/6；恐怖群用 3/4/6

USERS = list(range(1, 11))          # users.dat 中 10 人
ORPHAN_USER = 99                    # 有训练期评分但不在 users.dat

DRAMA_TS = (500, 550, 600, 650, 700, 750, 800, 850)      # 8 条训练期评分
HORROR_TS = (500, 560, 620, 680, 740, 800, 860, 900)


def _rating_rows():
    rows = []
    for u in (1, 2, 3):             # 剧情群：全高分
        seq = [(1, 5), (2, 5), (6, 5), (1, 5), (2, 4), (6, 4), (1, 5), (2, 5)]
        rows += [(u, m, r, ts) for (m, r), ts in zip(seq, DRAMA_TS)]
    for u in (4, 5, 6):             # 恐怖群：全低分
        seq = [(3, 2), (4, 1), (6, 2), (3, 2), (4, 2), (6, 1), (3, 2), (4, 2)]
        rows += [(u, m, r, ts) for (m, r), ts in zip(seq, HORROR_TS)]
    # 孤儿群用户 10：只评儿童片
    seq = [(5, 3)] * 8
    rows += [(10, 5, 3, ts) for ts in DRAMA_TS]
    # 用户 7：训练期只有 3 条 -> INSUFFICIENT_HISTORY
    rows += [(7, 1, 4, 500), (7, 3, 2, 600), (7, 6, 3, 700)]
    # 用户 8：只有验证期(T1,T2]评分 -> NO_TRAIN_HISTORY（且不进画像训练特征）
    rows += [(8, 1, 5, 1500), (8, 3, 1, 1600)]
    # 孤儿 99：训练期评分但不在 users.dat
    rows += [(ORPHAN_USER, 2, 4, 510)]
    return sorted(rows)


def make_base():
    """建临时仓库根，返回 (base, analysis_cfg_path, rules_cfg_path)。"""
    base = tempfile.mkdtemp(prefix='ml_analysis_fixture_')
    clean = os.path.join(base, 'hadoop', 'output', 'clean')
    os.makedirs(clean)
    with open(os.path.join(clean, 'movies.dat'), 'w', encoding='latin-1') as f:
        for mid, (title, g) in MOVIES.items():
            f.write('%d::%s::%s\n' % (mid, title, g))
    with open(os.path.join(clean, 'users.dat'), 'w', encoding='latin-1') as f:
        for u in USERS:
            f.write('%d::M::25::7::12143\n' % u)
    with open(os.path.join(clean, 'ratings.dat'), 'w', encoding='latin-1') as f:
        for uid, mid, r, ts in _rating_rows():
            f.write('%d::%d::%d::%d\n' % (uid, mid, r, ts))

    analysis = {
        'analysis_version': 'iter2-analysis-test',
        'input': {'data_version': 'movielens-1m-v2-clean-v1',
                  'clean_dir': 'hadoop/output/clean'},
        'profile_version': 'profile-test',
        'min_train_ratings': MIN_TRAIN_RATINGS,
        'fit_window': 'train_only',
        'feature_dict': {'_test': 'fixture'},
        'scaler': 'zscore_fit_on_ok_users',
        'representative_movies': {
            'top_n': 5, 'min_member_votes': 3,
            'basis': '群成员训练期 Rating>=4 的计数（同分按电影热度排序）；'
                     '代表性内容 = 高频高分电影，不代表因果偏好'},
        'algorithms': {
            'clustering': {
                'kmeans': {
                    'module': 'clustering.kmeans_tool', 'entry': 'run',
                    'tool_name': 'clustering_kmeans',
                    'display_name': 'K-Means（测试口径）',
                    'algorithm_source': 'test fixture',
                    'selection_rule': '测试口径：抽样轮廓估计选最大者，平手取小',
                    'parameters': {'k_candidates': [2, 3], 'seed': 7,
                                   'max_iter': 50, 'tol': 0.0001,
                                   'init': 'kmeans++',
                                   'silhouette_sample_size': 40,
                                   'timeout_s': 120},
                },
                'dbscan': {
                    'module': 'clustering.dbscan_tool', 'entry': 'run',
                    'tool_name': 'clustering_dbscan',
                    'display_name': 'DBSCAN（测试口径）',
                    'algorithm_source': 'test fixture',
                    'parameters': {'min_samples': 3, 'eps_method':
                                   'kdistance_p90', 'eps_sample_size': 40,
                                   'seed': 7, 'timeout_s': 120},
                },
            },
            'classification': {},
            'dimensionality_reduction': {},
        },
        'allowed_parameters': {
            'kmeans': {'k': [2, 30], 'max_iter': [10, 1000],
                       'seed': [0, 2147483647]},
            'dbscan': {'eps': [0.01, 50.0], 'min_samples': [3, 100]},
        },
        'artifacts': {'profiles_dir': 'agent/artifacts/profiles',
                      'clusters_dir': 'agent/artifacts/clustering'},
    }
    ap = os.path.join(base, 'analysis.json')
    with open(ap, 'w', encoding='utf-8') as f:
        json.dump(analysis, f, ensure_ascii=False, indent=1)

    rules = {
        'rule_version': 'rule-test',
        'input_version': 'movielens-1m-v2',
        'output_version': 'movielens-1m-v2-clean-v1',
        'time': {'T1': '1970-01-01', 'T2': '1970-01-01',
                 'T1_epoch': T1_EPOCH, 'T2_epoch': T2_EPOCH,
                 'split_rule': 'fixture'},
        'genres': {'valid': GENRES},
        'weights': {},
    }
    rp = os.path.join(base, 'rules.json')
    with open(rp, 'w', encoding='utf-8') as f:
        json.dump(rules, f, ensure_ascii=False, indent=1)
    return base, ap, rp


class install(object):
    """with install() as fx: ...  环境变量 + 配置缓存的成对切换。"""

    def __enter__(self):
        self.base, self.analysis_path, self.rules_path = make_base()
        self._saved = {k: os.environ.get(k) for k in
                       ('ML_ANALYSIS_BASE', 'ML_ANALYSIS_CONFIG', 'ML_RULES')}
        os.environ['ML_ANALYSIS_BASE'] = self.base
        os.environ['ML_ANALYSIS_CONFIG'] = self.analysis_path
        os.environ['ML_RULES'] = self.rules_path
        self._reset_caches()
        self.acfg = config.load_analysis()
        self.rcfg = config.load_rules()
        return self

    def __exit__(self, *exc):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._reset_caches()
        shutil.rmtree(self.base, ignore_errors=True)
        return False

    @staticmethod
    def _reset_caches():
        config._ANALYSIS_CACHE = None
        config._RULES_CACHE = None


FIT_USERS = [1, 2, 3, 4, 5, 6, 10]
ALL_USERS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
