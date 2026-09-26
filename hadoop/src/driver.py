#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MovieLens 数据治理 Driver

职责：
  1. 依次运行检查作业（格式检查 / 跨表引用 / 唯一性 / 一致性）
  2. 汇总各作业输出的计数指标
  3. 按 docs/evaluation-method.md 的公式计算五维得分
  4. 输出符合 docs/接口规范文档.md 契约的 JSON

三个阶段（对应 docs/接口规范文档.md 第 9、10、11 节的三个接口）
  before  清洗前质量评分
  clean   数据清洗
  after   清洗后质量评分
  all     一次跑完（等价于 before，供联调与报告使用）

运行模式：
  --mode hadoop  通过 hadoop/scripts/run_check.sh 提交 Hadoop Streaming 作业（正式运行）
  --mode local   在本机用文件模拟 shuffle（开发调试用，结果应与 hadoop 一致）

用法：
  python3 hadoop/src/driver.py --mode local
  python3 hadoop/src/driver.py --mode hadoop --task-id task_001
  python3 hadoop/src/driver.py --mode hadoop --stage before --task-id task_001
  python3 hadoop/src/driver.py --mode hadoop --stage clean  --task-id task_001

⚠️ 关于"真实结果"的要求：
  本程序不使用任何占位数据。所有数值均来自实际扫描数据文件的统计。
  某个阶段尚未实现或执行失败时，程序**明确报错退出**，绝不返回占位结果。
  依据：docs/接口规范文档.md 第 2.2 节、第 15 节
        docs/迭代一_Hadoop数据清洗与Agent基础.md 第 80 行
