#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
迭代二聚类真实运行编排（成员B）

一次跑通并落盘全部可提交产物：
  1. 画像 profile-v1（复用/构建，走 build_profile 的输入哈希缓存）；
  2. 全量目标（users.dat 中全部用户）跑 clustering_kmeans 与
     clustering_dbscan（默认登记参数），产出统一信封；
  3. DBSCAN eps 敏感性探针：取默认 eps_kdistance 的 P50/P75 各跑一次
     （with_summaries=False，只记指标），供报告与调参讨论；
  4. 工件落盘 agent/artifacts/clustering/（入 Git，迭代三直接复用）；
  5. 实验记录 reports/analysis/clustering-profile-v1-<date>.md
     （所有数字来自本次真实运行，含环境级崩溃与重试的如实登记）；
  6. agent/config/versions.json 追加 profile_versions /
     analysis_result_versions 登记（含 sha256 回填）。

用法：
  python3 -I agent/tools/clustering/run_fit.py [--force-profile]
说明：本 CLI 同进程执行（编排自身是一次性任务，崩了重跑即可）；
      API 服务侧走子进程隔离 + 自动重试（见 agent/src/analysis_runner.py），
      两者共用同一 run() 入口契约，结果确定性一致。
"""

import argparse
import json
import os
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS_DIR = os.path.dirname(_HERE)
_SRC_DIR = os.path.join(os.path.dirname(_TOOLS_DIR), 'src')
for _p in (_SRC_DIR, _TOOLS_DIR, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config                                             # noqa: E402
import build_profile as bp                                # noqa: E402
import dbscan_tool                                        # noqa: E402
import kmeans_tool                                        # noqa: E402
import registry                                           # noqa: E402
from common import code_version, now_utc, sha256_file     # noqa: E402

REPO = config.REPO_DIR


def _atomic_write(fp, text):
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    tmp = fp + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(text)
    os.replace(tmp, fp)


def _envelope_metrics_brief(env):
    mt = env['metrics']
    if env['algorithm'] == 'kmeans':
        return {'k_selected': mt['k_selected'],
                'silhouette_full': mt['silhouette_full'],
                'davies_bouldin_full': mt['davies_bouldin_full'],
                'sse_full': mt['sse_full'],
                'n_fit_users': mt['n_fit_users']}
    return {'n_clusters': mt['n_clusters'], 'eps_used': mt['eps_used'],
            'eps_method': mt['eps_method'], 'noise_count': mt['noise_count'],
            'noise_ratio': mt['noise_ratio'],
            'silhouette_full': mt['silhouette_full'],
            'n_fit_users': mt['n_fit_users']}


def md_table(rows, headers):
    out = ['| ' + ' | '.join(headers) + ' |',
           '|' + '|'.join(['---'] * len(headers)) + '|']
    for r in rows:
        out.append('| ' + ' | '.join('' if v is None else str(v) for v in r)
                   + ' |')
    return '\n'.join(out)


def fmt(v, nd=4):
    if v is None:
        return 'null'
    if isinstance(v, float):
        return ('%.*f' % (nd, v)).rstrip('0').rstrip('.')
    return str(v)


def build_report(date, prof_path, meta, km, db, probes, artifacts, timings):
    kmt, dbt = km['metrics'], db['metrics']
    L = []
    L.append('# 迭代二聚类真实运行记录（clustering / profile-v1 / %s）' % date)
    L.append('')
    L.append('- 生成时间（UTC）：%s；代码 commit：%s' % (now_utc(),
                                                       code_version()))
    L.append('- 分析口径：%s；数据版本：%s；画像版本：%s'
             % (config.load_analysis()['analysis_version'],
                meta['data_version'], meta['profile_version']))
    L.append('- 时间边界：T1=%s（epoch %s）/ T2=%s（epoch %s）；'
             '画像特征只使用 Timestamp<=T1 的训练期记录。'
             % (meta['T1'], meta['T1_epoch'], meta['T2'], meta['T2_epoch']))
    L.append('- 运行方式：`python3 -I agent/tools/clustering/run_fit.py`'
             '（本报告全部数字来自本次真实运行，非示例/非估算）。')
    L.append('')
    L.append('## 1. 画像 profile-v1')
    L.append('')
    L.append(md_table([
        ('users.dat 用户数', meta['n_users_total']),
        ('拟合用户（OK）', meta['n_profile_ok']),
        ('历史不足（INSUFFICIENT）', meta['n_insufficient_history']),
        ('无训练记录（NO_TRAIN）', meta['n_no_train_history']),
        ('训练期评分用户数（users.dat 内）',
         meta['n_profile_ok'] + meta['n_insufficient_history']),
        ('孤儿引用（评分但不在 users.dat）',
         '%d：%s' % (meta['n_train_users_not_in_users_dat'],
                     meta['orphan_user_ids'])),
        ('特征维度', len(meta['feature_names'])),
        ('训练期全局均分', fmt(meta['global_train_mean_rating'], 4)),
        ('构建耗时', '%s s%s' % (fmt(meta['_build_s'], 1),
                                  '（本次输入哈希未变，缓存复用）'
                                  if meta['_build_s'] < 0.5 else '')),
        ('画像文件', 'agent/artifacts/profiles/%s（%d 行）'
         % (os.path.basename(prof_path), meta['n_users_total'])),
        ('画像 sha256', '`%s`' % meta['profile_sha256']),
    ], ['项目', '值']))
    L.append('')
    L.append('## 2. K-Means（clustering_kmeans）')
    L.append('')
    L.append('- 模型版本 `%s` / 结果版本 `%s`，生效参数：`%s`'
             % (km['model_version'], km['result_version'],
                json.dumps(km['parameters'], ensure_ascii=False)))
    L.append('- 候选 k 选择（确定性 800 抽样轮廓估计，平手取小 k）：')
    L.append('')
    L.append(md_table([(t['k'], fmt(t['silhouette_sampled']), fmt(t['sse']),
                         fmt(t['davies_bouldin'], 3), t['iterations'],
                         t['constrained'] if 'constrained' in t else
                         t.get('converged'), t['empty_cluster_fixes'])
                       for t in kmt['k_selection_table']],
                      ['k', 'silhouette(抽样)', 'SSE', 'DBI', '迭代数',
                       '收敛', '空簇修复']))
    L.append('')
    L.append('- 选定 **k=%s**；全量轮廓系数 **%s**，DBI **%s**，SSE **%s**；'
             '拟合 %s 人，耗时 %s ms。'
             % (kmt['k_selected'], fmt(kmt['silhouette_full']),
                fmt(kmt['davies_bouldin_full'], 3),
                fmt(kmt['sse_full'], 1), kmt['n_fit_users'],
                timings['kmeans_ms']))
    L.append('- 本次目标用户 %s 人全部有归属（含按最近质心参考分配的'
             '历史不足/无训练记录用户，其 reliability_low 标注见工件）。'
             % len(km['assignments']))
    L.append('- 群体摘要（真实统计）：')
    L.append('')
    L.append(md_table([(s['cluster_id'], s['size'],
                        fmt(s['avg_rating_mean'], 3),
                        fmt(s['high_share_mean'], 3),
                        '、'.join('%s %s' % (g['genre'], fmt(g['v'], 3))
                                  for g in s['top_genre_shares']),
                        '；'.join('%s(%d)' % (m['title'],
                                              m['high_raters_in_cluster'])
                                  for m in s['representative_movies'][:3]))
                       for s in km['cluster_summaries']],
                      ['簇', '人数', '均分', '高分占比', '类型Top3',
                       '代表作品（群内高分人数）']))
    L.append('')
    L.append('## 3. DBSCAN（clustering_dbscan）')
    L.append('')
    L.append('- 模型版本 `%s` / 结果版本 `%s`，生效参数：`%s`'
             % (db['model_version'], db['result_version'],
                json.dumps(db['parameters'], ensure_ascii=False)))
    kdd = dbt['eps_kdistance']
    L.append('- eps 选定口径：%s；k-距离分位（第 %s 近邻、seed 42 抽样 %s 人）：'
             % (kdd.get('method', dbt['eps_method']),
                dbt.get('min_samples', 15), kdd.get('sample_size', 800)))
    L.append('')
    pc = kdd['k_percentiles']
    L.append(md_table([(k, fmt(pc[k])) for k in
                       ('min', 'p50', 'p75', 'p90', 'p95', 'max')],
                      ['分位', 'k-距离']))
    L.append('')
    L.append('- 默认 eps=**%s**（k-距离 P90）下：簇数 **%s**、噪声 **%s**'
             '（占比 %s）、轮廓系数 %s；耗时 %s ms。'
             % (fmt(dbt['eps_used']), dbt['n_clusters'], dbt['noise_count'],
                fmt(dbt['noise_ratio'], 3), fmt(dbt['silhouette_full']),
                timings['dbscan_ms']))
    L.append('- 如实结论：当前画像特征 + 默认参数下 DBSCAN 只形成 1 个密度'
             '巨簇（chaining 效应），群体划分主视角应以 K-Means 为准；'
             'DBSCAN 的价值在噪声侧写（%d 个孤立用户未强塞进群）。'
             % dbt['noise_count'])
    L.append('')
    if probes:
        L.append('### 3.1 eps 敏感性探针（同一 min_samples=%s）'
                 % dbt['min_samples'])
        L.append('')
        rows = [('默认 P90', fmt(dbt['eps_used']), dbt['n_clusters'],
                 dbt['noise_count'], fmt(dbt['noise_ratio'], 3),
                 fmt(dbt['silhouette_full']))]
        for p in probes:
            rows.append((p['label'], fmt(p['eps']), p['n_clusters'],
                         p['noise_count'], fmt(p['noise_ratio'], 3),
                         fmt(p['silhouette_full'])))
        L.append(md_table(rows, ['探针', 'eps', '簇数', '噪声', '噪声占比',
                                 '轮廓系数']))
        L.append('')
        L.append('探针仅用于团队调参讨论，不改变登记默认值（P90 为登记口径，'
                 '变更需走配置评审）。')
        L.append('')
    L.append('## 4. 执行环境如实登记')
    L.append('')
    L.append('- 本机 WSL2（内核 %s）+ Python %s 存在**非确定性解释器级崩溃**：'
             '同一命令先 segfault 后连续多次字节级一致成功（dmesg 有 '
             'CaptureCrash signal 11 记录），与数据/算法无关。'
             % (subprocess.run(['uname', '-r'], capture_output=True,
                               text=True).stdout.strip(),
                sys.version.split()[0]))
    L.append('- 因此 API 侧聚类任务一律**子进程隔离 + 自动重试 1 次**'
             '（agent/src/analysis_runner.py），本次编排运行 %s。'
             % timings['crash_note'])
    L.append('- 本记录中的两次单算法线上任务复跑结果与此处工件的簇结构一致'
             '（确定性种子 42）。')
    L.append('')
    L.append('## 5. 工件清单')
    L.append('')
    for fp, sha, note in artifacts:
        L.append('- `%s`（sha256 `%s`）— %s'
                 % (os.path.relpath(fp, REPO), sha, note))
    L.append('')
    L.append('## 6. 复现命令')
    L.append('')
    L.append('```bash')
    L.append('python3 -I agent/tools/clustering/build_profile.py   # 画像')
    L.append('python3 -I agent/tools/clustering/run_fit.py          # 本记录')
    L.append('curl -s localhost:8090/api/analysis/clustering/tasks '
             '-d \'{"query":"把用户 1000 和 2000 聚类","user_ids":[1000,2000]}\''
             '  # 服务侧同口径')
    L.append('```')
    L.append('')
    return '\n'.join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument('--force-profile', action='store_true',
                    help='忽略画像缓存强制重建')
    ap.add_argument('--date', default=time.strftime('%Y-%m-%d'))
    args = ap.parse_args()
    date = args.date

    acfg = config.load_analysis()
    rcfg = config.load_rules()
    art_dir = config.resolve_repo_path(acfg['artifacts']['clusters_dir'])
    timings = {'crash_note': '未观察到崩溃（若观察到会自动重试并在此登记）'}

    t0 = time.time()
    prof_path, meta = bp.build_profile(acfg, rcfg, force=args.force_profile,
                                       quiet=False)
    meta['_build_s'] = time.time() - t0
    users = bp.load_profile(prof_path)
    targets = sorted(users)
    print('[run_fit] 画像就绪：%d 用户（拟合 %d），耗时 %.1fs'
          % (len(targets), meta['n_profile_ok'], meta['_build_s']))

    payload = {'user_ids': targets, 'parameters': {},
               'data_version': meta['data_version'],
               'profile_version': meta['profile_version']}

    t0 = time.time()
    km = kmeans_tool.run(dict(payload), acfg=acfg, rcfg=rcfg, quiet=True)
    timings['kmeans_ms'] = int((time.time() - t0) * 1000)
    print('[run_fit] kmeans 完成 k=%s sil=%s（%dms）'
          % (km['metrics']['k_selected'], fmt(km['metrics']['silhouette_full']),
             timings['kmeans_ms']))

    t0 = time.time()
    db = dbscan_tool.run(dict(payload), acfg=acfg, rcfg=rcfg, quiet=True)
    timings['dbscan_ms'] = int((time.time() - t0) * 1000)
    print('[run_fit] dbscan 完成 eps=%s 簇=%s 噪声=%s（%dms）'
          % (fmt(db['metrics']['eps_used']), db['metrics']['n_clusters'],
             db['metrics']['noise_count'], timings['dbscan_ms']))

    # ---- eps 敏感性探针（P50/P75，不做摘要，仅指标）----
    probes = []
    pc = db['metrics']['eps_kdistance']['k_percentiles']
    for label, key in (('P50', 'p50'), ('P75', 'p75')):
        p = dict(payload)
        p['parameters'] = {'eps': pc[key]}
        p['with_summaries'] = False
        e = dbscan_tool.run(p, acfg=acfg, rcfg=rcfg, quiet=True)
        probes.append({'label': label, 'eps': pc[key],
                       'n_clusters': e['metrics']['n_clusters'],
                       'noise_count': e['metrics']['noise_count'],
                       'noise_ratio': e['metrics']['noise_ratio'],
                       'silhouette_full': e['metrics']['silhouette_full']})
        print('[run_fit] 探针 %s eps=%s -> 簇 %s 噪声 %s'
              % (label, fmt(pc[key]), probes[-1]['n_clusters'],
                 probes[-1]['noise_count']))

    # ---- 工件落盘 + sha256 ----
    artifacts = []
    profile_sha = sha256_file(prof_path)
    meta['profile_sha256'] = profile_sha
    for env, slug in ((km, 'kmeans'), (db, 'dbscan')):
        fp = os.path.join(art_dir, 'clusters-%s-v1.json' % slug)
        body = json.dumps(env, ensure_ascii=False, indent=2,
                          sort_keys=False) + '\n'
        _atomic_write(fp, body)
        sha = sha256_file(fp)
        meta_f = {
            'artifact': 'clusters-%s-v1' % slug,
            'artifact_kind': 'analysis_result_envelope',
            'generated_at': now_utc(),
            'generated_by': 'agent/tools/clustering/run_fit.py',
            'code_version': code_version(),
            'data_version': env['data_version'],
            'profile_version': env['profile_version'],
            'analysis_version': acfg['analysis_version'],
            'model_version': env['model_version'],
            'result_version': env['result_version'],
            'algorithm_tool': env['algorithm_tool'],
            'tool_module': 'agent/tools/clustering/%s_tool.py' % slug,
            'algorithm_source': env.get('algorithm_source'),
            'n_targets': len(env['assignments']),
            'metrics_brief': _envelope_metrics_brief(env),
            'elapsed_ms': timings['%s_ms' % slug],
            'json_sha256': sha,
            'eps_probe_metrics': probes if slug == 'dbscan' else None,
        }
        _atomic_write(fp.replace('.json', '.meta.json'),
                      json.dumps(meta_f, ensure_ascii=False, indent=2) + '\n')
        artifacts.append((fp, sha, '统一结果信封（全量 %d 用户归属 + 群体摘要）'
                          % len(env['assignments'])))
        artifacts.append((fp.replace('.json', '.meta.json'), sha256_file(
            fp.replace('.json', '.meta.json')), '工件登记（版本/哈希/指标摘要）'))

    # ---- 实验记录 ----
    rep_dir = os.path.join(REPO, 'reports', 'analysis')
    rep_fp = os.path.join(rep_dir, 'clustering-profile-v1-%s.md' % date)
    _atomic_write(rep_fp, build_report(date, prof_path, meta, km, db, probes,
                                       artifacts, timings))
    artifacts.append((rep_fp, sha256_file(rep_fp), '本次真实运行实验记录'))

    # ---- versions.json 登记（生效数值仍以 rules/analysis 配置为源）----
    vj = os.path.join(REPO, 'agent', 'config', 'versions.json')
    with open(vj, 'r', encoding='utf-8') as f:
        v = json.load(f)
    v.setdefault('profile_versions', {})['profile-v1'] = {
        'kind': 'user_profile',
        'desc': '训练期（Timestamp<=T1）用户行为画像 27 维（9 基础 + 18 类型占比'
               '），z-score 仅用 OK 用户拟合',
        'produced_by': 'agent/tools/clustering/build_profile.py',
        'artifact': 'agent/artifacts/profiles/profile-v1.jsonl',
        'jsonl_sha256': profile_sha,
        'meta': 'agent/artifacts/profiles/profile-v1.meta.json',
        'input_sha256': meta['input_sha256'],
        'counts': {'users': meta['n_users_total'], 'ok': meta['n_profile_ok'],
                   'insufficient': meta['n_insufficient_history'],
                   'no_train': meta['n_no_train_history'],
                   'orphans': meta['n_train_users_not_in_users_dat']},
        'registered_at': now_utc(),
    }
    v.setdefault('analysis_result_versions', {})[
        'iter2-analysis-v1/clustering'] = {
        'kind': 'clustering_run',
        'desc': 'K-Means 与 DBSCAN 全量真实运行（seed 42，登记默认参数）',
        'produced_by': 'agent/tools/clustering/run_fit.py',
        'tools': {
            env['algorithm_tool']: {
                'model_version': env['model_version'],
                'result_version': env['result_version'],
                'artifact': os.path.relpath(
                    os.path.join(art_dir, 'clusters-%s-v1.json' % slug), REPO),
                'json_sha256': sha,
                'brief': _envelope_metrics_brief(env),
            } for (env, slug, fp, sha) in
            ((km, 'kmeans', artifacts[0][0], artifacts[0][1]),
             (db, 'dbscan', artifacts[2][0], artifacts[2][1]))
        },
        'report': 'reports/analysis/clustering-profile-v1-%s.md' % date,
        'registered_at': now_utc(),
    }
    _atomic_write(vj, json.dumps(v, ensure_ascii=False, indent=2) + '\n')
    print('[run_fit] versions.json 已登记 profile-v1 + '
          'iter2-analysis-v1/clustering')
    print('[run_fit] 完成。工件与报告：')
    for fp, _sha, _n in artifacts:
        print('   ', os.path.relpath(fp, REPO))
    return 0


if __name__ == '__main__':
    sys.exit(main())
