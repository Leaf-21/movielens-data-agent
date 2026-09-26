#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
问题清单构建模块

职责：把检查程序产出的指标（metrics）转换为接口规范要求的问题清单字段。

对应接口规范：docs/接口规范文档.md 第 13 节
  "problems": [],
  "unresolved_problems": [],

设计说明
--------
指标名（如 ratings_r_rating_bad）对人不可读，而前端与 Agent 需要的是
"哪个维度、什么问题、多少条、怎么处置"。因此这里用一张声明式规则表
把指标名映射为可展示的问题描述，而不是在代码里散落 if-else。

添加新检查项时，只需在 PROBLEM_RULES 中增加一条规则。

处置方式（action）取值与接口规范一致：
  fix       修复 —— 能确定正确值并改回
  dedupe    去重 —— 完全重复或业务主键重复
  isolate   隔离 —— 疑似错误但无法确证，移出主数据集
  keep      保留 —— 确认不是错误，仅需保证读取/输出方式正确
  observe   仅观察 —— 疑似异常但需结合业务背景判断，不扣分
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ml_common'))
import ml_common as ml


# ---------------------------------------------------------------------------
# 指标 -> 问题 的映射表
#
# 字段说明：
#   key        指标名（与 mapper 输出的名字一致，reducer 已加表名前缀）
#   dimension  所属五维
#   action     处置方式
#   severity   high / medium / low / info
#   subject    问题对象（面向用户的可读描述）
#   reason     产生原因
#   fixable    是否可通过"修复"消除（决定属于 problems 还是需要隔离）
# ---------------------------------------------------------------------------
PROBLEM_RULES = [
    # ---- 准确性：Zip-code ----
    dict(key='users_u_zip_bad', dimension='accurate', action='fix',
         severity='low', fixable=True,
         subject='Zip-code 不符合 5 位数字格式',
         reason='其中美国 ZIP+4 扩展格式（NNNNN-NNNN）可安全截取前 5 位；'
                '其余形式（非数字、纯数字但位数不对、空值）无法确定正确值，需隔离'),

    # ---- 准确性：其余字段（实测均为 0，保留以便后续数据出现问题时自动报出）----
    dict(key='ratings_r_uid_bad', dimension='accurate', action='isolate',
         severity='high', fixable=False,
         subject='ratings.UserID 不是正整数',
         reason='标识符格式异常，无法确定正确值'),
    dict(key='ratings_r_mid_bad', dimension='accurate', action='isolate',
         severity='high', fixable=False,
         subject='ratings.MovieID 不是正整数',
         reason='标识符格式异常，无法确定正确值'),
    dict(key='ratings_r_rating_bad', dimension='accurate', action='isolate',
         severity='high', fixable=False,
         subject='Rating 超出 1-5 范围或不是整数',
         reason='评分值非法，且无法推断用户真实评分'),
    dict(key='ratings_r_ts_bad', dimension='accurate', action='isolate',
         severity='medium', fixable=False,
         subject='Timestamp 不可解释或超出数据集时间范围',
         reason='时间戳无法解释，无法确定正确时间'),
    dict(key='movies_m_mid_bad', dimension='accurate', action='isolate',
         severity='high', fixable=False,
         subject='movies.MovieID 不是正整数',
         reason='标识符格式异常'),
    dict(key='movies_m_title_empty', dimension='accurate', action='isolate',
         severity='high', fixable=False,
         subject='电影标题为空',
         reason='缺少必需字段，无法补全'),
    dict(key='movies_m_year_missing', dimension='accurate', action='keep',
         severity='low', fixable=False,
         subject='标题结尾缺少年份',
         reason='年份缺失属信息不足，不影响记录唯一性'),
    dict(key='movies_m_year_bad', dimension='accurate', action='keep',
         severity='low', fixable=False,
         subject='标题年份超出合理范围',
         reason='需结合外部资料判断，不在本轮处理范围'),
    dict(key='users_u_uid_bad', dimension='accurate', action='isolate',
         severity='high', fixable=False,
         subject='users.UserID 不是正整数',
         reason='标识符格式异常'),
    dict(key='users_u_gender_bad', dimension='accurate', action='isolate',
         severity='low', fixable=False,
         subject='Gender 不在 {M, F} 范围',
         reason='取值编码超出数据说明，无法确定真实性别，移出主数据集'),
    dict(key='users_u_age_bad', dimension='accurate', action='isolate',
         severity='low', fixable=False,
         subject='Age 不属于规定年龄段编码',
         reason='取值编码超出数据说明，无法确定真实年龄段，移出主数据集'),
    dict(key='users_u_occ_bad', dimension='accurate', action='isolate',
         severity='low', fixable=False,
         subject='Occupation 超出 0-20 编码范围',
         reason='取值编码超出数据说明，无法确定真实职业，移出主数据集'),

    # ---- 完整性：必需字段缺失 ----
    dict(key='ratings_missing', dimension='complete', action='isolate',
         severity='high', fixable=False,
         subject='ratings 存在必需字段缺失的记录',
         reason='必需字段缺失使记录无法参与分析'),
    dict(key='movies_missing', dimension='complete', action='isolate',
         severity='high', fixable=False,
         subject='movies 存在必需字段缺失的记录',
         reason='必需字段缺失使记录无法定位'),
    dict(key='users_missing', dimension='complete', action='isolate',
         severity='high', fixable=False,
         subject='users 存在 UserID 缺失的记录',
         reason='缺少主键，记录无法关联'),

    # ---- 唯一性 ----
    dict(key='ratings_pair_dup_violations', dimension='unique', action='dedupe',
         severity='high', fixable=True,
         subject='同一用户对同一电影存在多条评分记录',
         reason='业务主键 (UserID, MovieID) 重复'),
    dict(key='movies_movie_dup_violations', dimension='unique', action='dedupe',
         severity='high', fixable=True,
         subject='movies.MovieID 重复',
         reason='主键重复'),
    dict(key='users_user_dup_violations', dimension='unique', action='dedupe',
         severity='high', fixable=True,
         subject='users.UserID 重复',
         reason='主键重复'),

    # ---- 一致性：跨表引用 ----
    dict(key='users_orphan_records', dimension='consistent', action='isolate',
         severity='high', fixable=False,
         subject='ratings 引用的 UserID 在 users 中不存在',
         reason='跨表关联断裂，评分记录无法关联到用户属性'),
    dict(key='movies_orphan_records', dimension='consistent', action='isolate',
         severity='high', fixable=False,
         subject='ratings 引用的 MovieID 在 movies 中不存在',
         reason='跨表关联断裂，评分记录无法关联到电影信息'),

    # ---- 一致性：表内冲突与格式 ----
    # 冲突（同一主键多个不同取值）由清洗侧的 conflict_policy 处置：保留一条、其余按重复移除，
    # 但**保留一条不等于修正**，因此这类问题由 driver 依据清洗统计单独列入未解决问题。
    dict(key='movies_value_multi_violations', dimension='consistent', action='dedupe',
         severity='high', fixable=False,
         subject='同一 MovieID 对应多个 Title 或 Genres',
         reason='同一标识对应矛盾信息，数据本身无法判断哪个正确；'
                '清洗按确定性规则保留一条，其余移除，该问题**未真正解决**'),
    dict(key='users_attr_multi_violations', dimension='consistent', action='dedupe',
         severity='medium', fixable=False,
         subject='同一 UserID 对应多组冲突的用户属性',
         reason='属性冲突，数据本身无法判断哪组正确；'
                '清洗按确定性规则保留一条，其余移除，该问题**未真正解决**'),
    dict(key='movies_m_genres_dup', dimension='consistent', action='fix',
         severity='low', fixable=True,
         subject='Genres 内部出现重复类型',
         reason='如 Drama|Drama，可安全去重'),
    dict(key='movies_m_genres_emptyitem', dimension='consistent', action='fix',
         severity='low', fixable=True,
         subject='Genres 内部存在空项',
         reason='如 Drama|，可安全去除空项'),
    dict(key='movies_m_genres_unknown', dimension='consistent', action='isolate',
         severity='low', fixable=False,
         subject='Genres 出现未识别的类型名称',
         reason='类别不在 ml-1m 的 18 个标准类别内（如注入的 UnknownGenre），'
                '无法确定应映射到哪个标准类别，移出主数据集'),
    dict(key='movies_m_genres_empty', dimension='consistent', action='isolate',
         severity='low', fixable=False,
         subject='Genres 字段为空',
         reason='类型信息完全缺失，无法通过其它字段推导；'
                '注意 Genres 属可选属性，此处置是"无法验证"而非"记录错误"'),
    dict(key='movies_m_title_space', dimension='consistent', action='fix',
         severity='low', fixable=True,
         subject='电影标题首尾存在空白字符',
         reason='可安全去除首尾空白'),
    dict(key='movies_m_title_nonascii', dimension='consistent', action='keep',
         severity='info', fixable=False,
         subject='电影标题含 ISO-8859-1 特殊字符',
         reason='数据本身正确（如 Misérables），属编码处理问题。'
                '必须确保按 ISO-8859-1 读取并以同编码输出'),

    # ---- 时效性 ----
    dict(key='ratings_r_ts_bad', dimension='up_to_date', action='isolate',
         severity='medium', fixable=False,
         subject='时间戳不可解释，无法参与时效性评价',
         reason='时间不可解释的记录无法归入任何时间窗口'),
]