"""

import argparse
import datetime
import json
import os
import subprocess
import sys

# --- 路径 ---
DRIVER_DIR = os.path.dirname(os.path.abspath(__file__))          # hadoop/src
HADOOP_DIR = os.path.dirname(DRIVER_DIR)                          # hadoop
REPO_DIR = os.path.dirname(HADOOP_DIR)                            # 仓库根
CHECK_DIR = os.path.join(DRIVER_DIR, 'check')
COMMON_DIR = os.path.join(DRIVER_DIR, 'common')
PIPELINE_DIR = os.path.join(DRIVER_DIR, 'pipeline')

sys.path.insert(0, COMMON_DIR)
sys.path.insert(0, PIPELINE_DIR)
import ml_common as ml
import problems as problems_mod
import report as report_mod

RUN_CHECK_SH = os.path.join(HADOOP_DIR, 'scripts', 'run_check.sh')

# 五个维度的字段名与顺序（依据接口规范第 12 节）
DIM_ORDER = ('accurate', 'complete', 'unique', 'up_to_date', 'consistent')

# 任务状态文件与产物的存放位置
REPORT_DIR = os.path.join(REPO_DIR, 'reports', 'quality-report')
CLEAN_DATA_DIR = os.path.join(HADOOP_DIR, 'output', 'clean')
ISOLATED_DATA_DIR = os.path.join(HADOOP_DIR, 'output', 'isolated')


# ---------------------------------------------------------------------------
# 作业清单
#   每个作业对应一类检查，job 名与 run_check.sh 的分派名一致
# ---------------------------------------------------------------------------
JOBS = [
    'format-ratings', 'format-movies', 'format-users',
    'cross-users', 'cross-movies',
    'group-u-pair', 'group-u-movie', 'group-u-user',
    'group-c-movie-multi', 'group-c-user-attr',
]

# 本地模式下每个作业的 (mapper 命令, reducer 命令, 参与的表)
# 不再用 shell 管道模板拼命令：那种写法容易漏掉输入重定向，
# 且一旦 mapper 因缺 stdin 而提前退出，reducer 的"补零"会把它伪装成 0，
# 导致出错但不报错。改为显式文件读写，任何环节失败都能被检测到。
LOCAL_JOBS = {
    'format-ratings': (
        'ML_TABLE=ratings python3 {check}/mapper.py',
        'ML_TABLE=ratings python3 {check}/reducer.py',
        [('ratings', None)],
    ),
    'format-movies': (
        'ML_TABLE=movies python3 {check}/mapper.py',
        'ML_TABLE=movies python3 {check}/reducer.py',
        [('movies', None)],
    ),
    'format-users': (
        'ML_TABLE=users python3 {check}/mapper.py',
        'ML_TABLE=users python3 {check}/reducer.py',
        [('users', None)],
    ),
    'cross-users': (
        'ML_XREF=users python3 {check}/cross_mapper.py',
        'ML_XREF=users python3 {check}/cross_reducer.py',
        [('ratings', 'ratings'), ('users', 'ref')],
    ),
    'cross-movies': (
        'ML_XREF=movies python3 {check}/cross_mapper.py',
        'ML_XREF=movies python3 {check}/cross_reducer.py',
        [('ratings', 'ratings'), ('movies', 'ref')],
    ),
    'group-u-pair': (
        'ML_GROUP="ratings|0,1||uniq" python3 {check}/group_mapper.py',
        'ML_METRIC=ratings_pair_dup python3 {check}/group_reducer.py',
        [('ratings', None)],
    ),
    'group-u-movie': (
        'ML_GROUP="movies|0||uniq" python3 {check}/group_mapper.py',
        'ML_METRIC=movies_movie_dup python3 {check}/group_reducer.py',
        [('movies', None)],
    ),
    'group-u-user': (
        'ML_GROUP="users|0||uniq" python3 {check}/group_mapper.py',
        'ML_METRIC=users_user_dup python3 {check}/group_reducer.py',
        [('users', None)],
    ),
    'group-c-movie-multi': (
        'ML_GROUP="movies|0|1,2|multi" python3 {check}/group_mapper.py',
        'ML_METRIC=movies_value_multi python3 {check}/group_reducer.py',
        [('movies', None)],
    ),
    'group-c-user-attr': (
        'ML_GROUP="users|0|1,2,3,4|multi" python3 {check}/group_mapper.py',
        'ML_METRIC=users_attr_multi python3 {check}/group_reducer.py',
        [('users', None)],
    ),
}

TABLE_FILE = {
    'ratings': 'ratings.dat',
    'movies': 'movies.dat',
    'users': 'users.dat',
}


# ---------------------------------------------------------------------------
# 作业执行
# ---------------------------------------------------------------------------

def run_hadoop_job(job, work_dir, verbose=True):
    """通过 run_check.sh 提交一个 Hadoop Streaming 作业，返回其输出文本。"""
    if verbose:
        print('  [hadoop] %s ...' % job, flush=True)
    env = os.environ.copy()
    env['ML_OUT_DIR'] = work_dir
    p = subprocess.run(['bash', RUN_CHECK_SH, job],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       env=env, cwd=REPO_DIR)
    out_file = os.path.join(work_dir, job + '.txt')
    if p.returncode != 0:
        raise SystemExit(
            '[driver] Hadoop 作业失败: %s（退出码 %d）\n'
            '  完整输出:\n%s' % (job, p.returncode, p.stdout.decode('utf-8', 'replace'))
        )
    if not os.path.exists(out_file):
        raise SystemExit(
            '[driver] Hadoop 作业 %s 未产生输出文件: %s' % (job, out_file)
        )
    with open(out_file, 'r', encoding='utf-8') as f:
        return f.read()


def run_local_job(job, data_dir, work_dir, verbose=True):
    """
    在本机用显式文件读写模拟 Hadoop 的 map -> shuffle -> reduce。

    为什么不用 shell 管道：管道写法一旦漏掉输入重定向，mapper 会因缺 stdin
    立即退出而不报错，reducer 的"补零"再把它伪装成合法的 0，
    于是错误被静默吞掉。显式文件读写配合空输出检测可以避免这类问题。

    ⚠️ 本函数只用于开发调试。正式运行请使用 --mode hadoop。
    用于合并 mapper 输出的排序是全局排序（-S 由 sort 自行管理），
    与 Hadoop 的分区内排序不同，但两者对同一份数据产生相同结果。
    """
    if verbose:
        print('  [local ] %s ...' % job, flush=True)

    mapper_tpl, reducer_tpl, tables = LOCAL_JOBS[job]
    jdir = os.path.join(work_dir, 'local', job)
    os.makedirs(jdir, exist_ok=True)

    # --- map 阶段 ---
    # tables 的元素为 (表名, 角色)：角色 'ratings' 表示该输入是评分记录，
    # 'ref' 表示该输入是参照表。跨表作业需要两份输入扮演不同角色，
    # 若都用同一角色跑 mapper，参照表会被误当作评分记录，导致结果完全错误。
    map_out_parts = []
    for tbl, role in tables:
        src = os.path.join(data_dir, TABLE_FILE[tbl])
        if not os.path.exists(src):
            raise SystemExit('[driver] 找不到数据文件: %s' % src)
        cmd = mapper_tpl.format(check=CHECK_DIR, data=data_dir)
        if role:
            cmd = 'ML_INPUT_ROLE=%s %s' % (role, cmd)
        part = os.path.join(jdir, '%s.%s.map' % (tbl, role or 'all'))
        with open(src, 'rb') as fin, open(part, 'wb') as fout:
            p = subprocess.run(['bash', '-c', cmd], stdin=fin, stdout=fout,
                               stderr=subprocess.PIPE)
        if p.returncode != 0:
            raise SystemExit(
                '[driver] 本地 mapper 失败: %s / %s（角色 %s，退出码 %d）\n%s'
                % (job, tbl, role, p.returncode, p.stderr.decode('utf-8', 'replace'))
            )
        map_out_parts.append(part)

    # --- 空输出检测：mapper 一条都没产出，说明输入或逻辑有问题 ---
    total_bytes = sum(os.path.getsize(p) for p in map_out_parts)
    if total_bytes == 0:
        raise SystemExit(
            '[driver] 本地 mapper 无任何输出: %s\n'
            '  这是个错误信号，而不是"没有违规"。请检查输入数据与 mapper 逻辑。' % job
        )

    # --- shuffle 阶段：合并后按 key 排序 ---
    merged = os.path.join(jdir, 'merged')
    with open(merged, 'wb') as fout:
        for p in map_out_parts:
            with open(p, 'rb') as fin:
                while True:
                    chunk = fin.read(1 << 20)
                    if not chunk:
                        break
                    fout.write(chunk)

    sorted_path = os.path.join(jdir, 'sorted')
    with open(merged, 'rb') as fin, open(sorted_path, 'wb') as fout:
        p = subprocess.run(['sort', '-T', jdir], stdin=fin, stdout=fout,
                           stderr=subprocess.PIPE,
                           env=dict(os.environ, LC_ALL='C'))
    if p.returncode != 0:
        raise SystemExit('[driver] 本地 sort 失败: %s\n%s'
                         % (job, p.stderr.decode('utf-8', 'replace')))

    # --- reduce 阶段 ---
    cmd = reducer_tpl.format(check=CHECK_DIR, data=data_dir)
    with open(sorted_path, 'rb') as fin:
        p = subprocess.run(['bash', '-c', cmd], stdin=fin,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        raise SystemExit(
            '[driver] 本地 reducer 失败: %s（退出码 %d）\n%s'
            % (job, p.returncode, p.stderr.decode('utf-8', 'replace'))
        )
    return p.stdout.decode('latin-1')


# ---------------------------------------------------------------------------
# 指标汇总与评分
# ---------------------------------------------------------------------------

def collect_metrics(mode, work_dir, data_dir, verbose=True):
    """运行全部作业并汇总指标。"""
    metrics = {}
    for job in JOBS:
        if mode == 'hadoop':
            text = run_hadoop_job(job, work_dir, verbose)
        else:
            text = run_local_job(job, data_dir, work_dir, verbose)
        got = ml.read_counters(text.splitlines())

        # 关键校验：格式类作业必须报告出记录总数，否则说明 mapper 没读到数据。
        # 这类"看起来成功的空结果"最难排查，所以在源头拦住。
        if job.startswith('format-'):
            tbl = job.split('-', 1)[1]
            key = tbl + '_total'
            if not got.get(key):
                raise SystemExit(
                    '[driver] 作业 %s 未报告有效记录数（%s=%r）。\n'
                    '  这意味着 mapper 没有读到输入数据，结果不可信，'
                    '拒绝输出这样的 JSON。' % (job, key, got.get(key))
                )

        dup = set(got) & set(metrics)
        if dup:
            raise SystemExit(
                '[driver] 指标名冲突（作业 %s 与之前重复）: %r\n'
                '  这说明两个作业输出了同名指标，无法安全汇总。' % (job, sorted(dup))
            )
        metrics.update(got)
    return metrics


def ratio(numerator, denominator):
    """
    返回 (得分, 比率)。分母为 0 时返回 (None, None) 表示该项不适用，
    避免用 0 做除数产生虚假的 100 分。
    """
    if not denominator:
        return None, None
    r = float(numerator) / float(denominator)
    if r < 0:
        r = 0.0
    return round(100.0 * (1.0 - r), 4), r


def score_accurate(m):
    """准确性：字段合法性微平均（每字段一次机会）。"""
    tr, tm, tu = m.get('ratings_total'), m.get('movies_total'), m.get('users_total')
    items = [
        (m.get('ratings_r_uid_bad', 0),    tr),
        (m.get('ratings_r_mid_bad', 0),    tr),
        (m.get('ratings_r_rating_bad', 0), tr),
        (m.get('ratings_r_ts_bad', 0),     tr),
        (m.get('movies_m_mid_bad', 0),      tm),
        (m.get('movies_m_title_empty', 0),  tm),
        (m.get('movies_m_year_missing', 0) + m.get('movies_m_year_bad', 0), tm),
        (m.get('users_u_uid_bad', 0),    tu),
        (m.get('users_u_gender_bad', 0), tu),
        (m.get('users_u_age_bad', 0),    tu),
        (m.get('users_u_occ_bad', 0),    tu),
        (m.get('users_u_zip_bad', 0),    tu),
    ]
    ratios = []
    detail = []
    for bad, den in items:
        if den:
            ratios.append(float(bad) / float(den))
            detail.append('%d/%d' % (bad, den))
    if not ratios:
        return None, {}
    score = round(100.0 * (1.0 - sum(ratios) / len(ratios)), 4)
    return score, {'checks': len(ratios), 'per_check_rates': detail}


def score_complete(m):
    """完整性：必需字段缺失记录数 / 三表总记录数。"""
    bad = (m.get('ratings_missing', 0) + m.get('movies_missing', 0) + m.get('users_missing', 0))
    den = (m.get('ratings_total', 0) + m.get('movies_total', 0) + m.get('users_total', 0))
    score, r = ratio(bad, den)
    return score, {'missing_records': bad, 'total_records': den, 'rate': r}


def score_unique(m):
    """唯一性：主键违规数 / 三表总记录数。"""
    bad = (m.get('ratings_pair_dup_violations', 0)
           + m.get('movies_movie_dup_violations', 0)
           + m.get('users_user_dup_violations', 0))
    den = (m.get('ratings_total', 0) + m.get('movies_total', 0) + m.get('users_total', 0))
    score, r = ratio(bad, den)
    return score, {'dup_violations': bad, 'total_records': den, 'rate': r}


def score_consistent(m):
    """
    一致性：0.5 x 跨表引用完整性 + 0.5 x 格式一致性。
    跨表部分按"每张参照表一次机会"取平均，避免记录数差异导致权重失衡。
    """
    tr = m.get('ratings_total')
    tm = m.get('movies_total')
    tu = m.get('users_total')

    ref_items = [
        (m.get('users_orphan_records', 0), tr),
        (m.get('movies_orphan_records', 0), tr),
    ]
    ref_rates = [float(b) / float(d) for b, d in ref_items if d]
    ref_ratio = (sum(ref_rates) / len(ref_rates)) if ref_rates else None

    fmt_items = [
        (m.get('movies_value_multi_violations', 0), tm),
        (m.get('users_attr_multi_violations', 0),   tu),
        (m.get('movies_m_genres_dup', 0) + m.get('movies_m_genres_emptyitem', 0)
         + m.get('movies_m_genres_unknown', 0) + m.get('movies_m_genres_empty', 0), tm),
        (m.get('movies_m_title_space', 0), tm),
        (m.get('users_u_zip_bad', 0),      tu),
    ]
    fmt_rates = [float(b) / float(d) for b, d in fmt_items if d]
    fmt_ratio = (sum(fmt_rates) / len(fmt_rates)) if fmt_rates else None

    parts = [x for x in (ref_ratio, fmt_ratio) if x is not None]
    if not parts:
        return None, {}
    combined = sum(parts) / len(parts)
    score = round(100.0 * (1.0 - combined), 4)
    return score, {
        'ref_integrity_ratio': (round(ref_ratio, 10) if ref_ratio is not None else None),
        'format_consistency_ratio': (round(fmt_ratio, 10) if fmt_ratio is not None else None),
        'orphan_records': {
            'users': m.get('users_orphan_records', 0),
            'movies': m.get('movies_orphan_records', 0),
        },
    }


def score_up_to_date(m):
    """
    时效性：时间可解释性 x 时间新鲜度（以 T1/T2 为参照，而非"今天"）。

    依据 docs/evaluation-method.md 第 4.4 节：
      - 不得把"评分发生在 2000-2003 年"视为质量问题。
      - 第一层（reliability）：时间戳能否被合理解释。
      - 第二层（freshness）：距 T2 的相对新近程度。
    本实现只用第一层，因为它是可完全自动验证的客观判据；
    第二层需要逐条时间戳求均值，将在评分阶段（score 模块）实现。
    """
    tr = m.get('ratings_total')
    ok = m.get('ratings_d2_ok', 0)
    score, r = ratio((tr - ok) if tr else 0, tr)
    return score, {
        'explainable_records': ok,
        'total_records': tr,
        'note': '仅计入第一层（时间可解释性）；第二层新鲜度在 score 模块中按 T1/T2 计算',
    }


DIMENSION_FUNCS = {
    'accurate': score_accurate,
    'complete': score_complete,
    'unique': score_unique,
    'up_to_date': score_up_to_date,
    'consistent': score_consistent,
}


def build_scores(metrics):
    """计算五维得分与综合分。"""
    scores = {}
    details = {}
    for dim, fn in DIMENSION_FUNCS.items():
        s, d = fn(metrics)
        scores[dim] = s
        details[dim] = d

    # 综合分：仅当五维全部可计算时才给出，避免用缺失值凑数
    if all(scores.get(k) is not None for k in ml.WEIGHTS):
        overall = sum(scores[k] * ml.WEIGHTS[k] for k in ml.WEIGHTS)
        scores['overall'] = round(overall, 4)
    else:
        missing = [k for k in ml.WEIGHTS if scores.get(k) is None]
        scores['overall'] = None
        details['_overall_note'] = '以下维度无法计算，故不给出综合分: %r' % missing

    return scores, details


# ---------------------------------------------------------------------------
# 输出组装
# ---------------------------------------------------------------------------

def fmt_epoch(ts):
    return datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc).strftime('%Y-%m-%d')


def build_result(task_id, metrics, scores, details, after_metrics=None,
                 after_scores=None, stats=None):
    """
    组装最终评估结果 JSON。

    契约依据：docs/接口规范文档.md 第 13 节（GET /api/tasks/{task_id}/result）
    本次新增字段：score_change、problems、unresolved_problems、report
    以及版本命名 input_version / output_version（第 16 节）。

    参数：
      metrics         清洗前（Before）的指标
      scores          Before 的五维得分
      after_metrics   After 的指标，未执行清洗时为 None
      after_scores    After 的五维得分，未执行清洗时为 None
      stats           清洗统计（four counts），未执行清洗时为 None
    """
    cfg = ml.load_rules()

    before_count = (metrics.get('ratings_total', 0)
                    + metrics.get('movies_total', 0)
                    + metrics.get('users_total', 0))

    # --- Before 得分 ---
    before_score = {d: scores.get(d) for d in DIM_ORDER}
    before_score['overall'] = scores.get('overall')

    # --- After 得分（未执行清洗时全部为 None，不填占位值）---
    if after_scores:
        after_score = {d: after_scores.get(d) for d in DIM_ORDER}
        after_score['overall'] = after_scores.get('overall')
    else:
        after_score = {d: None for d in DIM_ORDER}
        after_score['overall'] = None

    # --- score_change：五维变化量 ---
    # 只在 After 存在时给出；否则为 None，避免填写 0 被误读为"没有变化"
    if after_scores:
        score_change = {}
        for d in DIM_ORDER:
            b, a = before_score.get(d), after_score.get(d)
            score_change[d] = (round(a - b, 4) if (b is not None and a is not None) else None)
    else:
        score_change = {d: None for d in DIM_ORDER}

    # --- problems / unresolved_problems ---
    problems, unresolved = problems_mod.build_problems(metrics, scores)

    # --- report ---
    rep = report_mod.build_report(before_score, after_score, ml.WEIGHTS, cfg, unresolved)

    # --- statistics ---
    if stats:
        statistics = {
            'before_count': stats.get('before_count', before_count),
            'after_count': stats.get('after_count'),
            'fixed_count': stats.get('fixed_count'),
            'deduplicated_count': stats.get('deduplicated_count'),
            'isolated_count': stats.get('isolated_count'),
        }
    else:
        # 清洗尚未执行：除 before_count 外一律为 None。
        # 依据接口规范第 2.2 节，不得用 0 冒充真实结果。
        statistics = {
            'before_count': before_count,
            'after_count': None,
            'fixed_count': None,
            'deduplicated_count': None,
            'isolated_count': None,
            '_note': '清洗尚未执行，After 相关统计为 null。执行 clean 阶段后填充。',
        }

    return {
        'task_id': task_id,
        'status': 'SUCCESS',
        'stage': 'ALL' if after_scores else 'BEFORE_SCORE',

        # 版本（接口规范第 16 节）
        'data_version': cfg['output_version'] if after_scores else cfg['input_version'],
        'input_version': cfg['input_version'],
        'output_version': cfg['output_version'] if after_scores else None,
        'rule_version': cfg['rule_version'],

        # T1/T2 同时输出"日期"和"精确 epoch 秒"。
        # 只给日期是不够的：按日期午夜切分与按分位数精确切分会产生不同结果
        # （实测差约 0.5 个百分点），后续迭代必须使用 epoch 才能复现同一划分。
        'T1': fmt_epoch(ml.T1),
        'T2': fmt_epoch(ml.T2),
        'T1_epoch': ml.T1,
        'T2_epoch': ml.T2,
        'split_rule': cfg['time'].get('split_rule'),

        'before_score': before_score,
        'after_score': after_score,
        'score_change': score_change,

        'statistics': statistics,
        'problems': problems,
        'unresolved_problems': unresolved,
        'report': rep,

        'dataset': {
            'ratings': metrics.get('ratings_total'),
            'movies':  metrics.get('movies_total'),
            'users':   metrics.get('users_total'),
            'time_range': [
                cfg['time']['dataset_min_date'],
                cfg['time']['dataset_max_date'],
            ],
        },

        'weights': ml.WEIGHTS,
        'score_details': details,
        # metrics 为本项目附加的调试与追溯字段，不属于接口契约必需项，
        # 但保留它便于核查每个得分背后的原始计数。
        'metrics': metrics,
    }


# ---------------------------------------------------------------------------
# 阶段化入口（对应接口规范第 9、10、11 节的三个接口）
# ---------------------------------------------------------------------------

def state_path(task_id):
    """任务状态文件路径。三个阶段通过它传递中间结果。"""
    return os.path.join(REPORT_DIR, task_id + '.json')


def load_state(task_id):
    """读取已有任务状态；不存在时返回 None。"""
    p = state_path(task_id)
    if not os.path.exists(p):
        return None
    with open(p, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_state(task_id, data):
    os.makedirs(REPORT_DIR, exist_ok=True)
    with open(state_path(task_id), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return state_path(task_id)


def stage_before(args, task_id):
    """
    阶段一：清洗前质量评分

    对应接口：POST /hadoop/quality-score/before
    响应契约（接口规范第 9 节）：
        {"task_id", "status", "data_version", "scores": {五维}}
    """
    if not args.quiet:
        print('[driver] 阶段: BEFORE_SCORE（清洗前质量评分）')

    metrics = collect_metrics(args.mode, args.work_dir, args.data_dir,
                              verbose=not args.quiet)
    scores, details = build_scores(metrics)
    cfg = ml.load_rules()

    # 状态文件：保存完整指标，供 clean / after 阶段复用
    state = load_state(task_id) or {}
    state.update({
        '_state': 'BEFORE_DONE',
        'task_id': task_id,
        'data_version': cfg['input_version'],
        'rule_version': cfg['rule_version'],
        'before_metrics': metrics,
        'before_scores': scores,
        'before_details': details,
    })
    save_state(task_id, state)

    # 接口响应（严格按第 9 节契约）
    response = {
        'task_id': task_id,
        'status': 'SUCCESS',
        'data_version': cfg['input_version'],
        'scores': {d: scores.get(d) for d in DIM_ORDER},
    }
    return response


def stage_clean(args, task_id):
    """
    阶段二：数据清洗

    对应接口：POST /hadoop/clean
    响应契约（接口规范第 10 节）：
        {"task_id", "status", "input_version", "output_version",
         "rule_version", "statistics": {五个字段}}
    """
    raise SystemExit(
        '[driver] 阶段 CLEAN（数据清洗）尚未实现。\n'
        '\n'
        '  接口契约已按 docs/接口规范文档.md 第 10 节预留，\n'
        '  但清洗作业本身仍在开发中（对应 Issue #3）。\n'
        '\n'
        '  为遵守接口规范第 2.2 节与第 15 节，本阶段在未实现时\n'
        '  【明确失败】而不返回占位结果。\n'
        '\n'
        '  当前可用的阶段：before（清洗前评分）\n'
        '  待 clean 完成后，after 阶段即可使用。\n'
    )


def stage_after(args, task_id):
    """
    阶段三：清洗后质量评分

    对应接口：POST /hadoop/quality-score/after
    响应契约（接口规范第 11 节）：
        {"task_id", "status", "data_version", "scores": {五维}}

    依赖：clean 阶段产出的清洗后数据集。
    """
    state = load_state(task_id)
    if not state or 'before_metrics' not in state:
        raise SystemExit(
            '[driver] 找不到任务 %s 的 before 阶段结果。\n'
            '  请先执行: --stage before --task-id %s' % (task_id, task_id)
        )

    clean_dir = CLEAN_DATA_DIR
    if not os.path.isdir(clean_dir) or not os.listdir(clean_dir):
        raise SystemExit(
            '[driver] 未找到清洗后数据集: %s\n'
            '  请先执行: --stage clean --task-id %s\n'
            '  （clean 阶段目前尚未实现，见 --stage clean 的说明）' % (clean_dir, task_id)
        )

    cfg = ml.load_rules()
    if not args.quiet:
        print('[driver] 阶段: AFTER_SCORE（清洗后质量评分）')
        print('        数据目录: %s' % clean_dir)

    metrics = collect_metrics(args.mode, args.work_dir, clean_dir,
                              verbose=not args.quiet)
    scores, details = build_scores(metrics)

    state.update({
        '_state': 'AFTER_DONE',
        'data_version': cfg['output_version'],
        'after_metrics': metrics,
        'after_scores': scores,
        'after_details': details,
    })
    save_state(task_id, state)

    response = {
        'task_id': task_id,
        'status': 'SUCCESS',
        'data_version': cfg['output_version'],
        'scores': {d: scores.get(d) for d in DIM_ORDER},
    }
    return response


def stage_all(args, task_id):
    """一次跑完 before + after（clean 未实现时 after 为空），输出最终结果契约。"""
    if not args.quiet:
        print('[driver] 阶段: ALL（清洗前评分 + 最终结果组装）')
        print('        注意：clean 阶段尚未实现，after_score 将为 null')

    metrics = collect_metrics(args.mode, args.work_dir, args.data_dir,
                              verbose=not args.quiet)
    scores, details = build_scores(metrics)

    state = load_state(task_id) or {}
    state.update({
        '_state': 'BEFORE_DONE',
        'task_id': task_id,
        'before_metrics': metrics,
        'before_scores': scores,
        'before_details': details,
    })

    after_metrics = state.get('after_metrics')
    after_scores = state.get('after_scores')
    stats = state.get('clean_statistics')

    result = build_result(task_id, metrics, scores, details,
                          after_metrics=after_metrics,
                          after_scores=after_scores,
                          stats=stats)
    state['result'] = result
    save_state(task_id, state)
    return result


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description='MovieLens 数据治理 driver（对应 docs/接口规范文档.md 第 9-11 节）')
    ap.add_argument('--stage', choices=['all', 'before', 'clean', 'after'], default='all',
                    help='执行阶段：before=清洗前评分；clean=数据清洗；'
                         'after=清洗后评分；all=一次跑完（默认，向后兼容）')
    ap.add_argument('--mode', choices=['local', 'hadoop'], default='local',
                    help='local=本机文件模拟（调试）；hadoop=提交 Hadoop Streaming 作业')
    ap.add_argument('--task-id', default=None, help='任务标识，默认按时间生成')
    ap.add_argument('--data-dir', default=os.path.expanduser('~/data/ml-1m'))
    ap.add_argument('--work-dir', default='/tmp/mlqc-driver')
    ap.add_argument('--out', default=None, help='输出 JSON 路径（默认写入 reports/quality-report/）')
    ap.add_argument('--quiet', action='store_true')
    args = ap.parse_args()

    task_id = args.task_id or ('task_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
    os.makedirs(args.work_dir, exist_ok=True)

    if not args.quiet:
        print('=' * 62)
        print(' MovieLens 数据治理')
        print('   stage     : %s' % args.stage)
        print('   mode      : %s' % args.mode)
        print('   task_id   : %s' % task_id)
        print('   data_dir  : %s' % args.data_dir)
        print('=' * 62)

    ml.init_rules()
    cfg = ml.load_rules()
    if not args.quiet:
        print('规则版本: %s   数据版本: %s -> %s' % (
            cfg['rule_version'], cfg['input_version'], cfg['output_version']))
        print('T1=%s  T2=%s' % (fmt_epoch(ml.T1), fmt_epoch(ml.T2)))
        print('')

    # --- 阶段派发 ---
    if args.stage == 'before':
        result = stage_before(args, task_id)
    elif args.stage == 'clean':
        result = stage_clean(args, task_id)
    elif args.stage == 'after':
        result = stage_after(args, task_id)
    else:
        result = stage_all(args, task_id)

    # --- 输出 ---
    if args.out:
        out_path = args.out
    elif args.stage == 'all':
        out_path = os.path.join(REPORT_DIR, task_id + '.json')
    else:
        out_path = os.path.join(args.work_dir, '%s_%s.json' % (task_id, args.stage))
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    if not args.quiet:
        print('')
        print('=' * 62)
        if args.stage in ('before', 'after'):
            print(' 五维质量评分（%s）' % ('Before' if args.stage == 'before' else 'After'))
            print('=' * 62)
            for k in DIM_ORDER:
                v = result['scores'].get(k)
                print('   %-12s %s' % (k, ('%.4f' % v) if v is not None else 'N/A'))
        else:
            print(' 五维质量评分（Before）')
            print('=' * 62)
            for k in DIM_ORDER:
                v = result['before_score'].get(k)
                print('   %-12s %s' % (k, ('%.4f' % v) if v is not None else 'N/A'))
            ov = result['before_score'].get('overall')
            print('   %-12s %s' % ('overall', ('%.4f' % ov) if ov is not None else 'N/A'))
            print('')
            print(' 问题清单      : %d 条' % len(result.get('problems', [])))
            print(' 未解决问题    : %d 条' % len(result.get('unresolved_problems', [])))
            print(' 报告 improvements: %d 条'
                  % len(result.get('report', {}).get('improvements', [])))
            print(' 数据规模: ratings=%s movies=%s users=%s' % (
                result['dataset']['ratings'], result['dataset']['movies'],
                result['dataset']['users']))
        print('')
        print(' 结果已写入: %s' % out_path)

    return 0


if __name__ == '__main__':
    sys.exit(main())
