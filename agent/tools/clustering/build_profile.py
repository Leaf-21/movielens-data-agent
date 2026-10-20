#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用户偏好画像构建（profile-v1，成员B）

口径（迭代二数据与实验规范 §四 / agent/config/analysis.json）：
  · 只使用迭代一清洗快照 hadoop/output/clean/（movielens-1m-v2-clean-v1）；
  · 只用训练期记录：Timestamp <= T1（T1 运行时读取 rules.json 登记值）；
  · 训练期评分数 < min_train_ratings 的用户标记 INSUFFICIENT_HISTORY，
    不参与聚类拟合，也不被强行赋予可信群体结论；
  · 特征均记录名称/含义/聚合方式/时间窗/缺失处理（特征字典在配置文件）；
  · z-score 标准化统计量只由画像可用用户拟合，保存在画像元数据中，
    供降维（成员C）等后续步骤对同一批向量复用，不重新拟合。

独立运行（交付清单"工具可独立运行"）：
  python3 agent/tools/clustering/build_profile.py [--force]

产出（默认 agent/artifacts/profiles/，入 Git 供迭代三使用）：
  profile-v1.jsonl      每用户一行：uid/状态/原始特征/标准化向量
  profile-v1.meta.json  输入校验值、T1/T2、特征顺序、scaler、代码 commit 等
