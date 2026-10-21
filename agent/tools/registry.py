#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
迭代二六工具统一注册表（成员B搭框架，成员A/C按同名约定落位）

单一真源是 agent/config/analysis.json 的 algorithms 段：
  · 某类别下有登记条目（module/entry/parameters）-> 已实现；
  · 条目缺失或未登记 -> MODEL_NOT_FOUND（不猜测、不借用别的算法执行）。

成员A（分类）/成员C（降维）的工具合入后，只需：
  1. 把模块放到 analysis.json 登记的 module 路径（如 classification.xxx_tool）
  2. 在 algorithms.<类别> 下登记同名条目（module/entry/parameters/...）
本注册表即自动生效，接口与错误语义不变。

工具模块契约（六个工具同构）：
  run(payload: dict, acfg=None, rcfg=None) -> 统一信封 dict；失败抛 AnalysisError。
  CLI：python3 -I <file> --request req.json --output out.json
       成功打印 {"status":"SUCCESS",...}；失败打印 FAILED+error，退出码 2。
  调度器实际调用走 analysis_runner.tool_command()：仍是 -I 隔离进程，但经 -c 引导脚本
  把用户级 site-packages 补回 sys.path（-I 隐含 -s，pip install --user 装的
  numpy/sklearn 原本不可见，2026-10-21 修复），并统一注入 ML_CLEAN_DIR 指向
  analysis.json 登记的清洗快照（聚类与分类/降维此前默认路径不同，已在 runner 统一）。
  结论：工具的第三方依赖无论装在系统目录还是用户目录都可用。
命名约定（接口扩展规范 §七）：clustering_<algorithm> / classification_<algorithm> /
dimensionality_reduction_<algorithm>。
"""

import os
import sys

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.join(os.path.dirname(_TOOLS_DIR), 'src')
for _p in (_SRC_DIR, _TOOLS_DIR, os.path.join(_TOOLS_DIR, 'clustering')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config  # noqa: E402
from common import AnalysisError, MODEL_NOT_FOUND  # noqa: E402

CATEGORIES = ('clustering', 'classification', 'dimensionality_reduction')

# URL 段 <-> 内部类别名（接口扩展规范 §2.2 路径用连字符）
CATEGORY_SLUGS = {'clustering': 'clustering',
                  'classification': 'classification',
                  'dimensionality-reduction': 'dimensionality_reduction'}


def _node(category, acfg):
    return acfg['algorithms'].get(category, {})


def algorithm_names(category, acfg=None):
    """该类别下已登记且有模块路径的算法名（升序）。"""
    acfg = acfg or config.load_analysis()
    return sorted(k for k, v in _node(category, acfg).items()
                  if isinstance(v, dict) and v.get('module'))


def registered(category, algorithm, acfg=None):
    return algorithm in algorithm_names(category, acfg)


def tool_name(category, algorithm):
    """规范 §七 统一工具名，如 clustering_kmeans。"""
    return '%s_%s' % (category, algorithm)


def implemented_tools(acfg=None):
    """全部已实现工具名（供 MODEL_NOT_FOUND 提示与 /health 展示）。"""
    acfg = acfg or config.load_analysis()
    out = []
    for c in CATEGORIES:
        out += [tool_name(c, a) for a in algorithm_names(c, acfg)]
    return out


def require(category, algorithm, acfg=None):
    """
    校验并返回登记条目；未实现抛 MODEL_NOT_FOUND（消息列出已注册工具，
    让调用方一眼看到"不是没有这个接口，而是该算法尚未登记实现"）。
    """
    acfg = acfg or config.load_analysis()
    if category not in CATEGORIES:
        raise AnalysisError('INVALID_REQUEST', '未知分析类别: %s' % category)
    if not registered(category, algorithm, acfg):
        raise AnalysisError(
            MODEL_NOT_FOUND,
            '算法 %s 尚未在 analysis.json 登记实现（类别 %s）。已注册工具: %s'
            % (algorithm or '(未指定)', category, implemented_tools(acfg) or '无'),
            {'category': category, 'algorithm': algorithm,
             'registered': implemented_tools(acfg)})
    return _node(category, acfg)[algorithm]


def module_file(entry):
    """module 'clustering.kmeans_tool' -> 绝对路径 agent/tools/clustering/kmeans_tool.py"""
    parts = entry['module'].split('.')
    return os.path.join(_TOOLS_DIR, *parts) + '.py'


def in_process_run(category, algorithm, payload, acfg=None, rcfg=None):
    """
    同进程动态导入执行（供 run_fit 与测试用）。
    调度器在线程里走 subprocess 隔离（analysis_runner），两者共用同一 CLI/入口契约。
    """
    import importlib
    acfg = acfg or config.load_analysis()
    entry = require(category, algorithm, acfg)
    mod_name = entry['module']
    if _TOOLS_DIR not in sys.path:
        sys.path.insert(0, _TOOLS_DIR)
    mod = importlib.import_module(mod_name)
    fn = getattr(mod, entry.get('entry', 'run'))
    return fn(payload, acfg=acfg, rcfg=rcfg)
