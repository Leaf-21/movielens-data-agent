#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
评分管线模块桥接（复用成员A的 problems / report 构建逻辑）

为什么 Agent 直接 import 成员A的 pipeline 模块，而不是自己重写一份：
  1. 单一事实来源。问题清单映射表（PROBLEM_RULES）和评估报告文案
     （method / improvements / unresolved / limitations）是"评价口径"的一部分。
     如果 Agent 复制一份，两次实现就会漂移 —— 同一个任务在
     driver --stage all 路径与 Agent HTTP 路径下产出不一致的问题清单，
     直接违反接口规范第 11 节"清洗前后必须使用同一套评价口径"。
  2. 这两个模块是纯函数（输入 dict -> 输出 dict），零第三方依赖，
     不触碰 Hadoop，也不读写文件，import 它们不会引入执行副作用。
  3. 职责边界（接口规范第 2.1 节）说的是"Agent 不实现清洗/评分算法"。
     问题映射与报告文案属于"结果解释"的素材装配，不是评分计算 ——
     计算仍然全部发生在 Hadoop。

注意：这些模块内部通过 __file__ 定位 hadoop/config/rules.json，
在仓库内 import 时路径解析正常，无需额外设置 ML_RULES。
"""

import os
import sys

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_DIR = os.path.dirname(os.path.dirname(_SRC_DIR))

_HADOOP_COMMON = os.path.join(_REPO_DIR, 'hadoop', 'src', 'common')
_HADOOP_PIPELINE = os.path.join(_REPO_DIR, 'hadoop', 'src', 'pipeline')

for p in (_HADOOP_COMMON, _HADOOP_PIPELINE):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    import ml_common                      # noqa: E402  规则加载 / 常量
    import problems as problems_mod       # noqa: E402  PROBLEM_RULES 指标->问题映射
    import report as report_mod           # noqa: E402  method/improvements/unresolved/limitations
except Exception as e:  # pragma: no cover
    raise RuntimeError(
        '[agent.pipeline_bridge] 无法加载 Hadoop 评分管线模块：\n  %r\n'
        '请确认仓库完整（hadoop/src/common 与 hadoop/src/pipeline 存在）。' % e)


def load_rules():
    """透传成员A的规则加载（同一解析逻辑、同一文件、同一校验）。"""
    return ml_common.load_rules()


def build_problems(metrics):
    """
    指标 -> (problems, unresolved)。

    ⚠️ Agent 的用法与成员A有一处刻意的差别（成员B设计决定，需在 PR 说明）：
      成员A在 driver --stage all 路径下用 before 指标构建 unresolved
      （含义是"本轮计划处置的问题"）；
      Agent 在清洗完成后改用 after 指标计算 unresolved
      （含义是"清洗后依然存在的问题"）。
      后者与接口规范第 14 节对 unresolved 的定义（"仍然无法解决的问题"）
      更贴近，且两个口径都来自同一张 PROBLEM_RULES 映射表，不存在
      "换了一套判定标准"的问题。
    """
    return problems_mod.build_problems(metrics)


def build_report(before_scores, after_scores, weights, cfg, unresolved_problems):
    """组装 report 对象（接口规范第 14 节）。after_scores 为 None 时
    improvements 为空、_status 标注为阶段性报告 —— 与成员A行为一致。"""
    return report_mod.build_report(before_scores, after_scores, weights, cfg,
                                   unresolved_problems)


DIM_ORDER = ('accurate', 'complete', 'unique', 'up_to_date', 'consistent')