"""

import argparse
import io
import json
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS_DIR = os.path.dirname(_HERE)                      # agent/tools
_SRC_DIR = os.path.join(os.path.dirname(_TOOLS_DIR), 'src')  # agent/src
# _HERE 必须优先：agent/tools/common 是数据包，不提供聚类侧 AnalysisError。
for _p in (_TOOLS_DIR, _SRC_DIR, _HERE):
    if _p in sys.path:
        sys.path.remove(_p)
    sys.path.insert(0, _p)

import config                                  # noqa: E402
from common import AnalysisError, sha256_file, code_version, now_utc  # noqa: E402

BASE_FEATURES = ('n_ratings', 'avg_rating', 'std_rating', 'rating_bias',
                 'high_share', 'avg_movie_pop', 'share_top_pop',
                 'active_span_days', 'avg_gap_days')
STATUS_OK = 'OK'
STATUS_INSUFFICIENT = 'INSUFFICIENT_HISTORY'

DELIM = '::'


def _genre_feature_names(genres):
    # 类型名含空格/撇号（如 Children's），特征名规范化为 genre_share_<slug>
    return [('genre_share_%s' % g.lower().replace("'", '').replace(' ', '_'))
            for g in genres]


def feature_names(genres):
    return list(BASE_FEATURES) + _genre_feature_names(genres)


def load_movies(clean_dir):
    """movie_id -> (title, year, genres set)。ISO-8859-1 解码。"""
    movies = {}
    p = os.path.join(clean_dir, 'movies.dat')
    with io.open(p, encoding='latin-1') as f:
        for line in f:
            parts = line.rstrip('\n').split(DELIM)
            if len(parts) < 3:
                continue
            mid = int(parts[0])
            title = parts[1]
            year = None
            if title.endswith(')') and '(' in title:
                try:
                    year = int(title[title.rfind('(') + 1:-1])
                except ValueError:
                    year = None
            genres = set(g for g in parts[2].split('|') if g)
            movies[mid] = (title, year, genres)
    if not movies:
        raise AnalysisError('DATA_UNAVAILABLE', '清洗快照 movies.dat 为空或不可读: %s' % p)
    return movies


def load_users(clean_dir):
    p = os.path.join(clean_dir, 'users.dat')
    uids = set()
    with io.open(p, encoding='latin-1') as f:
        for line in f:
            parts = line.rstrip('\n').split(DELIM)
            if parts and parts[0].isdigit():
                uids.add(int(parts[0]))
    return uids


def train_passes(clean_dir, t1_epoch, movies):
    """
    两遍扫描训练期评分：
      1) 电影热度（训练期评分数）
      2) 逐用户聚合
    返回 (popularity, user_stats, global_mean, n_train_rows)。
    """
    p = os.path.join(clean_dir, 'ratings.dat')
    if not os.path.exists(p):
        raise AnalysisError('DATA_UNAVAILABLE',
                            '找不到清洗快照评分文件: %s（请先完成迭代一清洗流程）' % p)
    popularity = {}
    n_train = 0
    total = 0
    with io.open(p, encoding='latin-1') as f:
        for line in f:
            total += 1
            parts = line.rstrip('\n').split(DELIM)
            if len(parts) != 4:
                continue
            if int(parts[3]) <= t1_epoch:
                mid = int(parts[2 - 1])  # MovieID
                popularity[mid] = popularity.get(mid, 0) + 1
                n_train += 1
    # 第二遍：逐用户
    stats = {}   # uid -> dict(计数累加器)
    pairs = {}   # uid -> set(movie_id) 与 (mid,rating) 明细分开存
    with io.open(p, encoding='latin-1') as f:
        for line in f:
            parts = line.rstrip('\n').split(DELIM)
            if len(parts) != 4:
                continue
            ts = int(parts[3])
            if ts > t1_epoch:
                continue
            uid, mid, r = int(parts[0]), int(parts[1]), int(parts[2])
            s = stats.get(uid)
            if s is None:
                s = stats[uid] = {'n': 0, 'sum': 0, 'sumsq': 0, 'high': 0,
                                  'min_ts': ts, 'max_ts': ts, 'pop_sum': 0.0,
                                  'top_pop_n': 0}
                pairs[uid] = {}
            s['n'] += 1
            s['sum'] += r
            s['sumsq'] += r * r
            s['high'] += 1 if r >= 4 else 0
            s['min_ts'] = min(s['min_ts'], ts)
            s['max_ts'] = max(s['max_ts'], ts)
            s['pop_sum'] += math.log1p(popularity.get(mid, 0))
            prev = pairs[uid].get(mid)
            if prev is None or r > prev:
                pairs[uid][mid] = r
    # 热度前四分位阈值（按训练期热度）
    pops = sorted(popularity.values(), reverse=True)
    top_q = pops[max(0, len(pops) // 4 - 1)] if pops else 0
    global_mean = sum(s['sum'] for s in stats.values()) / float(n_train) if n_train else 0.0
    top_sets = {mid for mid, c in popularity.items() if c >= top_q}
    return stats, pairs, popularity, global_mean, top_sets, total


def build_user_feature(uid, s, rated_movies, movies, popularity, global_mean,
                       top_sets, genres, gnames):
    n = s['n']
    avg = s['sum'] / float(n)
    var = max(s['sumsq'] / float(n) - avg * avg, 0.0)
    uniq = len(rated_movies)
    span = (s['max_ts'] - s['min_ts']) / 86400.0
    feats = {
        'n_ratings': float(n),
        'avg_rating': avg,
        'std_rating': math.sqrt(var) if n >= 2 else 0.0,
        'rating_bias': avg - global_mean,
        'high_share': s['high'] / float(n),
        'avg_movie_pop': s['pop_sum'] / float(n),
        'share_top_pop': sum(1 for m in rated_movies if m in top_sets) / float(uniq),
        'active_span_days': span,
        'avg_gap_days': (span / (n - 1)) if n >= 2 else 0.0,
    }
    gcount = dict.fromkeys(genres, 0)
    for mid in rated_movies:
        for g in movies[mid][2] & set(genres):
            gcount[g] += 1
    for g, name in zip(genres, gnames):
        feats[name] = gcount[g] / float(uniq)
    return feats


def build_profile(analysis_cfg, rules_cfg, force=False, quiet=False):
    """构建/复用画像。返回 (profile_path, meta)。"""
    base = config.resolve_repo_path('.')
    clean_dir = config.resolve_repo_path(analysis_cfg['input']['clean_dir'])
    art_dir = config.resolve_repo_path(analysis_cfg['artifacts']['profiles_dir'])
    pv = analysis_cfg['profile_version']
    prof_path = os.path.join(art_dir, pv + '.jsonl')
    meta_path = os.path.join(art_dir, pv + '.meta.json')

    t1_epoch = int(rules_cfg['time']['T1_epoch'])
    t2_epoch = int(rules_cfg['time']['T2_epoch'])
    min_n = int(analysis_cfg['min_train_ratings'])
    genres = list(rules_cfg['genres']['valid'])
    gnames = _genre_feature_names(genres)
    fnames = feature_names(genres)

    input_hashes = {}
    for fn in ('ratings.dat', 'movies.dat', 'users.dat'):
        fp = os.path.join(clean_dir, fn)
        if not os.path.exists(fp):
            raise AnalysisError('DATA_UNAVAILABLE',
                                '清洗快照缺少 %s（期望目录: %s）' % (fn, clean_dir),
                                {'hint': '请确认迭代一清洗任务已成功产出 hadoop/output/clean/'})
        input_hashes[fn] = sha256_file(fp)

    cfg_fp = json.dumps([pv, min_n, fnames, t1_epoch], sort_keys=True)
    if not force and os.path.exists(prof_path) and os.path.exists(meta_path):
        with open(meta_path, 'r', encoding='utf-8') as f:
            meta = json.load(f)
        if (meta.get('input_sha256') == input_hashes
                and meta.get('config_fingerprint') == cfg_fp):
            if not quiet:
                print('[profile] 复用已有画像 %s（输入与口径未变化）' % pv)
            return prof_path, meta

    movies = load_movies(clean_dir)
    all_users = load_users(clean_dir)
    stats, rated, popularity, global_mean, top_sets, total_rows = train_passes(
        clean_dir, t1_epoch, movies)
    # 迭代一孤儿引用：训练期评分出现过但不在 users.dat 的用户。
    # 画像域以 users.dat 为准（UNKNOWN_USER 判定域一致），孤儿不计入画像，
    # 数量如实登记进 meta 与 limitations，不静默丢弃。
    orphans = sorted(set(stats) - all_users)

    raw_feats = {}
    n_ok = n_insufficient = n_no_hist = 0
    for uid in sorted(all_users):
        s = stats.get(uid)
        if s is None:
            raw_feats[uid] = None
            n_no_hist += 1
            continue
        if s['n'] < min_n:
            # 仍记录特征（便于解释），但标记不足、不参与拟合
            raw_feats[uid] = build_user_feature(uid, s, rated[uid], movies,
                                                popularity, global_mean,
                                                top_sets, genres, gnames)
            raw_feats[uid]['_status_override'] = STATUS_INSUFFICIENT
            n_insufficient += 1
            continue
        raw_feats[uid] = build_user_feature(uid, s, rated[uid], movies,
                                            popularity, global_mean,
                                            top_sets, genres, gnames)
        n_ok += 1

    # scaler：只用 OK 用户
    mean = {}
    std = {}
    for name in fnames:
        vals = [f[name] for f in raw_feats.values()
                if f is not None and '_status_override' not in f]
        m = sum(vals) / len(vals) if vals else 0.0
        v = sum((x - m) ** 2 for x in vals) / len(vals) if vals else 0.0
        mean[name] = m
        std[name] = math.sqrt(v)

    os.makedirs(art_dir, exist_ok=True)
    tmp = prof_path + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8') as f:
        for uid in sorted(all_users):
            feats = raw_feats[uid]
            if feats is None:
                rec = {'user_id': uid, 'status': STATUS_INSUFFICIENT,
                       'fit': False, 'features': None, 'vector': None,
                       'note': '训练期(Timestamp<=T1)无任何评分记录，无法构造画像向量'}
            else:
                status = feats.pop('_status_override', STATUS_OK)
                vec = [((feats[name] - mean[name]) / std[name]) if std[name] > 1e-12
                       else 0.0 for name in fnames]
                # 历史不足用户：特征与向量仍可计算（供 K-Means 低可信最近质心参考），
                # 但不参与拟合与 scaler；DBSCAN 对其只报未分配。
                rec = {'user_id': uid, 'status': status,
                       'fit': status == STATUS_OK,
                       'features': feats, 'vector': vec,
                       'note': (None if status == STATUS_OK else
                                '训练期评分 %d 条 < 最小历史 %d 条，不参与拟合'
                                % (int(feats['n_ratings']), min_n))}
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    os.replace(tmp, prof_path)

    meta = {
        'profile_version': pv,
        'data_version': analysis_cfg['input']['data_version'],
        'clean_dir': os.path.relpath(clean_dir, base),
        'input_sha256': input_hashes,
        'input_total_rows': {'ratings_all': total_rows},
        'T1': rules_cfg['time']['T1'], 'T2': rules_cfg['time']['T2'],
        'T1_epoch': t1_epoch, 'T2_epoch': t2_epoch,
        'min_train_ratings': min_n,
        'feature_names': fnames,
        'feature_dict': analysis_cfg['feature_dict'],
        'scaler': {'type': 'zscore_fit_on_ok_users', 'mean': mean, 'std': std,
                   'zero_std_columns_kept_zero': [n for n in fnames if std[n] <= 1e-12]},
        'n_users_total': len(all_users),
        'n_profile_ok': n_ok,
        'n_insufficient_history': n_insufficient,
        'n_no_train_history': n_no_hist,
        'n_train_users_not_in_users_dat': len(orphans),
        'orphan_user_ids': orphans,
        'n_train_ratings_used': sum(int(s['n']) for uid, s in stats.items()),
        'global_train_mean_rating': global_mean,
        'config_fingerprint': cfg_fp,
        'code_version': code_version(),
        'created_at': now_utc(),
        'window_note': '特征只用 Timestamp<=T1 训练期记录（数据与实验规范 §四.1）',
    }
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    if not quiet:
        print('[profile] 已生成 %s: OK=%d 历史不足=%d 无训练记录=%d（训练期用 %d 人）'
              % (pv, n_ok, n_insufficient + n_no_hist, n_no_hist, len(stats)))
    return prof_path, meta


def load_profile(prof_path):
    """读画像 JSONL -> users: {uid: rec}。"""
    users = {}
    with io.open(prof_path, encoding='utf-8') as f:
        for line in f:
            rec = json.loads(line)
            users[rec['user_id']] = rec
    return users


def snapshot_for_summaries(analysis_cfg):
    """群体摘要/代表性内容需要原始评分对，这里从快照现算（不落中间文件）。
    返回 (rated: uid->{mid:best_rating}, movies, title_of(mid))。"""
    base = config.resolve_repo_path('.')
    rules_cfg = config.load_rules()
    clean_dir = config.resolve_repo_path(analysis_cfg['input']['clean_dir'])
    t1 = int(rules_cfg['time']['T1_epoch'])
    movies = load_movies(clean_dir)
    rated = {}
    p = os.path.join(clean_dir, 'ratings.dat')
    with io.open(p, encoding='latin-1') as f:
        for line in f:
            parts = line.rstrip('\n').split(DELIM)
            if len(parts) != 4 or int(parts[3]) > t1:
                continue
            uid, mid, r = int(parts[0]), int(parts[1]), int(parts[2])
            d = rated.setdefault(uid, {})
            if r > d.get(mid, 0):
                d[mid] = r
    return rated, movies


def main():
    ap = argparse.ArgumentParser(description='构建/复用 profile-v1 用户画像')
    ap.add_argument('--force', action='store_true', help='忽略缓存重新构建')
    args = ap.parse_args()
    acfg = config.load_analysis()
    path, meta = build_profile(acfg, config.load_rules(), force=args.force)
    print(json.dumps({k: meta[k] for k in
                      ('profile_version', 'n_users_total', 'n_profile_ok',
                       'n_insufficient_history', 'n_no_train_history',
                       'input_sha256', 'code_version', 'created_at')},
                     ensure_ascii=False, indent=2))
    try:
        display_path = os.path.relpath(path, config.REPO_DIR)
    except ValueError:
        display_path = path
    print('->', display_path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
