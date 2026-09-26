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
SCORE_DIR = os.path.join(DRIVER_DIR, 'score')

sys.path.insert(0, COMMON_DIR)
sys.path.insert(0, PIPELINE_DIR)
import ml_common as ml
import problems as problems_mod
import report as report_mod
import errors as errors_mod
from errors import StageError

RUN_CHECK_SH = os.path.join(HADOOP_DIR, 'scripts', 'run_check.sh')
RUN_CLEAN_SH = os.path.join(HADOOP_DIR, 'scripts', 'run_clean.sh')

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
    'freshness-ratings',
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
    'freshness-ratings': (
        'python3 {score}/freshness_mapper.py',
        'cat',
        [('ratings', None)],
    ),
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

def run_hadoop_job(job, work_dir, verbose=True, data_dir=None, stage='BEFORE_SCORE'):
    """
    通过 run_check.sh 提交一个 Hadoop Streaming 作业，返回其输出文本。

    data_dir  覆盖检查作业的输入目录（after 阶段用于对清洗后数据评分）
    stage     出错时写入错误响应的阶段名（BEFORE_SCORE / AFTER_SCORE）
    """
    if verbose:
        print('  [hadoop] %s ...' % job, flush=True)
    env = os.environ.copy()
    env['ML_OUT_DIR'] = work_dir
    if data_dir:
        env['ML_INPUT_DIR'] = data_dir
    p = subprocess.run(['bash', RUN_CHECK_SH, job],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       env=env, cwd=REPO_DIR)
    out_file = os.path.join(work_dir, job + '.txt')
    if p.returncode != 0:
        raise StageError(
            stage=stage, code=errors_mod.HADOOP_EXECUTION_ERROR,
            message='Hadoop 作业执行失败：%s' % job,
            detail=p.stdout.decode('utf-8', 'replace')[-4000:],
        )
    if not os.path.exists(out_file):
        raise StageError(
            stage=stage, code=errors_mod.HADOOP_EXECUTION_ERROR,
            message='Hadoop 作业 %s 未产生输出文件' % job,
            detail='期望路径: %s' % out_file,
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
            raise StageError(
                stage='BEFORE_SCORE', code=errors_mod.DATA_NOT_FOUND,
                message='找不到数据文件，无法执行检查',
                detail='期望路径: %s' % src,
            )
        cmd = mapper_tpl.format(check=CHECK_DIR, data=data_dir, score=SCORE_DIR)
        if role:
            cmd = 'ML_INPUT_ROLE=%s %s' % (role, cmd)
        part = os.path.join(jdir, '%s.%s.map' % (tbl, role or 'all'))
        with open(src, 'rb') as fin, open(part, 'wb') as fout:
            p = subprocess.run(['bash', '-c', cmd], stdin=fin, stdout=fout,
                               stderr=subprocess.PIPE)
        if p.returncode != 0:
            raise StageError(
                stage='BEFORE_SCORE', code=errors_mod.HADOOP_EXECUTION_ERROR,
                message='本地 mapper 执行失败：作业 %s，表 %s' % (job, tbl),
                detail=p.stderr.decode('utf-8', 'replace')[-2000:],
            )
        map_out_parts.append(part)

    # --- 空输出检测：mapper 一条都没产出，说明输入或逻辑有问题 ---
    total_bytes = sum(os.path.getsize(p) for p in map_out_parts)
    if total_bytes == 0:
        raise StageError(
            stage='BEFORE_SCORE', code=errors_mod.HADOOP_EXECUTION_ERROR,
            message='mapper 未产生任何输出：%s' % job,
            detail='空输出是错误信号而非"没有违规"，已判定为失败以避免不可信结果。',
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
        raise StageError(
            stage='BEFORE_SCORE', code=errors_mod.HADOOP_EXECUTION_ERROR,
            message='本地排序阶段失败：作业 %s' % job,
            detail=p.stderr.decode('utf-8', 'replace')[-2000:],
        )

    # --- reduce 阶段 ---
    cmd = reducer_tpl.format(check=CHECK_DIR, data=data_dir, score=SCORE_DIR)
    with open(sorted_path, 'rb') as fin:
        p = subprocess.run(['bash', '-c', cmd], stdin=fin,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        raise StageError(
            stage='BEFORE_SCORE', code=errors_mod.HADOOP_EXECUTION_ERROR,
            message='本地 reducer 执行失败：作业 %s' % job,
            detail=p.stderr.decode('utf-8', 'replace')[-2000:],
        )
    return p.stdout.decode('latin-1')


# ---------------------------------------------------------------------------
# 指标汇总与评分
# ---------------------------------------------------------------------------

def collect_metrics(mode, work_dir, data_dir, verbose=True, stage='BEFORE_SCORE'):
    """
    运行全部作业并汇总指标。

    data_dir 可指向原始数据或清洗后数据；stage 用于错误响应的阶段名，
    使 after 阶段的失败能被正确归类为 AFTER_SCORE 而非 BEFORE_SCORE。
    """
    metrics = {}
    for job in JOBS:
        if mode == 'hadoop':
            text = run_hadoop_job(job, work_dir, verbose,
                                  data_dir=data_dir, stage=stage)
        else:
            text = run_local_job(job, data_dir, work_dir, verbose)
        got = ml.read_counters(text.splitlines())

        # 关键校验：格式类作业必须报告出记录总数，否则说明 mapper 没读到数据。
        # 这类"看起来成功的空结果"最难排查，所以在源头拦住。
        if job.startswith('format-'):
            tbl = job.split('-', 1)[1]
            key = tbl + '_total'
            if not got.get(key):
                raise StageError(
                    stage=stage, code=errors_mod.QUALITY_SCORE_ERROR,
                    message='作业 %s 未报告有效记录数，结果不可信' % job,
                    detail='指标 %s 的值为 %r，说明 mapper 没有读到输入数据，'
                           '拒绝输出这样的结果。' % (key, got.get(key)),
                )

        dup = set(got) & set(metrics)
        if dup:
            raise StageError(
                stage=stage, code=errors_mod.QUALITY_SCORE_ERROR,
                message='指标名冲突，无法安全汇总',
                detail='作业 %s 与之前重复的指标: %r' % (job, sorted(dup)),
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
    时效性 = 第一层（时间可解释性）× 第二层（时间新鲜度）

    依据 docs/evaluation-method.md 第 4.4 节：

      第一层 reliability：时间戳能否被合理解释
          = 合规记录数 / 总记录数

      第二层 freshness：按 T1/T2 逐条计算新近程度后求均值
          freshness(t) = clamp((t − T1) / (T2 − T1), 0, 1)
          均值越小说明数据越集中在早期

      Up-to-date = 100 × reliability × mean(freshness)

    ⚠️ 关于本数据集该维度得分偏低的说明
    ----------------------------------------------------------------
    T1/T2 按分位数切分，因此按定义 70% 的记录落在 T1 之前、其 freshness
    被 clamp 为 0。实测分布：

        clamp 到 0  (t <= T1) :  700,144  (70.00%)
        线性区间    (T1~T2)   :  150,035  (15.00%)
        clamp 到 1  (t > T2)  :  150,030  (15.00%)

        freshness 均值 = 0.215385814245

    因此本维度得分约为 21.54，明显低于其他四维。

    **这不是 bug，与数据质量也无关**：T1/T2 一旦按分位数确定，该均值
    就基本被锁定（线性区间约贡献 0.075，T2 之后的 15% 贡献 0.15）。
    它衡量的是"数据在时间窗口内的新近程度"，而本数据集 90.4% 的评分
    集中在 2000 年，新近程度本来就低。

    依据 docs/迭代一_Hadoop数据清洗与Agent基础.md 第 51 行：
    "数据年代较早并不必然属于错误"。

    因此本维度在报告中必须配合说明使用，不可单独作为"数据质量差"的依据。
    这也正是该维度权重被设为 0.10（最低档）的原因 —— 见 evaluation-method 第 5.1 节。
    """
    tr = m.get('ratings_total')

    # --- 第一层：时间可解释性 ---
    ok = m.get('ratings_d2_ok', 0)
    # 注意 ratio() 返回的第二个值是【违规率】：
    #   rel_violation_rate = 不可解释记录数 / 总数
    # 本项目实测该值为 0（1000209 条全部可解释），故第一层得分为 100.0。
    rel_score, rel_violation_rate = ratio((tr - ok) if tr else 0, tr)

    # --- 第二层：新鲜度均值 ---
    fsum = m.get('ratings_freshness_sum')
    fn = m.get('ratings_freshness_n')

    details = {
        'explainable_records': ok,
        'total_records': tr,
        # 命名对齐 ratio() 的语义，避免被误读为"合规率"
        'reliability_violation_rate': (round(rel_violation_rate, 10)
                                       if rel_violation_rate is not None else None),
        'reliability_score': rel_score,
    }

    if fsum is None or not fn:
        # 新鲜度指标缺失：不能静默当作 0 或 1，明确标注并用第一层的结果
        details['note'] = ('未取得新鲜度指标（ratings_freshness_sum / _n），'
                           '本维度仅按第一层计算。请检查 freshness-ratings 作业是否执行。')
        return rel_score, details

    freshness_mean = float(fsum) / float(fn)
    details['freshness_sum'] = round(float(fsum), 12)
    details['freshness_n'] = fn
    details['freshness_mean'] = round(freshness_mean, 12)
    details['formula'] = ('100 × (1 − reliability_violation_rate) × freshness_mean'
                          ' = 100 × reliability_score/100 × freshness_mean')

    if rel_score is None:
        return None, details

    score = round(rel_score * freshness_mean, 4)
    details['note'] = (
        'T1/T2 按分位数切分，按定义 70%% 的记录落在 T1 之前，其 freshness '
        '被 clamp 为 0，故本维度得分（%.4f）明显低于其他四维。'
        '这是数据时间分布的客观反映，与数据质量无关；'
        '依据迭代一需求第 51 行，数据年代较早并不必然属于错误。' % score
    )
    return score, details


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

    执行流程：
      1. 对三张表分别提交 Hadoop Streaming 清洗作业（run_clean.sh）
      2. 读取带处置标签的输出，按标签分流：
           clean + fixed -> 清洗后数据集（hadoop/output/clean/）
           isolated      -> 隔离数据集  （hadoop/output/isolated/）
      3. 汇总统计并写入任务状态，供 after 阶段使用

    ⚠️ "修复"与"隔离"的区分贯穿始终：
       修复的记录进入主数据集并计入 fixed_count；
       隔离的记录移出主数据集、单独保存并计入 isolated_count。
       二者不合并、不互相表述（依据迭代一需求第 91 行）。
    """
    state = load_state(task_id) or {}
    cfg = ml.load_rules()

    if not args.quiet:
        print('[driver] 阶段: CLEANING（数据清洗）')

    # --- 准备输出目录 ---
    for d in (CLEAN_DATA_DIR, ISOLATED_DATA_DIR):
        os.makedirs(d, exist_ok=True)

    work_dir = os.path.join(args.work_dir, 'clean')
    os.makedirs(work_dir, exist_ok=True)

    counts = {'clean_count': 0, 'fixed_count': 0, 'isolated_count': 0,
              'deduplicated_count': 0, 'unknown_count': 0}
    after_total = 0
    before_total = 0

    for table in ('ratings', 'movies', 'users'):
        tagged, c = _run_clean_job(table, work_dir, args, verbose=not args.quiet)

        # 分流：clean 与 fixed 进入主数据集，isolated 单独保存
        clean_path = os.path.join(CLEAN_DATA_DIR, TABLE_FILE[table])
        iso_path = os.path.join(ISOLATED_DATA_DIR, TABLE_FILE[table])

        n_clean, n_fixed, n_iso = _split_tagged(tagged, clean_path, iso_path)

        for k in ('clean_count', 'fixed_count', 'isolated_count', 'unknown_count'):
            counts[k] += c.get(k, 0)
        after_total += n_clean + n_fixed
        before_total += (n_clean + n_fixed + n_iso)

        if not args.quiet:
            print('         %-8s clean=%-8d fixed=%-5d isolated=%-5d'
                  % (table, n_clean, n_fixed, n_iso))

    # --- 一致性校验：分流后总数必须等于清洗作业报告的总数 ---
    reported_total = (counts['clean_count'] + counts['fixed_count']
                      + counts['isolated_count'] + counts['unknown_count'])
    if before_total != reported_total:
        raise StageError(
            stage='CLEANING', code=errors_mod.HADOOP_EXECUTION_ERROR,
            message='清洗结果行数与作业统计不一致，结果不可信',
            detail='分流后 %d 行，作业报告 %d 行' % (before_total, reported_total),
        )
    if counts['unknown_count']:
        raise StageError(
            stage='CLEANING', code=errors_mod.HADOOP_EXECUTION_ERROR,
            message='清洗输出中存在无法识别的标签',
            detail='unknown_count=%d，说明 mapper/reducer 契约被破坏'
                   % counts['unknown_count'],
        )
    if after_total <= 0:
        raise StageError(
            stage='CLEANING', code=errors_mod.HADOOP_EXECUTION_ERROR,
            message='清洗后数据集为空，结果不可信',
        )

    # --- 去重：业务主键重复在清洗 mapper 中未被单独处置 ---
    # 实测 ratings 的 (UserID, MovieID) 无重复（见 Issue #2），此处如实记录为 0。
    # 若后续数据出现重复，需在清洗规则中显式增加去重处置后再更新此值。
    counts['deduplicated_count'] = 0

    stats = {
        'before_count': before_total,
        'after_count': after_total,
        'fixed_count': counts['fixed_count'],
        'deduplicated_count': counts['deduplicated_count'],
        'isolated_count': counts['isolated_count'],
    }

    # --- 写入任务状态，供 after 阶段读取 ---
    state.update({
        '_state': 'CLEAN_DONE',
        'data_version': cfg['output_version'],
        'rule_version': cfg['rule_version'],
        'clean_statistics': stats,
        'clean_data_dir': CLEAN_DATA_DIR,
        'isolated_data_dir': ISOLATED_DATA_DIR,
    })
    save_state(task_id, state)

    if not args.quiet:
        print('')
        print('         before_count=%d  after_count=%d  fixed=%d  dedup=%d  isolated=%d'
              % (stats['before_count'], stats['after_count'], stats['fixed_count'],
                 stats['deduplicated_count'], stats['isolated_count']))
        print('         清洗后数据: %s' % CLEAN_DATA_DIR)
        print('         隔离数据  : %s' % ISOLATED_DATA_DIR)

    # 接口响应（严格按第 10 节契约）
    return {
        'task_id': task_id,
        'status': 'SUCCESS',
        'input_version': cfg['input_version'],
        'output_version': cfg['output_version'],
        'rule_version': cfg['rule_version'],
        'statistics': {
            'before_count': stats['before_count'],
            'after_count': stats['after_count'],
            'fixed_count': stats['fixed_count'],
            'deduplicated_count': stats['deduplicated_count'],
            'isolated_count': stats['isolated_count'],
        },
    }


def _run_clean_job(table, work_dir, args, verbose=True):
    """
    提交单表清洗作业，返回 (带标签输出文件路径, 统计字典)。

    作业通过 run_clean.sh 执行；脚本会把带标签的输出落到
    <work_dir>/<table>.tagged，统计落到 <work_dir>/<table>.counts。
    """
    if verbose:
        print('         [hadoop] clean-%s ...' % table, flush=True)

    env = os.environ.copy()
    env['ML_OUT_DIR'] = work_dir
    env['ML_WORK_DIR'] = os.path.join(work_dir, 'hdfs', table)
    env['ML_DATA_DIR'] = args.data_dir
    env.pop('ML_INPUT_DIR', None)   # 清洗始终以原始数据为输入

    p = subprocess.run(['bash', RUN_CLEAN_SH, table],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       env=env, cwd=REPO_DIR)
    if p.returncode != 0:
        raise StageError(
            stage='CLEANING', code=errors_mod.HADOOP_EXECUTION_ERROR,
            message='清洗作业执行失败：%s' % table,
            detail=p.stdout.decode('utf-8', 'replace')[-4000:],
        )

    tagged = os.path.join(work_dir, table + '.tagged')
    counts_file = os.path.join(work_dir, table + '.counts')

    if not os.path.exists(tagged):
        raise StageError(
            stage='CLEANING', code=errors_mod.HADOOP_EXECUTION_ERROR,
            message='清洗作业未产生数据输出：%s' % table,
            detail='期望路径: %s' % tagged,
        )
    if not os.path.exists(counts_file):
        raise StageError(
            stage='CLEANING', code=errors_mod.HADOOP_EXECUTION_ERROR,
            message='清洗作业未产生统计输出：%s' % table,
            detail='期望路径: %s' % counts_file,
        )

    counts = {}
    with open(counts_file, 'r', encoding='utf-8') as f:
        for line in f:
            parts = line.rstrip('\n').split('\t')
            if len(parts) == 2:
                try:
                    counts[parts[0]] = int(parts[1])
                except ValueError:
                    continue

    if not counts:
        raise StageError(
            stage='CLEANING', code=errors_mod.HADOOP_EXECUTION_ERROR,
            message='清洗统计文件为空或格式错误：%s' % table,
        )
    return tagged, counts


def _split_tagged(tagged_path, clean_path, iso_path):
    """
    按标签把带标签输出分流为两个文件。

    输入行格式：<标签>\t<记录原文>
      clean / fixed  -> clean_path（清洗后数据）
      isolated       -> iso_path（隔离数据）

    ⚠️ 必须以二进制方式读写：记录为 ISO-8859-1 字节，用文本模式会破坏编码。

    返回 (clean+fixed 行数, fixed 行数, isolated 行数)
    """
    n_clean = n_fixed = n_iso = 0

    with open(tagged_path, 'rb') as fin, \
         open(clean_path, 'wb') as fclean, \
         open(iso_path, 'wb') as fiso:
        for line in fin:
            raw = line.rstrip(b'\n').rstrip(b'\r')
            if raw == b'':
                continue
            parts = raw.split(b'\t', 1)
            if len(parts) < 2:
                continue
            tag, payload = parts[0], parts[1]

            if tag == b'clean':
                fclean.write(payload + b'\n')
                n_clean += 1
            elif tag == b'fixed':
                fclean.write(payload + b'\n')
                n_fixed += 1
            elif tag == b'isolated':
                fiso.write(payload + b'\n')
                n_iso += 1
            # 其他标签已在调用方按 unknown_count 拦截

    return n_clean, n_fixed, n_iso


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
        raise StageError(
            stage='AFTER_SCORE', code=errors_mod.INVALID_REQUEST,
            message='缺少 before 阶段结果，无法执行清洗后评分',
            detail='请先执行: --stage before --task-id %s' % task_id,
        )

    clean_dir = state.get('clean_data_dir') or CLEAN_DATA_DIR
    missing = [t for t in ('ratings', 'movies', 'users')
               if not os.path.exists(os.path.join(clean_dir, TABLE_FILE[t]))]
    if missing:
        raise StageError(
            stage='AFTER_SCORE', code=errors_mod.DATA_NOT_FOUND,
            message='未找到清洗后数据集，无法执行清洗后评分',
            detail='目录 %s 中缺少: %s。请先执行 --stage clean --task-id %s'
                   % (clean_dir, ', '.join(missing), task_id),
        )

    cfg = ml.load_rules()
    if not args.quiet:
        print('[driver] 阶段: AFTER_SCORE（清洗后质量评分）')
        print('        数据目录: %s' % clean_dir)

    metrics = collect_metrics(args.mode, args.work_dir, clean_dir,
                              verbose=not args.quiet, stage='AFTER_SCORE')
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
    """
    完整流程：before → clean → after，输出最终结果契约（接口规范第 13 节）。

    三个阶段依次调用，每一步的产出写入任务状态，最后组装为完整结果。
    Agent 也可以分别调用三个接口（接口规范第 9-11 节），二者等价。
    """
    if not args.quiet:
        print('=' * 62)
        print(' 完整流程：清洗前评分 -> 数据清洗 -> 清洗后评分')
        print('=' * 62)

    # --- 阶段一：清洗前评分 ---
    after_resp = stage_before(args, task_id)

    # --- 阶段二：数据清洗 ---
    clean_resp = stage_clean(args, task_id)

    # --- 阶段三：清洗后评分 ---
    after_resp = stage_after(args, task_id)

    # --- 组装最终结果 ---
    state = load_state(task_id) or {}
    metrics = state['before_metrics']
    scores = state['before_scores']
    details = state['before_details']

    result = build_result(task_id, metrics, scores, details,
                          after_metrics=state.get('after_metrics'),
                          after_scores=state.get('after_scores'),
                          stats=state.get('clean_statistics'))
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
    # 失败时按接口规范第 15 节返回结构化错误响应，而不是裸的报错文本，
    # 以便 Agent 按 error.code 分类处理。
    stage_label = {
        'before': 'BEFORE_SCORE', 'clean': 'CLEANING',
        'after': 'AFTER_SCORE', 'all': 'BEFORE_SCORE',
    }[args.stage]

    try:
        if args.stage == 'before':
            result = stage_before(args, task_id)
        elif args.stage == 'clean':
            result = stage_clean(args, task_id)
        elif args.stage == 'after':
            result = stage_after(args, task_id)
        else:
            result = stage_all(args, task_id)
    except SystemExit as e:
        # 规则文件缺失、参数非法等由其他模块抛出的 SystemExit，
        # 同样转为结构化错误响应，避免 Agent 收到无法解析的裸文本。
        msg = str(e.code) if e.code else '未知错误'
        code = errors_mod.INVALID_RULE_VERSION if 'rule' in msg.lower() \
            else errors_mod.INTERNAL_ERROR
        errors_mod.emit_error(task_id, stage_label, code, msg)
        return 1
    except StageError as e:
        # 结构化错误响应：写入 stdout 与状态文件，退出码 1
        resp = errors_mod.build_error_response(
            task_id, e.stage, e.code, e.message, e.detail)
        errors_mod.emit_error(task_id, e.stage, e.code, e.message, e.detail)
        # 同时落盘，便于排查与后续阶段读取
        try:
            st = load_state(task_id) or {}
            st['_state'] = 'FAILED'
            st['last_error'] = resp.get('error')
            save_state(task_id, st)
        except Exception:
            pass  # 状态文件写入失败不应掩盖原始错误
        if not args.quiet:
            print('', file=sys.stderr)
            print('[driver] 阶段失败: %s / %s' % (e.stage, e.code), file=sys.stderr)
        return 1

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
