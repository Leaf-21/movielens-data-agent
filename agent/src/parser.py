#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
需求解析（Prompt → 执行计划）

对应分工文档中成员B的"Prompt / 流程设计"交付物。
完整设计说明见 docs/流程与Prompt设计.md，本文件是实现。

解析策略（两级，先确定后兜底）
------------------------------
第一级：确定性关键词规则。
  迭代一的需求句式有限（清洗+评估 / 只评估 / 指定维度 / 指定版本），
  用规则即可覆盖，结果可测试、可复现、零成本 —— 这是主路径。

第二级：可选的大模型分类（llm.classify_intent）。
  仅当规则一个都没命中（既无清洗类词汇也无评估类词汇）时调用；
  大模型只允许在【已支持的计划集合】里做选择，不允许生成任何数值。
  未安装 anthropic 包或未配置密钥时自动跳过（llm.AVAILABLE=False），
  行为回退到"项目默认流程 = 评估+清洗+对比"。

为什么不解析"只评某几个维度"：
  成员A的评分作业始终计算全部五维（driver 无按维度开关的入口），
  score_config 在契约里按第 9 节原样传递。解析出的"关注维度"
  只影响【结果解释的侧重】，不影响评分口径 —— 保证第 11 节
  "清洗前后同一口径"不被用户话术破坏。
"""

import re

try:
    import llm
except ImportError:  # 允许以包外路径直接加载
    from agent_src_stub import llm  # pragma: no cover

DIM_ORDER = ('accurate', 'complete', 'unique', 'up_to_date', 'consistent')

# 维度关键词（含常见口语说法）
DIM_KEYWORDS = {
    'accurate':   ['准确', '合法', '错误值', '格式正确'],
    'complete':   ['完整', '缺失'],
    'unique':     ['唯一', '重复', '去重'],
    'up_to_date': ['时效', '新鲜', '时间分布'],
    'consistent': ['一致', '引用', '关联', '孤儿'],
}

# "不清洗 / 只评分"类表述 —— 命中则计划止步于 Before 评分
NO_CLEAN_PATTERNS = [
    '不清洗', '不要清洗', '无需清洗', '不用清洗', '别清洗', '先不清洗',
    '只评估', '仅评估', '只评分', '只打分', '仅评分', '只要评分',
    '只跑评分', 'evaluate only', 'before only', 'score only',
    'evaluate-only', 'before-only', 'score-only',
]

# "清洗"类表述 —— 命中则确定走完整流程
CLEAN_PATTERNS = [
    '清洗', '治理', '清理', '去重', '隔离', '修复', '规范化',
    'clean',
]

# 版本抽取（接口规范第 16 节的命名规范）
DATA_VERSION_RE = re.compile(r'movielens-1m-v\d+(?:-clean-v\d+)?')
RULE_VERSION_RE = re.compile(r'rule-v\d+')


def detect_dimensions(prompt):
    """从自然语言中识别用户关注的维度。"""
    text = (prompt or '').lower()
    hit = []
    for dim, words in DIM_KEYWORDS.items():
        if any(w.lower() in text for w in words):
            hit.append(dim)
    return [d for d in DIM_ORDER if d in hit]


def detect_versions(prompt):
    """抽取提示词里显式给出的数据版本与规则版本。"""
    dv = DATA_VERSION_RE.search(prompt or '')
    rv = RULE_VERSION_RE.search(prompt or '')
    return (dv.group(0) if dv else None,
            rv.group(0) if rv else None)


def build_plan(prompt, data_version, rule_version, score_config=None,
               allow_llm=True):
    """
    把自然语言需求 + 结构化参数解析为执行计划。

    返回 dict：
      do_clean         是否执行清洗与 After 评分
      focus_dimensions 用户关注的维度（只影响解释侧重）
      data_version     生效的数据版本（请求字段优先，提示词兜底）
      rule_version     生效的规则版本（同上）
      score_config     原样传递给 Hadoop 的评分配置（可为 None）
      notes            解析过程的可见说明（供前端展示"Agent 理解到了什么"）
      llm_used         是否使用了大模型兜底分类
    """
    text = prompt or ''
    lower = text.lower()
    notes = []

    # ---- 是否清洗 ----
    if any(p in lower for p in NO_CLEAN_PATTERNS):
        do_clean = False
        source = 'rule'
        notes.append('检测到"只评估、不清洗"的表述，任务将在清洗前评分后结束。')
    elif any(p in lower for p in CLEAN_PATTERNS):
        do_clean = True
        source = 'rule'
    else:
        # 规则未命中：尝试大模型兜底，仍不行则走项目默认流程
        do_clean = True
        source = 'default'
        if allow_llm and llm.AVAILABLE:
            verdict = llm.classify_intent(text)
            if verdict and 'do_clean' in verdict:
                do_clean = bool(verdict['do_clean'])
                source = 'llm'
                notes.append('表述未命中关键词，由大模型判定为%s。'
                             % ('"完整流程（评估+清洗+对比）"' if do_clean
                                else '"仅评估"'))
        notes.append('未识别到明确的清洗/仅评估表述，采用项目默认流程：%s。'
                     % ('评估+清洗+对比' if do_clean else '仅评估'))

    # ---- 关注维度 ----
    focus = detect_dimensions(text)
    if focus:
        notes.append('用户关注维度：%s（评分仍按五维全量执行，解释将侧重这些维度）。'
                     % '、'.join(focus))

    # ---- 版本：请求字段优先，提示词兜底 ----
    dv_from_prompt, rv_from_prompt = detect_versions(text)
    final_dv = data_version
    if dv_from_prompt and dv_from_prompt != data_version:
        notes.append('提示词中出现数据版本 %s，但请求字段 data_version=%s 优先。'
                     % (dv_from_prompt, data_version))
    final_rv = rule_version
    if rv_from_prompt and rule_version and rv_from_prompt != rule_version:
        notes.append('提示词中出现规则版本 %s，但请求字段 rule_version=%s 优先。'
                     % (rv_from_prompt, rule_version))

    return {
        'do_clean': do_clean,
        'clean_intent_source': source,   # rule | llm | default（可追溯）
        'focus_dimensions': focus,
        'data_version': final_dv,
        'rule_version': final_rv,
        'score_config': score_config,
        'notes': notes,
        'llm_used': source == 'llm',
    }
