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


UNAVAILABLE_TEXT = (
    '当前未配置可用的语言模型，无法回答追问。\n'
    '请在仓库根 .env 中配置大模型（模板见 .env.example，配置项见 README'
    '「大模型增强层」），重启 Agent 后即可追问。\n'
    '任务结果本身不受影响，可直接查看 GET /api/tasks/{id}/result 的原始字段'
    '（metrics / cluster_summaries / limitations 等）。'
)

LLM_FAILED_TEXT = (
    '调用语言模型失败，无法回答追问。\n'
    '具体原因见 Agent 日志中 [agent.llm] 开头的记录（鉴权 / 网络 / 限流 / 模型名）。\n'
    '任务结果本身不受影响，可直接查看 GET /api/tasks/{id}/result 的原始字段。'
)


#: metrics 里的说明性长文本：对回答没有帮助，却会显著拉长 prompt
_METRIC_PROSE_KEYS = ('definition', 'k_selection_rule', '_note')

#: 每个群体保留几部代表作品（原数据是 5 部，回答里通常只引用前几部）
_MAX_REP_MOVIES = 3


def _slim_metrics(metrics):
    """去掉 metrics 里的说明性长文本，只留数字与结构（显著减小 prompt）。"""
    if not isinstance(metrics, dict):
        return metrics
    return {k: v for k, v in metrics.items() if k not in _METRIC_PROSE_KEYS}


def _slim_summaries(summaries):
    """压缩群体摘要：代表作品只留前 N 部，其余字段原样保留。"""
    out = []
    for c in summaries or []:
        if not isinstance(c, dict):
            continue
        item = dict(c)
        reps = item.get('representative_movies')
        if isinstance(reps, list) and len(reps) > _MAX_REP_MOVIES:
            item['representative_movies'] = reps[:_MAX_REP_MOVIES]
            item['representative_movies_total'] = len(reps)
        out.append(item)
    return out


def _analysis_evidence(record):
    """
    迭代二分析任务的只读证据摘录。

    体积控制（重要）：assignments 只保留**本次请求涉及的**用户，
    coordinates 只给总数与前 5 条样例 —— 否则 4783 个拟合用户的归属
    会把上下文撑到几 MB，既慢又容易被截断。
    """
    result = record.get('result') or {}
    wanted = set(result.get('requested_user_ids') or [])
    algos = []
    for e in result.get('results') or []:
        item = {k: e.get(k) for k in (
            'algorithm', 'algorithm_tool', 'algorithm_name', 'model_version',
            'result_version', 'parameters', 'information_retention',
            'resource_usage', 'clustering_comparison', 'limitations',
            'original_dimensions', 'reduced_dimensions', 'axis_meaning')}
        item['metrics'] = _slim_metrics(e.get('metrics'))
        item['cluster_summaries'] = _slim_summaries(e.get('cluster_summaries'))
        assigns = e.get('assignments') or []
        if wanted:
            item['assignments'] = [a for a in assigns
                                   if a.get('user_id') in wanted]
        else:
            item['assignments'] = assigns[:50]
            item['assignments_truncated'] = max(0, len(assigns) - 50)
        coords = e.get('coordinates') or []
        if coords:
            item['coordinates_count'] = len(coords)
            item['coordinates_sample'] = coords[:5]
            item.pop('coordinates', None)
        algos.append(item)
    return {
        'task_id': record.get('task_id'),
        'task_type': result.get('task_type'),
        'status': record.get('status'),
        'data_version': result.get('data_version'),
        'profile_version': result.get('profile_version'),
        'analysis_version': result.get('analysis_version'),
        'T1': result.get('T1'), 'T2': result.get('T2'),
        'requested_user_ids': result.get('requested_user_ids'),
        'result_versions': result.get('result_versions'),
        'algorithms': algos,
    }


def answer(record, question):
    """
    返回 (answer_text, source)。

    source ∈ state / llm / unavailable：
      · state        任务未完成或已失败 —— 如实报告状态与失败环节（事实陈述）
      · llm          大模型基于结果证据生成的回答
      · unavailable  大模型不可用或调用失败 —— 明确说明，不退回模板

    模板答案已按团队决定移除：语言表达一律交给大模型。
    模型不可用时**如实说明不可用**，绝不用规则拼一段看似完整的答案顶替
    （引言 §5：不得使用模拟结果替代）。
    """
    q = (question or '').strip()
    status = record.get('status')
    task_type = record.get('task_type') or record.get('plan', {}).get('task_type')
    is_analysis = task_type in _ANALYSIS_TYPES

    # ---- 1) 非终态：状态报告（事实陈述，不需要模型）----
    if status in (PENDING, RUNNING):
        stage = record.get('stage')
        if is_analysis:
            text = ('分析任务尚未完成（状态 %s，环节：%s）。聚类拟合可能需要数分钟。'
                    % (status, stage or '排队中'))
        else:
            text = ('任务尚未完成（当前状态 %s，环节：%s）。完成后即可追问结果。'
                    % (status, stage or '排队中'))
        notes = record.get('plan', {}).get('notes') or ''
        if notes:
            text += '\nAgent 对本需求的理解：' + (
                ' '.join(notes) if isinstance(notes, list) else notes)
        return text, 'state'

    # ---- 2) 失败任务：如实报告失败环节与原因（事实陈述）----
    if status == FAILED:
        return '\n'.join(failure_answer(record)), 'state'

    # ---- 3) 终态：语言表达交给大模型 ----
    if not llm.enabled():
        return UNAVAILABLE_TEXT, 'unavailable'
    evidence = _analysis_evidence(record) if is_analysis else build_evidence(record)
    text = llm.answer_question(q, evidence, max_tokens=1024)
    if not text:
        return LLM_FAILED_TEXT, 'unavailable'
    return text, 'llm'
