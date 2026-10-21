#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
极简 .env 加载器（成员B）

目的：让「本地填 API Key」这件事不必修改代码、也不必每次 export。
只用标准库，不引入 python-dotenv。

规则（与社区通用的 dotenv 行为保持一致）：
  · 文件不存在 -> 静默跳过（这是可选能力，缺失不算错误）
  · **不覆盖已存在的真实环境变量** —— 显式 `export XXX=yyy` 永远优先，
    便于临时切换/调试，也避免 .env 里的旧值意外盖掉 CI 注入的凭据。
  · 支持 `KEY=VALUE`、`export KEY=VALUE`、`#` 整行注释、空行
  · 值可被单/双引号包裹；未包裹时去掉行内 ` #` 之后的注释
  · 键名需匹配 [A-Za-z_][A-Za-z0-9_]*

查找顺序（先找到的优先生效，同名键以先出现的为准）：
  1. 环境变量 ML_ENV_FILE 指定的路径
  2. 仓库根 .env
  3. agent/.env
"""

import io
import os
import re

_REPO_DIR = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))          # .../movielens-data-agent
_KEY_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')

#: 本次进程内确实由 .env 注入的键（只记键名，便于 /health 展示，绝不记值）
_loaded = {}


def candidate_paths(explicit=None):
    """返回待尝试的 .env 路径列表（去重、保序，不判断是否存在）。"""
    out = []
    env_file = explicit or os.environ.get('ML_ENV_FILE')
    if env_file:
        out.append(os.path.abspath(os.path.expanduser(env_file)))
    out.append(os.path.join(_REPO_DIR, '.env'))
    out.append(os.path.join(_REPO_DIR, 'agent', '.env'))
    seen, uniq = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def parse(text):
    """解析 .env 文本，返回 {key: value}。非法行静默跳过。"""
    out = {}
    for raw in (text or '').splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[len('export '):].strip()
        if '=' not in line:
            continue
        key, _, val = line.partition('=')
        key = key.strip()
        if not _KEY_RE.match(key):
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
            val = val[1:-1]            # 成对引号：原样保留内部内容
        else:
            for marker in (' #', '\t#'):
                idx = val.find(marker)
                if idx >= 0:
                    val = val[:idx].rstrip()
                    break
        out[key] = val
    return out


def load(paths=None, override=False, quiet=True, skip_empty=True):
    """
    加载 .env 到 os.environ。返回本次**实际注入**的 {key: value}。

    override=False 时，已存在于 os.environ 的键一律不覆盖（推荐默认）。
    skip_empty=True 时，值解析为空的键视为“未配置”，不注入 ——
    否则 `ANTHROPIC_API_KEY=` 会变成“存在但为空”，容易让调用方误判
    成“已经配了凭据”，也会干扰 SDK 自己的凭据探测。
    """
    loaded = {}
    for p in (paths or candidate_paths()):
        if not os.path.isfile(p):
            continue
        try:
            with io.open(p, 'r', encoding='utf-8') as f:
                data = parse(f.read())
        except (IOError, OSError, UnicodeDecodeError) as e:
            if not quiet:
                print('[agent.dotenv] 读取 %s 失败: %r' % (p, e))
            continue
        for k, v in data.items():
            if skip_empty and not v:
                continue
            if override or k not in os.environ:
                os.environ[k] = v
                loaded[k] = v
        if not quiet:
            print('[agent.dotenv] 已加载 %s（注入 %d 项）' % (p, len(loaded)))
    _loaded.update(loaded)
    return loaded


def loaded_keys():
    """本次进程内由 .env 注入的键名（排序后返回，供 /health 诊断）。"""
    return sorted(_loaded)


def reset():
    """仅供测试：清空“已加载键”记录（不还原 os.environ）。"""
    _loaded.clear()
