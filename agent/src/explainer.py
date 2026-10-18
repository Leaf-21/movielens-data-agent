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
import re
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
    'INVALID_DATA_VERSION': '请使用已登记的数据版本（movielens-1m-v2 或 clean 产物版本）。',
    'INVALID_RULE_VERSION': '请使用已登记的规则版本（当前为 rule-v2），或传 "default"。',
    'HADOOP_EXECUTION_ERROR': 'Hadoop 环节执行失败。请检查 Hadoop 服务是否存活'
                              '（GET /health）以及作业日志，确认后可重新提交任务。',
    'QUALITY_SCORE_ERROR': '质量评分环节失败，评分结果不可信，系统未输出任何占位分数。'
                           '请检查成员A的评分作业输出后重新提交。',
    'AGENT_EXECUTION_ERROR': 'Agent 调度环节失败。任务记录与已完成的中间结果仍可查看，'
                             '修正后可用同一 data_version 重新提交。',
    'INTERNAL_ERROR': '系统内部错误。请查看 error.detail 字段并联系开发成员。',
    # 迭代二接口扩展规范 §2.1/§六 新增码的指引
    'DATA_UNAVAILABLE': '清洗快照不可用。请确认 hadoop/output/clean/ 存在且为 '
                        'movielens-1m-v2-clean-v1（可先重跑迭代一清洗任务）。',
    'VERSION_MISMATCH': '数据/画像版本与分析口径不匹配。分析任务固定使用 '
                        'analysis.json 登记的版本，请修正请求字段后重新提交。',
    'UNKNOWN_USER': '目标用户不存在于 users.dat。请核对用户 ID 范围（1-6040）'
                    '与清洗快照后重新提交。',
    'UNKNOWN_MOVIE': '目标电影不存在于 movies.dat，请核对电影 ID。',
    'INSUFFICIENT_HISTORY': '用户训练期评分数低于最小历史要求，画像不可用；'
                            '系统未强行给出群体结论，可换用户或调低阈值（须重新登记口径）。',
    'MODEL_NOT_FOUND': '该算法尚未在 agent/config/analysis.json 登记实现。'
                       '聚类类别当前提供 kmeans/dbscan；分类与降维等成员A/C工具合入后自动生效。',
    'INVALID_PARAMETER': '算法参数不在 analysis.json allowed_parameters 白名单或超出取值范围。'
                         '请按 error.detail 中的允许清单修正。',
    'ALGORITHM_ERROR': '算法子进程执行失败（含超时/崩溃且重试无效）。'
                       'error.detail 记录退出码与 stderr 尾部，可据此排查后重新提交。',
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


_ANALYSIS_TYPES = ('clustering', 'classification', 'dimensionality_reduction')
_UID_RX = re.compile(r'(?:用户|user[_\s]*(?:id)?)[=：:\s]*(\d+)', re.I)
_CLUSTER_RX = re.compile(r'(?:群体|簇|cluster)[\s=]*([0-9]+)', re.I)


def _fmt_pct(v):
    return 'null' if v is None else ('%.3f' % v)


def analysis_summary_lines(result):
    """分析任务通用摘要：每个算法一栏，数字全部取自结果信封。"""
    lines = []
    for e in result.get('results') or []:
        mt = e.get('metrics') or {}
        head = ('【%s】模型 %s / 结果 %s：拟合用户 %s 人'
                % (e.get('algorithm_tool'), e.get('model_version'),
                   e.get('result_version'), mt.get('n_fit_users')))
        if e.get('algorithm') == 'kmeans':
            head += '，选定 k=%s' % mt.get('k_selected')
            if mt.get('silhouette_full') is not None:
                head += ('，全量轮廓系数 %.4f，DBI %.3f，SSE %.0f'
                         % (mt['silhouette_full'], mt['davies_bouldin_full'] or 0,
                            mt['sse_full'] or 0))
        elif e.get('algorithm') == 'dbscan':
            head += ('，eps=%s（%s）/ min_samples=%s，簇数 %s，噪声 %s（占比 %s）'
                     % (mt.get('eps_used'), mt.get('eps_method'),
                        mt.get('min_samples'), mt.get('n_clusters'),
                        mt.get('noise_count'),
                        ('%.1f%%' % (100 * mt['noise_ratio']))
                        if mt.get('noise_ratio') is not None else 'null'))
        lines.append(head + '。')
        for s in e.get('cluster_summaries') or []:
            genres = '、'.join('%s %s' % (g['genre'], _fmt_pct(g['v']))
                               for g in (s.get('top_genre_shares') or [])[:3])
            reps = '、'.join('%s（%d 人高分）' % (m['title'], m['high_raters_in_cluster'])
                             for m in (s.get('representative_movies') or [])[:3])
            lines.append('  群体 %s：%s 人，均分 %s，高分占比 %s；类型Top: %s；'
                         '代表作品: %s。'
                         % (s.get('cluster_id'), s.get('size'),
                            _fmt_pct(s.get('avg_rating_mean')),
                            _fmt_pct(s.get('high_share_mean')), genres, reps))
    if result.get('requested_user_ids'):
        lines.append('本次请求用户：%s。' % result['requested_user_ids'])
    return lines


