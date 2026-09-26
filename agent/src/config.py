#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent 配置与版本管理

职责：
  1. 定位仓库路径与运行时目录
  2. 加载数据版本 / 规则版本 / T1-T2 —— 一律以 hadoop/config/rules.json
     为唯一生效来源（该文件头部明确要求"修改本文件须通知成员B"，
     因此 Agent 绝不另存一份权重或时间边界，防止口径漂移）
  3. 读取 agent/config/versions.json 版本登记表（仅登记"含义与来源"，
     供解析与解释使用，不重复存储生效数值）
  4. 对创建任务请求做版本校验（接口规范第 15 / 16 / 17 节）
"""

import datetime
import json
import os
import sys

if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from errors import (INVALID_REQUEST, INVALID_DATA_VERSION,  # noqa: E402
                    INVALID_RULE_VERSION)

SRC_DIR = os.path.dirname(os.path.abspath(__file__))          # agent/src
AGENT_DIR = os.path.dirname(SRC_DIR)                           # agent
REPO_DIR = os.path.dirname(AGENT_DIR)                          # 仓库根

# ---------------------------------------------------------------------------
# 运行时目录：任务记录与结果快照。整体被 .gitignore 排除（运行产物）。
# ---------------------------------------------------------------------------
RUNTIME_DIR = os.path.join(AGENT_DIR, 'runtime')
TASKS_DIR = os.path.join(RUNTIME_DIR, 'tasks')
RESULTS_DIR = os.path.join(RUNTIME_DIR, 'results')

# ---------------------------------------------------------------------------
# 服务默认参数（环境变量可覆盖，便于联调时不改代码）
# ---------------------------------------------------------------------------
AGENT_HOST = os.environ.get('ML_AGENT_HOST', '127.0.0.1')
AGENT_PORT = int(os.environ.get('ML_AGENT_PORT', '8090'))

# 规则文件查找顺序与成员A的 ml_common.resolve_rules_path 相同：
#   1. ML_RULES 环境变量  2. hadoop/config/rules.json
RULES_PATH_DEFAULT = os.path.join(REPO_DIR, 'hadoop', 'config', 'rules.json')
VERSIONS_PATH = os.path.join(AGENT_DIR, 'config', 'versions.json')

_RULES_CACHE = None
_VERSIONS_CACHE = None


def rules_path():
    p = os.environ.get('ML_RULES') or RULES_PATH_DEFAULT
    return p


def load_rules():
    """加载 rules.json。找不到或解析失败时抛异常，绝不静默用默认值。"""
    global _RULES_CACHE
    if _RULES_CACHE is not None:
        return _RULES_CACHE
    p = rules_path()
    if not os.path.exists(p):
        raise RuntimeError(
            '[agent.config] 找不到规则配置 rules.json: %s\n'
            '  Agent 的评分口径、版本命名与 T1/T2 均以其为准，不允许使用内置默认值。' % p)
    with open(p, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    _RULES_CACHE = cfg
    return cfg


def load_versions_registry():
    """读取 agent/config/versions.json（版本登记表）。"""
    global _VERSIONS_CACHE
    if _VERSIONS_CACHE is not None:
        return _VERSIONS_CACHE
    with open(VERSIONS_PATH, 'r', encoding='utf-8') as f:
        reg = json.load(f)
    _VERSIONS_CACHE = reg
    return reg


def rules_weights(cfg):
    """从 rules.json 提取五维权重（过滤掉 _comment 类说明键）。"""
    return {k: float(v) for k, v in cfg['weights'].items() if not k.startswith('_')}


# ---------------------------------------------------------------------------
# 版本校验（接口规范第 16 节：数据版本 / 规则版本必须被登记）
# ---------------------------------------------------------------------------

def known_data_versions(cfg):
    reg = load_versions_registry()
    vs = set(reg.get('data_versions', {}).keys())
    # rules.json 中生效的两个版本必须在登记表内，防止两处漂移
    vs.add(cfg['input_version'])
    vs.add(cfg['output_version'])
    return vs


def known_rule_versions(cfg):
    reg = load_versions_registry()
    vs = set(reg.get('rule_versions', {}).keys())
    vs.add(cfg['rule_version'])
    return vs


def validate_data_version(data_version, cfg):
    """返回 (规范值, None) 或 (None, 错误dict)。错误dict 即接口规范第 15 节的 error 对象。"""
    if not isinstance(data_version, str) or not data_version.strip():
        return None, {'code': INVALID_REQUEST,
                      'message': 'data_version 必须是非空字符串'}
    dv = data_version.strip()
    if dv not in known_data_versions(cfg):
        return None, {'code': INVALID_DATA_VERSION,
                      'message': '数据版本未登记: %s' % dv,
                      'detail': '已知版本: %s' % sorted(known_data_versions(cfg))}
    return dv, None


def validate_rule_version(rule_version, cfg):
    """rule_version 可为 None / 'default'（使用系统登记的默认方案，见接口规范第 4 节）。"""
    if rule_version is None:
        return cfg['rule_version'], None
    if not isinstance(rule_version, str) or not rule_version.strip():
        return None, {'code': INVALID_REQUEST,
                      'message': 'rule_version 若提供，必须是非空字符串或 "default"'}
    rv = rule_version.strip()
    if rv == 'default':
        return cfg['rule_version'], None
    if rv not in known_rule_versions(cfg):
        return None, {'code': INVALID_RULE_VERSION,
                      'message': '清洗规则版本未登记: %s' % rv,
                      'detail': '已知版本: %s' % sorted(known_rule_versions(cfg))}
    return rv, None


# ---------------------------------------------------------------------------
# T1 / T2（接口规范第 17 节）
# 同时给出日期与精确 epoch：仅日期不可复现划分（见 rules.json _derivation）
# ---------------------------------------------------------------------------

def epoch_to_date(ts):
    return datetime.datetime.fromtimestamp(
        int(ts), datetime.timezone.utc).strftime('%Y-%m-%d')


def time_boundaries(cfg):
    t = cfg['time']
    return {
        'T1': epoch_to_date(t['T1_epoch']),
        'T2': epoch_to_date(t['T2_epoch']),
        'T1_epoch': int(t['T1_epoch']),
        'T2_epoch': int(t['T2_epoch']),
        'split_rule': t.get('split_rule'),
    }


def now_iso():
    """UTC ISO 时间戳，用于任务记录。"""
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