def _resolve(metrics, key):
    """读取指标值，缺失视为 0。"""
    return int(metrics.get(key, 0) or 0)


def build_problems(metrics, scores=None):
    """
    构建问题清单。

    返回 (problems, unresolved_problems)：
      problems            —— 本轮识别出的全部问题（含已解决与未解决）
      unresolved_problems —— 本轮结束后仍然存在的问题

    判定逻辑：
      · 违规数为 0 的项不进入 problems（不需要向用户展示"没问题的问题"）
      · action='keep' 的项进入 problems 但**不算未解决**，因为已确认它不是错误
      · action=fix/dedupe/isolate 的项在清洗执行前全部算未解决
    """
    problems = []
    unresolved = []

    for rule in PROBLEM_RULES:
        n = _resolve(metrics, rule['key'])
        if n <= 0:
            continue

        item = {
            'code': rule['key'],
            'dimension': rule['dimension'],
            'action': rule['action'],
            'severity': rule['severity'],
            'count': n,
            'subject': rule['subject'],
            'reason': rule['reason'],
        }
        problems.append(item)

        # keep 类型的项已确认不是错误，不计入未解决问题
        if rule['action'] != 'keep':
            unresolved.append(dict(item))

    return problems, unresolved


def summarize_by_action(problems):
    """按处置方式汇总条数，便于前端展示"修复/去重/隔离"三类统计。"""
    out = {}
    for p in problems:
        out[p['action']] = out.get(p['action'], 0) + p['count']
    return out


if __name__ == '__main__':
    # 便于单独调试：从 JSON 文件读入 metrics 并打印问题清单
    import json
    if len(sys.argv) < 2:
        raise SystemExit('用法: python3 problems.py <含 metrics 的 JSON 文件>')
    data = json.load(open(sys.argv[1], encoding='utf-8'))
    probs, unres = build_problems(data.get('metrics', {}))
    print('problems: %d 条' % len(probs))
    for p in probs:
        print('  [%s/%s] %s  %d 条' % (p['dimension'], p['action'], p['subject'], p['count']))
    print('unresolved_problems: %d 条' % len(unres))
    print('按处置汇总:', summarize_by_action(probs))
