#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务模型常量

状态与阶段的取值严格照抄 docs/接口规范文档.md 第 7 节，
前端（成员C）按同一张表渲染，任何一处改名都属于接口变更（第 20 节）。
"""

# ---------------------------------------------------------------------------
# 任务状态（接口规范第 7 节）
# ---------------------------------------------------------------------------
PENDING = 'PENDING'
RUNNING = 'RUNNING'
SUCCESS = 'SUCCESS'
FAILED = 'FAILED'
STATUSES = (PENDING, RUNNING, SUCCESS, FAILED)
TERMINAL_STATUSES = (SUCCESS, FAILED)

# ---------------------------------------------------------------------------
# 执行阶段（接口规范第 7 节）
# ---------------------------------------------------------------------------
PARSE_REQUEST = 'PARSE_REQUEST'
BEFORE_SCORE = 'BEFORE_SCORE'
CLEANING = 'CLEANING'
AFTER_SCORE = 'AFTER_SCORE'
GENERATE_REPORT = 'GENERATE_REPORT'
COMPLETED = 'COMPLETED'
STAGES = (PARSE_REQUEST, BEFORE_SCORE, CLEANING, AFTER_SCORE,
          GENERATE_REPORT, COMPLETED)

# 阶段 -> 面向用户的进度说明（接口规范第 6 节示例的措辞）
STAGE_MESSAGES = {
    PARSE_REQUEST: '正在解析用户需求',
    BEFORE_SCORE: '正在执行清洗前质量评分',
    CLEANING: '正在执行 Hadoop 数据清洗',
    AFTER_SCORE: '正在执行清洗后质量评分',
    GENERATE_REPORT: '正在汇总结果并生成评估报告',
    COMPLETED: '任务执行完成',
}

# ---------------------------------------------------------------------------
# 五维字段（接口规范第 12 节）
# ---------------------------------------------------------------------------
DIM_ORDER = ('accurate', 'complete', 'unique', 'up_to_date', 'consistent')

DIM_CN = {
    'accurate': '准确性',
    'complete': '完整性',
    'unique': '唯一性',
    'up_to_date': '时效性',
    'consistent': '一致性',
}


def is_terminal(status):
    return status in TERMINAL_STATUSES
