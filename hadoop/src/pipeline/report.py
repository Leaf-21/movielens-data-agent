#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
评估报告构建模块

职责：构建接口规范要求的 report 对象。

对应接口规范：docs/接口规范文档.md 第 14 节

    "report": {
      "method": "五维质量评分方法说明",
      "improvements": [],
      "unresolved": [],
      "limitations": []
    }

其中：
  method        五维评分如何计算、评价范围、分值范围、指标依据
  improvements  清洗后哪些方面发生变化
  unresolved    仍然无法解决的问题
  limitations   哪些情况无法验证

设计说明
--------
method 与 limitations 的内容来自 docs/evaluation-method.md，
这里以结构化形式内嵌到 JSON 中，使 Agent 无需读取 Markdown 文件
即可生成用户可见的解释（接口规范第 2.1 节要求 Hadoop 不做自然语言解释，
但需要提供可供解释的"证据"）。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ml_common'))
import ml_common as ml

DIMENSION_CN = {
    'accurate': '准确性',
    'complete': '完整性',
    'unique': '唯一性',
    'up_to_date': '时效性',
    'consistent': '一致性',
}


# ---------------------------------------------------------------------------
# method：评分方法与依据
# ---------------------------------------------------------------------------

def build_method(scores, weights, cfg):
    """构建 method 字段：说明五维如何计算、评价范围与分值范围。"""
    return {
        'summary': '五维质量评分采用"违规率扣分"模型：'
                   '得分 = 100 × (1 − 违规记录数 ÷ 适用记录总数)，分值范围 0–100。',
        'dimensions': {
            'accurate': '字段值的合法性。对 12 项字段级检查做微平均（每字段一次机会），'
                        '避免字段数多的表主导整体得分。',
            'complete': '业务必需字段的完整性。仅统计"必需字段"缺失，'
                        '用户属性等自愿填写字段的缺失视为信息不足，不计入扣分。',
            'unique': '业务主键的唯一性。ratings 以 (UserID, MovieID) 为主键，'
                      'movies 以 MovieID、users 以 UserID 为主键。',
            'up_to_date': '时间戳的可解释性与新近程度。'
                          '本项仅计入第一层（时间可解释性），'
                          '不以"距今天"为参照，避免把历史数据误判为质量问题。',
            'consistent': '跨表引用完整性与表内格式一致性，两者各占 50%。',
        },
        'weights': dict(weights),
        'weight_note': '综合分 = 五维加权平均。权重为设计选择而非测量结果，'
                       '改变权重会改变综合分排序。',
        'overall': scores.get('overall'),
        'score_range': '[0, 100]',
        'same_criteria': '清洗前后使用同一份评分程序、同一套阈值与权重，仅输入数据集不同，'
                         '以保证结果可比较。',
        'rule_version': cfg.get('rule_version'),
        'evaluation_doc': 'docs/evaluation-method.md',
    }


# ---------------------------------------------------------------------------
# improvements：清洗后的变化
# ---------------------------------------------------------------------------

def build_improvements(before_scores, after_scores):
    """
    构建 improvements 字段。

    只在 After 评分存在时生成。每个元素说明某一维度的变化量。
    注意：变化量可能为 0 或为负，**如实报告**，不做美化。
    依据 docs/迭代一_Hadoop数据清洗与Agent基础.md 第 69 行：
    "不要求所有维度的分数都提高，也不预设必须达到的分数"。
    """
    if not after_scores or before_scores is None:
        return []

    items = []
    for dim in ('accurate', 'complete', 'unique', 'up_to_date', 'consistent'):
        b = before_scores.get(dim)
        a = after_scores.get(dim)
        if b is None or a is None:
            continue
        delta = round(a - b, 4)
        if abs(delta) < 1e-9:
            desc = '%s维度得分未变化（%.4f）。%s' % (
                DIMENSION_CN[dim], b, _unchanged_hint(dim))
        elif delta > 0:
            desc = '%s维度得分由 %.4f 提升至 %.4f，变化 +%.4f。%s' % (
                DIMENSION_CN[dim], b, a, delta, _improved_hint(dim))
        else:
            desc = '%s维度得分由 %.4f 下降至 %.4f，变化 %.4f。%s' % (
                DIMENSION_CN[dim], b, a, delta, _declined_hint(dim))
        items.append({
            'dimension': dim,
            'dimension_cn': DIMENSION_CN[dim],
            'before': b,
            'after': a,
            'delta': delta,
            'description': desc,
        })
    return items


def _unchanged_hint(dim):
    hints = {
        'accurate': '原始数据未发现字段合法性错误。',
        'complete': '原始数据无必需字段缺失。',
        'unique': '原始数据主键天然唯一，不存在重复记录，本维度没有可改进空间。',
        'up_to_date': '时间戳全部可解释，属客观事实，不因清洗而变化。',
        'consistent': '跨表引用与格式均无违规。',
    }
    return hints.get(dim, '')


