#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
最终结果组装（接口规范第 13 节 / 第 14 节）

背景：成员A的 HTTP 端点按契约只返回最小字段（第 9-11 节），
完整的第 13 节结果（score_change / statistics / problems /
unresolved_problems / report）原本只在 driver --stage all 路径里组装。
Agent 走的是三个 HTTP 接口 + 状态交接文件，因此由本模块负责组装 ——
这是分工文档中成员B"结果解析与聚合"交付物的核心。

与成员A driver.build_result 的关系：
  · 字段集合、取值语义完全一致（对照 reports/quality-report/task_001.json）；
  · 复用同一套构建函数（pipeline_bridge -> problems.py / report.py），
    不重写任何映射与文案，保证两条路径产出口径一致；
  · 唯一的刻意差别：unresolved_problems 在清洗完成后改用【after 指标】
    计算（"清洗后依然存在"），而不是 before 指标的"计划处置"口径。
    理由见 pipeline_bridge.build_problems 注释；此差异会在 PR 描述中
    向成员A/C 说明。

真实结果红线（接口规范第 2.2 节）：
  数值全部来自成员A写入状态文件的真实执行产物；本模块只做四则运算
  （差值、求和）与结构组装。未执行的环节一律为 null 并附 _note 说明，
  绝不填 0 冒充。
"""

import os
import sys

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

import pipeline_bridge as bridge          # noqa: E402
from models import DIM_ORDER              # noqa: E402
from errors import AgentError, QUALITY_SCORE_ERROR  # noqa: E402


def _fmt_epoch(ts):
    import datetime
    return datetime.datetime.fromtimestamp(
        int(ts), datetime.timezone.utc).strftime('%Y-%m-%d')


def before_count_of(metrics):
    """三表记录总数（与成员A driver.build_result 同一算法）。"""
    return int((metrics.get('ratings_total') or 0)
               + (metrics.get('movies_total') or 0)
               + (metrics.get('users_total') or 0))


def _score_block(scores):
    if not scores:
        block = {d: None for d in DIM_ORDER}
        block['overall'] = None
        return block
    block = {d: scores.get(d) for d in DIM_ORDER}
    block['overall'] = scores.get('overall')
    return block


def _score_change(before, after):
    if not after:
        return {d: None for d in DIM_ORDER}
    change = {}
    for d in DIM_ORDER:
        b, a = before.get(d), after.get(d)
        change[d] = round(a - b, 4) if (b is not None and a is not None) else None
    return change


def build(task_id, state, cfg, do_clean):
    """
    组装第 13 节结果（不含 status 字段 —— 由调度层按任务结局填写，
    成功填 SUCCESS，失败时同一结构作为"部分结果"如实返回）。

    参数：
      task_id  任务标识
      state    成员A状态文件的完整 dict
      cfg      rules.json 内容（版本 / 时间 / 权重的唯一来源）
      do_clean 本任务计划是否执行清洗（失败的部分结果也需要它来写说明）
    """
    before_metrics = state.get('before_metrics')
    before_scores = state.get('before_scores')
    if not before_metrics or not before_scores:
        raise AgentError(
            'BEFORE_SCORE', QUALITY_SCORE_ERROR,
            '状态文件中没有清洗前评分明细，无法组装结果',
            '期望键 before_metrics / before_scores，实际键: %s'
            % sorted(state.keys()))

    after_metrics = state.get('after_metrics')
    after_scores = state.get('after_scores')
    clean_stats = state.get('clean_statistics')

    before = _score_block(before_scores)
    # 与成员A driver.build_result 相同：After 未执行时输出"全 null 的字典"
    # 而不是 null 字段，前端可稳定读取 after_score.accurate。
    after = _score_block(after_scores)
    change = _score_change(before, after)

    # ---- problems：清洗前识别出的全部问题（before 指标）----
    problems, _ = bridge.build_problems(before_metrics)

    # ---- unresolved：清洗后依然存在（after 指标）；未清洗则同 problems 口径 ----
    if after_metrics:
        _, unresolved = bridge.build_problems(after_metrics)
    else:
        _, unresolved = bridge.build_problems(before_metrics)

    # ---- statistics ----
    bc = before_count_of(before_metrics)
    if clean_stats:
        statistics = {
            'before_count': clean_stats.get('before_count', bc),
            'after_count': clean_stats.get('after_count'),
            'fixed_count': clean_stats.get('fixed_count'),
            'deduplicated_count': clean_stats.get('deduplicated_count'),
            'isolated_count': clean_stats.get('isolated_count'),
        }
    else:
        # 未清洗 / 清洗失败：After 相关一律 null（接口规范第 2.2 节）
        statistics = {
            'before_count': bc,
            'after_count': None,
            'fixed_count': None,
            'deduplicated_count': None,
            'isolated_count': None,
            '_note': '清洗尚未执行（或执行失败），After 相关统计为 null。',
        }

    # ---- report（复用成员A的构建函数；未清洗时 improvements 为空）----
    weights = {k: v for k, v in cfg['weights'].items() if not k.startswith('_')}
    t = cfg['time']
    rep = bridge.build_report(before, after, weights, cfg, unresolved)

    result = {
        'task_id': task_id,
        'stage': 'ALL' if after_scores else 'BEFORE_SCORE',

        # 版本（第 16 节）：清洗链路完成才输出 clean 版本
        'data_version': (cfg['output_version'] if after_scores
                         else cfg['input_version']),
        'input_version': cfg['input_version'],
        'output_version': cfg['output_version'] if after_scores else None,
        'rule_version': cfg['rule_version'],

        # T1/T2（第 17 节）：日期 + 精确 epoch 同时给出
        'T1': _fmt_epoch(t['T1_epoch']),
        'T2': _fmt_epoch(t['T2_epoch']),
        'T1_epoch': int(t['T1_epoch']),
        'T2_epoch': int(t['T2_epoch']),
        'split_rule': t.get('split_rule'),

        'before_score': before,
        'after_score': after,
        'score_change': change,

        'statistics': statistics,
        'problems': problems,
        'unresolved_problems': unresolved,
        'report': rep,

        'dataset': {
            'ratings': before_metrics.get('ratings_total'),
            'movies': before_metrics.get('movies_total'),
            'users': before_metrics.get('users_total'),
            'time_range': [t.get('dataset_min_date'), t.get('dataset_max_date')],
        },
        'weights': weights,
        'score_details': state.get('before_details') or {},
        'metrics': before_metrics,

        # 溯源标注：与成员A --stage all 路径的产物区分开（本项目附加字段）
        '_assembled_by': 'agent/http-pipeline(成员B)',
    }
    if after_scores:
        result['after_metrics'] = after_metrics
        result['after_score_details'] = state.get('after_details') or {}
    return result
