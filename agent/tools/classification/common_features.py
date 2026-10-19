#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分类特征构建（feature_version = feat-v1）。

设计要点
--------
1. **时间安全**：F1 用户历史均分、F2 电影历史均分、F3 电影历史评分次数只使用
   严格早于目标事件的评分。实现上按时间戳分组：同一秒内的事件先统一读取
   「该秒之前」的累计状态，再更新累计状态，因此同一秒的其它事件也不参与
   彼此的特征（比「按行顺序」更严格）。
2. **只在训练期拟合**：唯一带学习参数的步骤是 GNB 的标准化（在 sklearn
   Pipeline 内、只用训练集 fit）。F4/F5/F6 的取值域来自规则文件与数据字典，
   不依赖数据分布，因此不属于「学习型预处理」。
3. **缺失显式化**：2,994 条评分涉及 15 个在 users.dat 中无属性的 UserID。
   F5 增加 `unknown` 列、F6 取 -1、并增加 `has_user_attrs` 标志，
   不把缺失静默编码成全 0。
4. **冷启动回退**：用户或电影无历史时，均值回退到训练期全局均分，并在
   `features_used` 中标记 fallback，供报告分层统计。

特征清单（F1–F6）
-----------------
F1 用户历史均分（数值）      F2 电影历史均分（数值）
F3 电影历史评分次数（log1p） F4 电影类型 multi-hot（18 维）
F5 职业 one-hot（21+unknown）F6 年龄段 ordinal（7 档，缺失为 -1）
另有 has_user_attrs（F5/F6 缺失标志）与三个数值特征合计 45 维。
"""

import os

import numpy as np

from common import split as split_mod
from . import schemas

FEATURE_VERSION = schemas.FEATURE_VERSION


class Dataset(object):
    """清洗快照 + 时间边界 + 累计统计的只读视图。"""

    def __init__(self, clean_dir=None, rules=None):
        self.rules = rules or split_mod.load_rules()
        self.T1, self.T2 = split_mod.time_bounds(self.rules)
        self.clean_dir = split_mod.clean_dir(self.rules, clean_dir)

        self.genres = list(self.rules['genres']['valid'])
        self.genre_index = {g: i for i, g in enumerate(self.genres)}
        self.occupations = list(range(
            int(self.rules['users']['occupation_min']),
            int(self.rules['users']['occupation_max']) + 1,
        ))
        self.ages = [int(a) for a in self.rules['users']['valid_age']]
        self.age_rank = {a: i for i, a in enumerate(self.ages)}

        self.users = _load_users(os.path.join(self.clean_dir, 'users.dat'))
        self.movies = _load_movies(os.path.join(self.clean_dir, 'movies.dat'))
        self.u, self.m, self.r, self.ts = _load_ratings(os.path.join(self.clean_dir, 'ratings.dat'))

        self.train_mask = self.ts <= self.T1
        if not self.train_mask.any():
            raise schemas.ToolError(schemas.DATA_UNAVAILABLE, '训练期为空，检查 T1 与数据版本')
        self.global_mean = float(self.r[self.train_mask].mean())

        self._max_u = int(self.u.max()) + 1
        self._max_m = int(self.m.max()) + 1

        # 用户属性与电影类型（按 ID 索引的数组，缺失为 -1 / 全 0）
        self.occ_idx = np.full(self._max_u, -1, dtype=np.int16)
        self.age_ord = np.full(self._max_u, -1, dtype=np.int16)
        self.has_attrs = np.zeros(self._max_u, dtype=np.float32)
        for uid, attr in self.users.items():
            if uid >= self._max_u:
                continue
            occ = attr.get('occupation')
            age = attr.get('age')
            self.has_attrs[uid] = 1.0
            if occ is not None and occ in self.occupations:
                self.occ_idx[uid] = self.occupations.index(occ)
            self.age_ord[uid] = self.age_rank.get(age, -1)

        self.genre_matrix = np.zeros((self._max_m, len(self.genres)), dtype=np.float32)
        for mid, gen in self.movies.items():
            if mid >= self._max_m:
                continue
            for g in gen:
                j = self.genre_index.get(g)
                if j is not None:
                    self.genre_matrix[mid, j] = 1.0

        self.feature_names = _feature_names(len(self.genres), len(self.occupations))
        self.train_users = set(np.unique(self.u[self.train_mask]).tolist())
        self.train_movies = set(np.unique(self.m[self.train_mask]).tolist())

    # -- 维度与基础信息 ---------------------------------------------------
    @property
    def n_features(self):
        return len(self.feature_names)

    def knows_user(self, user_id):
        uid = int(user_id)
        return uid in self.users or bool((self.u == uid).any())

    def knows_movie(self, movie_id):
        mid = int(movie_id)
        return mid in self.movies or bool((self.m == mid).any())

    def split_of_array(self):
        return np.where(self.ts <= self.T1, 0, np.where(self.ts <= self.T2, 1, 2)).astype(np.int8)

    # -- 训练矩阵 ---------------------------------------------------------
    def build_matrix(self):
        """返回 (X, y, split_codes, meta)。y = 1 当且仅当 Rating >= 4。"""
        n = len(self.r)
        order = np.argsort(self.ts, kind='stable')
        ts_sorted = self.ts[order]

        user_sum = np.zeros(self._max_u, dtype=np.float64)
        user_cnt = np.zeros(self._max_u, dtype=np.int64)
        movie_sum = np.zeros(self._max_m, dtype=np.float64)
        movie_cnt = np.zeros(self._max_m, dtype=np.int64)

        user_mean = np.empty(n, dtype=np.float32)
        movie_mean = np.empty(n, dtype=np.float32)
        movie_count = np.empty(n, dtype=np.float32)

        i = 0
        while i < n:
            j = i + 1
            current_ts = ts_sorted[i]
            while j < n and ts_sorted[j] == current_ts:
                j += 1
            idx = order[i:j]
            uu = self.u[idx]
            mm = self.m[idx]

            cnt_u = user_cnt[uu]
            user_mean[idx] = np.where(cnt_u > 0, user_sum[uu] / np.maximum(cnt_u, 1), self.global_mean)
            cnt_m = movie_cnt[mm]
            movie_mean[idx] = np.where(cnt_m > 0, movie_sum[mm] / np.maximum(cnt_m, 1), self.global_mean)
            movie_count[idx] = cnt_m

            np.add.at(user_sum, uu, self.r[idx])
            np.add.at(user_cnt, uu, 1)
            np.add.at(movie_sum, mm, self.r[idx])
            np.add.at(movie_cnt, mm, 1)
            i = j

        X = self._assemble(user_mean, movie_mean, movie_count,
                           self.u, self.m, self.occ_idx, self.age_ord, self.has_attrs)
        y = (self.r >= 4).astype(np.int8)
        meta = {
            'feature_version': FEATURE_VERSION,
            'data_version': split_mod.data_version(self.rules),
            'cleaning_rule_version': split_mod.rule_version(self.rules),
            'n_rows': int(n),
            'n_features': int(X.shape[1]),
            'global_mean': self.global_mean,
            'missing_user_attrs_rows': int((self.has_attrs[self.u] == 0).sum()),
            'feature_names': list(self.feature_names),
        }
        return X, y, self.split_of_array(), meta

    # -- 单条预测 ---------------------------------------------------------
    def build_row(self, user_id, movie_id, prediction_time=None):
        """构造一条预测特征。

        ``prediction_time`` 为 None 时按训练期快照（ts <= T1）计算，并在
        ``basis`` 中说明；给出时间时只使用严格早于该时间的评分。
        返回 (row, info)，info 含各特征取值、回退标记与口径说明。
        """
        uid, mid = int(user_id), int(movie_id)
        if not self.knows_user(uid):
            raise schemas.ToolError(schemas.UNKNOWN_USER, 'UserID %d 不存在' % uid,
                                    {'user_id': uid})
        if not self.knows_movie(mid):
            raise schemas.ToolError(schemas.UNKNOWN_MOVIE, 'MovieID %d 不存在' % mid,
                                    {'movie_id': mid})

        if prediction_time is None:
            mask = self.ts <= self.T1
            basis = 'train_snapshot(T1=%d)' % self.T1
        else:
            cutoff = int(prediction_time)
            mask = self.ts < cutoff
            basis = 'history_before(prediction_time=%d)' % cutoff

        u_slice = self.u[mask]
        m_slice = self.m[mask]
        r_slice = self.r[mask]

        same_user = u_slice == uid
        same_movie = m_slice == mid
        user_hist_n = int(same_user.sum())
        movie_hist_n = int(same_movie.sum())

        if user_hist_n:
            user_mean = float(r_slice[same_user].mean())
            user_source = 'history'
        else:
            user_mean = self.global_mean
            user_source = 'fallback_global_mean'
        if movie_hist_n:
            movie_mean = float(r_slice[same_movie].mean())
            movie_source = 'history'
        else:
            movie_mean = self.global_mean
            movie_source = 'fallback_global_mean'

        uu = np.array([uid], dtype=np.int64)
        mm = np.array([mid], dtype=np.int64)
        row = self._assemble(
            np.array([user_mean], dtype=np.float32),
            np.array([movie_mean], dtype=np.float32),
            np.array([float(movie_hist_n)], dtype=np.float32),
            uu, mm, self.occ_idx, self.age_ord, self.has_attrs,
        )

        info = {
            'prediction_time_basis': basis,
            'features': {
                'user_mean': round(user_mean, 4),
                'user_history_count': user_hist_n,
                'user_mean_source': user_source,
                'movie_mean': round(movie_mean, 4),
                'movie_history_count': movie_hist_n,
                'movie_mean_source': movie_source,
                'genres': sorted(self.movies.get(mid, [])),
                'occupation': self.users.get(uid, {}).get('occupation'),
                'age': self.users.get(uid, {}).get('age'),
                'has_user_attrs': bool(self.has_attrs[uid] > 0),
            },
        }
        if user_hist_n == 0 or movie_hist_n == 0:
            info['limitations'] = ['用户或电影历史不足，相关特征使用训练期全局均分回退']
        return row, info

    # -- 组装 -------------------------------------------------------------
    def _assemble(self, user_mean, movie_mean, movie_count, u_idx, m_idx, occ_idx, age_ord, has_attrs):
        n = len(user_mean)
        n_genres = len(self.genres)
        n_occ = len(self.occupations) + 1  # 末列 unknown
        X = np.zeros((n, 3 + n_genres + n_occ + 2), dtype=np.float32)
        X[:, 0] = user_mean
        X[:, 1] = movie_mean
        X[:, 2] = np.log1p(movie_count)

        g0 = 3
        X[:, g0:g0 + n_genres] = self.genre_matrix[m_idx]

        o0 = g0 + n_genres
        occ_cols = occ_idx[u_idx].astype(np.int64)
        occ_cols[occ_cols < 0] = len(self.occupations)
        X[np.arange(n), o0 + occ_cols] = 1.0

        a0 = o0 + n_occ
        X[:, a0] = age_ord[u_idx]
        X[:, a0 + 1] = has_attrs[u_idx]
        return X


def _feature_names(n_genres, n_occ_values):
    names = ['user_mean', 'movie_mean', 'log1p_movie_count']
    names += ['genre_%d' % i for i in range(n_genres)]
    names += ['occupation_%d' % o for o in range(n_occ_values)]
    names += ['occupation_unknown']
    names += ['age_ordinal', 'has_user_attrs']
    return names


def _decode(raw):
    return raw.decode('latin-1')


def _load_users(path):
    users = {}
    if not os.path.exists(path):
        raise schemas.ToolError(schemas.DATA_UNAVAILABLE, '缺少 users.dat: %s' % path)
    with open(path, 'rb') as f:
        for line in f:
            parts = _decode(line.rstrip(b'\r\n')).split('::')
            if len(parts) != 5:
                continue
            try:
                users[int(parts[0])] = {
                    'gender': parts[1],
                    'age': int(parts[2]),
                    'occupation': int(parts[3]),
                    'zip': parts[4],
                }
            except ValueError:
                continue
    return users


def _load_movies(path):
    movies = {}
    if not os.path.exists(path):
        raise schemas.ToolError(schemas.DATA_UNAVAILABLE, '缺少 movies.dat: %s' % path)
    with open(path, 'rb') as f:
        for line in f:
            parts = _decode(line.rstrip(b'\r\n')).split('::')
            if len(parts) != 3:
                continue
            try:
                movies[int(parts[0])] = [g for g in parts[2].split('|') if g]
            except ValueError:
                continue
    return movies


def _load_ratings(path):
    us, ms, rs, ts = [], [], [], []
    if not os.path.exists(path):
        raise schemas.ToolError(schemas.DATA_UNAVAILABLE, '缺少 ratings.dat: %s' % path)
    with open(path, 'rb') as f:
        for line in f:
            parts = line.rstrip(b'\r\n').split(b'::')
            if len(parts) != 4:
                continue
            us.append(int(parts[0]))
            ms.append(int(parts[1]))
            rs.append(int(parts[2]))
            ts.append(int(parts[3]))
    if not us:
        raise schemas.ToolError(schemas.DATA_UNAVAILABLE, 'ratings.dat 为空')
    return (np.asarray(us, dtype=np.int64), np.asarray(ms, dtype=np.int64),
            np.asarray(rs, dtype=np.float32), np.asarray(ts, dtype=np.int64))