def _improved_hint(dim):
    hints = {
        'accurate': '主要由于非法字段值被修复或隔离。',
        'complete': '主要由于关键字段缺失的记录被隔离。',
        'unique': '主要由于重复记录被去重。',
        'up_to_date': '主要由于时间不可解释的记录被隔离。',
        'consistent': '主要由于跨表关联断裂的记录被隔离，或格式不一致的字段被规范化。',
    }
    return hints.get(dim, '')


def _declined_hint(dim):
    hints = {
        # 时效性下降的典型机制：脏数据里的异常时间戳（毫秒戳、未来时间）会被
        # freshness 的 clamp 上界拉到 1，把清洗前均值抬高；清洗后回落到真实水平。
        # 这不是清洗引入的新问题，必须与"清洗把数据弄坏了"区分开。
        'up_to_date': '本维度不以"错误率"衡量，而是衡量数据的新近程度：'
                      '清洗前的较高得分可能来自被 clamp 到上界的异常时间戳'
                      '（如毫秒时间戳、2100 年时间戳），清洗后回落到真实水平。'
                      '需在报告中核对是否属于这种情况，不得直接判定为清洗引入的新问题。',
    }
    return hints.get(
        dim,
        '得分下降需要核查原因：既可能是清洗规则引入的新问题，'
        '也可能是脏数据的虚高得分被还原。请结合 before/after 指标逐项核对，'
        '不得忽略，也不得默认是清洗的错。')


# ---------------------------------------------------------------------------
# unresolved：仍未解决的问题
# ---------------------------------------------------------------------------

def build_unresolved(unresolved_problems):
    """
    构建 unresolved 字段。

    依据 docs/迭代一_Hadoop数据清洗与Agent基础.md 第 91 行：
    避免将删除或隔离记录直接表述为"问题已修复"。
    因此这里逐条说明问题的**真实性质**，而不统一写成"已解决"。
    """
    items = []
    for p in unresolved_problems:
        action = p['action']
        if action == 'isolate':
            how = '已隔离：该批记录被移出主数据集单独保存，问题本身未被修正。'
        elif action == 'fix':
            how = '计划修复：可确定正确值，将在清洗阶段规范化。'
        elif action == 'dedupe':
            how = '计划去重：重复记录将被移除。'
        else:
            how = '待处理。'
        items.append({
            'code': p['code'],
            'dimension': p['dimension'],
            'dimension_cn': DIMENSION_CN.get(p['dimension'], p['dimension']),
            'count': p['count'],
            'subject': p['subject'],
            'disposition': how,
        })
    return items


# ---------------------------------------------------------------------------
# limitations：无法验证的情况
# ---------------------------------------------------------------------------
# 依据 docs/接口规范文档.md 第 14 节与 docs/evaluation-method.md 第 6.2 节。
# 内容为固定说明，不随数据变化。
# ---------------------------------------------------------------------------
LIMITATIONS = [
    {
        'topic': '用户属性真实性',
        'detail': 'users.dat 的性别、年龄、职业、邮编由用户自愿填写，'
                  'GroupLens 未核验其准确性。格式正确不能证明内容真实。',
    },
    {
        'topic': '评分是否反映真实偏好',
        'detail': '数据集不含行为真值，"用户评了 5 分"是否反映真实喜好无法从数据判定。',
    },
    {
        'topic': 'Zip-code 与地区的一致性',
        'detail': '缺少地区真值参照，无法交叉验证邮编与职业等信息是否匹配。',
    },
    {
        'topic': '匿名用户的身份',
        'detail': '用户标识已匿名化，无法判断不同 UserID 是否属于同一自然人。',
    },
    {
        'topic': '同名电影是否为同一部',
        'detail': '不同 MovieID 可能存在相同标题（如翻拍作品），'
                  '仅凭标题无法判定，需外部知识库。',
    },
    {
        'topic': '时间戳时区',
        'detail': '数据集未声明时区，本系统统一按 UTC 解释，可能存在固定偏移。',
    },
    {
        'topic': '评分行为分布是否异常',
        'detail': '用户评分数量差异大、评分集中在高分等现象，'
                  '依据项目需求第 51 行需结合数据背景判断，本系统不作为质量问题扣分。',
    },
    {
        'topic': '合法性不等于准确性',
        'detail': '准确性维度实际衡量的是"字段值合法率"，不能等同于"数据真实准确"。',
    },
]


# ---------------------------------------------------------------------------
# 组装
# ---------------------------------------------------------------------------

def build_report(before_scores, after_scores, weights, cfg, unresolved_problems):
    """组装完整的 report 对象。"""
    return {
        'method': build_method(before_scores, weights, cfg),
        'improvements': build_improvements(before_scores, after_scores),
        'unresolved': build_unresolved(unresolved_problems),
        'limitations': LIMITATIONS,
        '_status': ('完整报告：含清洗前后对比'
                    if after_scores else
                    '阶段性报告：清洗尚未执行，improvements 为空'),
    }