def analysis_answer(record, question):
    """迭代二分析任务追问：模板主路径，数字只取自结果信封。"""
    q = (question or '').strip()
    low = q.lower()
    result = record.get('result') or {}
    envs = result.get('results') or []
    lines = []
    matched = False

    # ---- 版本/时间边界 ----
    if ('版本' in q or 'version' in low or 't1' in low or 't2' in low
            or '划分' in q or '时间' in q):
        matched = True
        lines.append('数据版本 %s；画像版本 %s；分析口径 %s；代码 commit %s。'
                     % (result.get('data_version'), result.get('profile_version'),
                        result.get('analysis_version'), result.get('code_version')))
        lines.append('训练期截止 T1=%s（epoch %s），验证期截止 T2=%s（epoch %s）；'
                     '画像特征只用 Timestamp<=T1 记录。'
                     % (result.get('T1'), result.get('T1_epoch'),
                        result.get('T2'), result.get('T2_epoch')))
        rv = result.get('result_versions') or {}
        if rv:
            lines.append('结果版本：%s。'
                         % '、'.join('%s=%s' % kv for kv in sorted(rv.items())))

    # ---- 指定用户归属 ----
    for uid in {int(m.group(1)) for m in _UID_RX.finditer(q)}:
        hit = False
        for e in envs:
            a = next((x for x in e.get('assignments') or []
                      if x.get('user_id') == uid), None)
            if not a:
                continue
            hit = True
            cid = a.get('cluster_id')
            seg = ('【%s】用户 %s：' % (e.get('algorithm_tool'), uid))
            if cid is None:
                seg += '无归属（状态 %s）' % a.get('status')
            else:
                seg += '属于群体 %s（状态 %s%s）' % (
                    cid, a.get('status'),
                    '，可靠性低' if a.get('reliability_low') else '')
                dist = a.get('distance_to_centroid')
                if dist is not None:
                    seg += '，到质心距离 %.3f' % dist
            if a.get('note'):
                seg += '。说明：' + a['note']
            lines.append(seg + '。')
            if cid is not None:
                s = next((x for x in e.get('cluster_summaries') or []
                          if x.get('cluster_id') == cid), None)
                if s:
                    lines.append('  该群体真实统计：%s 人，均分 %s，高分占比 %s。'
                                 % (s.get('size'), _fmt_pct(s.get('avg_rating_mean')),
                                    _fmt_pct(s.get('high_share_mean'))))
        if not hit:
            lines.append('结果中没有用户 %d 的归属记录（追问只基于已执行结果，'
                         '不为未计算的用户编造结论）。' % uid)
        matched = True

    # ---- 指定群体 ----
    for ck in {int(m.group(1)) for m in _CLUSTER_RX.finditer(q)}:
        hit = False
        for e in envs:
            s = next((x for x in e.get('cluster_summaries') or []
                      if x.get('cluster_id') == ck), None)
            if not s:
                continue
            hit = True
            genres = '、'.join('%s %s' % (g['genre'], _fmt_pct(g['v']))
                               for g in (s.get('top_genre_shares') or []))
            reps = '、'.join('%s（%d 人高分）'
                            % (m['title'], m['high_raters_in_cluster'])
                            for m in (s.get('representative_movies') or []))
            lines.append('【%s】群体 %s：%s 人，平均评分 %s，'
                         '高分占比 %s，活跃跨度均值 %s 天；类型占比：%s；代表作品：%s。'
                         % (e.get('algorithm_tool'), ck, s.get('size'),
                            _fmt_pct(s.get('avg_rating_mean')),
                            _fmt_pct(s.get('high_share_mean')),
                            _fmt_pct(s.get('active_span_days_mean')),
                            genres or '—', reps or '—'))
            lines.append('  依据：%s' % s.get('summary_basis'))
        if not hit:
            lines.append('群体 %d 不存在于当前结果（不同算法的簇号互不相通，'
                         '请指明算法或以用户归属为准）。' % ck)
        matched = True

    # ---- 指标/噪声/参数选择 ----
    if (any(k in low for k in ('指标', '轮廓', 'silhouette', 'dbi', 'davies', 'sse',
                               '噪声', 'noise', 'eps', 'k选', '选k', '参数怎么选',
                               'how many clusters')) or '指标' in q or '噪声' in q):
        matched = True
        for e in envs:
            mt = e.get('metrics') or {}
            parts = []
            if e.get('algorithm') == 'kmeans':
                parts = ['选定 k=%s' % mt.get('k_selected'),
                         '全量轮廓系数 %s' % _fmt_pct(mt.get('silhouette_full')),
                         'DBI %s' % _fmt_pct(mt.get('davies_bouldin_full')),
                         'SSE %s' % (mt.get('sse_full') and round(mt['sse_full'], 1))]
                tbl = mt.get('k_selection_table') or []
                if tbl and ('k' in low or '选' in q or '轮廓' in q):
                    parts.append('候选表：' + '；'.join(
                        'k=%d sil≈%s' % (t['k'],
                                          _fmt_pct(t['silhouette_sampled']))
                        for t in tbl))
            elif e.get('algorithm') == 'dbscan':
                parts = ['eps=%s（%s）' % (mt.get('eps_used'), mt.get('eps_method')),
                         'min_samples=%s' % mt.get('min_samples'),
                         '簇数 %s' % mt.get('n_clusters'),
                         '噪声 %s（%s）' % (mt.get('noise_count'),
                                          _fmt_pct(mt.get('noise_ratio'))),
                         '轮廓系数 %s' % _fmt_pct(mt.get('silhouette_full'))]
            lines.append('【%s】%s。' % (e.get('algorithm_tool'), '，'.join(parts)))
            defn = (mt.get('definition') or {}).get('silhouette')
            if defn and '轮廓' in q:
                lines.append('  口径：' + defn)

    # ---- 参数 ----
    if '参数' in q or 'parameter' in low:
        matched = True
        for e in envs:
            lines.append('【%s】生效参数：%s。' % (e.get('algorithm_tool'),
                                               e.get('parameters')))

    # ---- 局限 ----
    if any(k in q for k in ('局限', '不足', '风险', '为什么不能')):
        matched = True
        for e in envs:
            lines.append('【%s】局限：' % e.get('algorithm_tool'))
            lines.extend('  - ' + x for x in e.get('limitations') or [])

    if not matched:
        lines.extend(analysis_summary_lines(result))
        source = 'template'
        if llm.enabled():
            ev = {'task_id': record.get('task_id'), 'status': record.get('status'),
                  'algorithms': [{k: e.get(k) for k in
                                  ('algorithm_tool', 'model_version',
                                   'result_version', 'parameters', 'metrics',
                                   'cluster_summaries', 'limitations')}
                                 for e in envs]}
            extra = llm.answer_question(q, ev)
            if extra:
                lines.append('以下补充回答由大模型基于上述真实结果证据生成：\n' + extra)
                source = 'template+llm'
        return '\n'.join(lines), source
    return '\n'.join(lines), 'template'


def answer(record, question):
    """
    返回 (answer_text, source)。source ∈ template / llm / template+llm。
    永远不抛异常：LLM 失败时静默回退模板。
    """
    q = (question or '').strip()
    status = record.get('status')

    # ---- 迭代二：分析任务按 task_type 分发到专用模板 ----
    task_type = record.get('task_type') or record.get('plan', {}).get('task_type')
    if task_type in _ANALYSIS_TYPES:
        if status == FAILED:
            return '\n'.join(failure_answer(record)), 'template'
        if status in (PENDING, RUNNING):
            stage = record.get('stage')
            notes = record.get('plan', {}).get('notes') or ''
            text = ('分析任务尚未完成（状态 %s，环节：%s）。聚类拟合可能需要数分钟。'
                    % (status, stage or '排队中'))
            if notes:
                text += '\nAgent 对本需求的理解：' + (
                    ' '.join(notes) if isinstance(notes, list) else notes)
            return text, 'template'
        return analysis_answer(record, q)

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
