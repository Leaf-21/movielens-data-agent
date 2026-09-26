#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
结果解释（Agent"解释"职责，接口规范第 2.1 / 14 节）

职责：把第 13 节的结构化结果翻译成用户能读懂的中文说明，
并支持任务完成后的追问（POST /api/tasks/{task_id}/ask）。

三条硬规则：
  1. 解释中出现的一切数字只能取自结果 JSON（真实执行产物）；
     取不到就说"未执行/无数据"，不编造。
  2. 措辞纪律（迭代一需求第 91 行）：
     隔离(isolated) ≠ 修复(fixed)；删除 ≠ 修复。模板文案里逐条体现。
  3. 模板路径是主路径，任何环境（含无 API Key 的评测机）都必须能回答；
     大模型仅在模板未覆盖问题且 LLM 可用时兜底，且只允许引用给定证据。
"""

import os
import sys

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

import llm                                   # noqa: E402
from models import (DIM_ORDER, DIM_CN, SUCCESS, FAILED,
                    PENDING, RUNNING)        # noqa: E402
import parser as parser_mod                  # noqa: E402

SEVERITY_CN = {'high': '高', 'medium': '中', 'low': '低', 'info': '提示'}
ACTION_CN = {'fix': '修复', 'dedupe': '去重', 'isolate': '隔离',
             'keep': '保留（已确认非错误）', 'observe': '仅观察'}

# 各错误码的下一步指引（接口规范第 6 节：失败要说明环节和原因，并给出建议）
FAILURE_GUIDANCE = {
    'INVALID_REQUEST': '请检查请求字段后重新提交。',
    'DATA_NOT_FOUND': '数据文件缺失。请确认已解压 ml-1m.zip 且 Hadoop 服务的 '
                      '--data-dir 指向包含 ratings.dat / movies.dat / users.dat 的目录。',
    'INVALID_DATA_VERSION': '请使用已登记的数据版本（movielens-1m-v1 或 clean 产物版本）。',
    'INVALID_RULE_VERSION': '请使用已登记的规则版本（当前为 rule-v1），或传 "default"。',
    'HADOOP_EXECUTION_ERROR': 'Hadoop 环节执行失败。请检查 Hadoop 服务是否存活'
                              '（GET /health）以及作业日志，确认后可重新提交任务。',
    'QUALITY_SCORE_ERROR': '质量评分环节失败，评分结果不可信，系统未输出任何占位分数。'
                           '请检查成员A的评分作业输出后重新提交。',
    'AGENT_EXECUTION_ERROR': 'Agent 调度环节失败。任务记录与已完成的中间结果仍可查看，'
                             '修正后可用同一 data_version 重新提交。',
    'INTERNAL_ERROR': '系统内部错误。请查看 error.detail 字段并联系开发成员。',
}


# ---------------------------------------------------------------------------
# 摘要（模板主路径）
# ---------------------------------------------------------------------------

def _fmt(v):
    return 'null' if v is None else ('%.4f' % v)


def _delta_text(dc):
    if dc is None:
        return '无数据'
    if abs(dc) < 1e-9:
        return '持平（0）'
    return '提升 %.4f' % dc if dc > 0 else '下降 %.4f' % abs(dc)


def summarize(result):
    """完整任务摘要，多条目组合，全部数字取自 result。"""
    lines = []
    b, a = result.get('before_score') or {}, result.get('after_score')
    if b.get('overall') is not None:
        if a and a.get('overall') is not None:
            lines.append('综合质量分：清洗前 %s → 清洗后 %s（%s）。'
                         % (_fmt(b['overall']), _fmt(a['overall']),
                            _delta_text(round(a['overall'] - b['overall'], 4))))
        else:
            lines.append('综合质量分：清洗前 %s。本任务未执行清洗，无清洗后得分。'
                         % _fmt(b['overall']))

    st = result.get('statistics') or {}
    if st.get('fixed_count') is not None:
        lines.append(
            '数据量：清洗前 %s 条 → 清洗后 %s 条；修复 %s 条、去重 %s 条、隔离 %s 条。'
            '注意：隔离是把无法确证正确值的记录移出主数据集单独保存，'
            '问题本身并未被修正，不计入"已修复"。'
            % (st.get('before_count'), st.get('after_count'),
               st.get('fixed_count'), st.get('deduplicated_count'),
               st.get('isolated_count')))
    elif st.get('before_count') is not None:
        lines.append('原始数据总量 %s 条；清洗未执行，无处置统计。' % st['before_count'])

    probs = result.get('problems') or []
    if probs:
        parts = ['%s（%s，%d 条）' % (p['subject'],
                                     SEVERITY_CN.get(p['severity'], p['severity']),
                                     p['count']) for p in probs]
        lines.append('识别出的问题：' + '；'.join(parts) + '。')
    else:
        lines.append('本次评分未识别出任何违规项。')

    unres = result.get('unresolved_problems') or []
    if unres:
        lines.append('清洗后依然存在的问题：%s。'
                     % '；'.join('%s（%d 条）' % (p['subject'], p['count'])
                                 for p in unres))
    elif a:
        lines.append('清洗后不存在未解决的违规项。')
    return lines


def dim_answer(result, dim):
    """单维度追问的回答模板。"""
    b = (result.get('before_score') or {}).get(dim)
    a = (result.get('after_score') or {}).get(dim)
    dc = (result.get('score_change') or {}).get(dim)
    lines = ['%s维度：清洗前 %s%s。' % (
        DIM_CN[dim], _fmt(b),
        '' if a is None else '，清洗后 %s，%s' % (_fmt(a), _delta_text(dc)))]
    method = ((result.get('report') or {}).get('method') or {})
    if method.get('dimensions', {}).get(dim):
        lines.append('该维度口径：' + method['dimensions'][dim])
    related_p = [p for p in (result.get('problems') or []) if p['dimension'] == dim]
    if related_p:
        lines.append('该维度识别出的问题：%s。' % '；'.join(
            '%s（%s，处置=%s，%d 条）' % (p['subject'],
                                          SEVERITY_CN.get(p['severity'], p['severity']),
                                          ACTION_CN.get(p['action'], p['action']),
                                          p['count']) for p in related_p))
    rel_u = [p for p in (result.get('unresolved_problems') or []) if p['dimension'] == dim]
    if rel_u:
        lines.append('该维度尚未解决：%s。' % '；'.join(
            '%s（%d 条）' % (p['subject'], p['count']) for p in rel_u))
    if dim == 'up_to_date':
        note = ((result.get('score_details') or {}).get('up_to_date') or {}).get('note')
        if note:
            lines.append('特别说明：' + note)
    return lines


def failure_answer(record):
    """失败任务的状态回答：环节 + 原因 + 指引 + 已有部分结果。"""
    err = record.get('error') or {}
    lines = ['任务状态：FAILED，环节：%s。原因：%s'
             % (err.get('stage') or record.get('stage') or '未知',
                err.get('message') or record.get('message') or '无详细说明')]
    if err.get('code'):
        lines.append('错误码：%s。%s'
                     % (err['code'], FAILURE_GUIDANCE.get(err['code'], '')))
    partial = record.get('result')
    if partial and (partial.get('before_score') or {}).get('overall') is not None:
        lines.append('失败前已完成环节的真实结果仍然有效：'
                     + ' '.join(summarize(partial)[:1])
                     + '（清洗后数据缺失处为 null，不代表 0。）')
    return lines


def version_answer(result):
    st = result.get('statistics') or {}
    lines = [
        '数据版本：输入 %s；输出 %s。' % (result.get('input_version'),
                                        result.get('output_version') or '（本任务未产出清洗数据）'),
        '规则版本：%s（清洗与评分共用，定义于 hadoop/config/rules.json）。'
        % result.get('rule_version'),
        'T1=%s（epoch %s，训练期截止）；T2=%s（epoch %s，验证期截止）；'
        '测试数据位于 T2 之后。划分规则：%s。'
        % (result.get('T1'), result.get('T1_epoch'),
           result.get('T2'), result.get('T2_epoch'), result.get('split_rule')),
    ]
    if st.get('isolated_count'):
        lines.append('版本一致性提醒：被隔离记录未进入输出版本，保存在 '
                     'hadoop/output/isolated/，不参与后续训练切分。')
    return lines


# ---------------------------------------------------------------------------
# 追问入口（模板优先，LLM 兜底）
# ---------------------------------------------------------------------------

def build_evidence(record):
    """给 LLM 的只读证据摘录：只放已执行产生的数字与文案，控制体积。"""
    r = record.get('result') or {}
    report = r.get('report') or {}
    return {
        'task_id': record.get('task_id'),
        'status': record.get('status'),
        'before_score': r.get('before_score'),
        'after_score': r.get('after_score'),
        'score_change': r.get('score_change'),
        'statistics': r.get('statistics'),
        'problems': r.get('problems'),
        'unresolved_problems': r.get('unresolved_problems'),
        'versions': {'input': r.get('input_version'), 'output': r.get('output_version'),
                     'rule': r.get('rule_version')},
        'T1': r.get('T1'), 'T2': r.get('T2'), 'split_rule': r.get('split_rule'),
        'method': report.get('method'),
        'limitations': [x.get('topic') for x in report.get('limitations') or []],
    }


def answer(record, question):
    """
    返回 (answer_text, source)。source ∈ template / llm / template+llm。
    永远不抛异常：LLM 失败时静默回退模板。
    """
    q = (question or '').strip()
    status = record.get('status')

    if status == FAILED:
        return '\n'.join(failure_answer(record)), 'template'
    if status in (PENDING, RUNNING):
        from models import STAGE_MESSAGES
        stage = record.get('stage')
        text = ('任务尚未完成（当前状态 %s，环节：%s）。'
                '完成后即可追问评分与清洗结果。' % (status, stage or '排队中'))
        if record.get('plan', {}).get('notes'):
            text += '\nAgent 对本需求的理解：' + ' '.join(record['plan']['notes'])
        return text, 'template'

    result = record.get('result') or {}
    lines = []

    # ---- 关键词路由（可多个命中，全部作答）----
    matched = False
    dims = parser_mod.detect_dimensions(q)
    if dims:
        matched = True
        for d in dims:
            lines.extend(dim_answer(result, d))
    low = q.lower()
    if '隔离' in q or ('移除' in q and not matched):
        matched = True
        st = result.get('statistics') or {}
        lines.append('隔离：%s 条记录因无法确定正确值被移出主数据集，单独保存在 '
                     'hadoop/output/isolated/；它们未被修正，因此不能表述为"已修复"。'
                     '修复（fixed）%s 条才是真正改回正确值的记录。'
                     % (st.get('isolated_count'), st.get('fixed_count')))
    if ('版本' in q or 'T1' in q or 'T2' in q or 't1' in low or 't2' in low
            or '划分' in q or '切分' in q):
        matched = True
        lines.extend(version_answer(result))
    if '权重' in q:
        matched = True
        w = (result.get('report', {}).get('method', {}).get('weights')
             or result.get('weights') or {})
        lines.append('综合分权重：%s。%s'
                     % ('、'.join('%s %s' % (DIM_CN.get(k, k), v)
                                  for k, v in sorted(w.items())),
                        '权重是设计选择而非测量结果（见 evaluation-method 第 5.1 节）。'))
    if ('不足' in q or '局限' in q or '无法验证' in q or '不能确定' in q):
        matched = True
        lims = (result.get('report') or {}).get('limitations') or []
        lines.append('评价局限（无法验证的方面）：'
                     + '；'.join(x.get('topic', '') for x in lims) + '。')
    if not matched:
        # 无明确路由：先给通用摘要，再让 LLM 在证据约束下补充回答
        lines.extend(summarize(result))
        lines.append('（当前问题未命中已登记的解释模板，以上为任务摘要。）')
        source = 'template'
        if llm.enabled():
            extra = llm.answer_question(q, build_evidence(record))
            if extra:
                lines.append('以下补充回答由大模型基于上述真实结果证据生成：\n' + extra)
                source = 'template+llm'
        return '\n'.join(lines), source

    return '\n'.join(lines), 'template'
