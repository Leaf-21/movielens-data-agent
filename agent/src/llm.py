#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
可选的大模型增强层（Claude API）

设计红线（接口规范第 2.2 节 + 迭代一需求"不得编造结果"）：
  1. LLM 只用于【理解用户表述】和【解释已经真实执行的结果】，
     绝不生成或修改任何评分、条数、版本、时间边界。
  2. 传给模型的是结果 JSON 的只读摘录 + 强制"只引用给定数字"的系统提示。
  3. 本层完全可选：未安装 anthropic 包、或未配置任何凭据、或调用失败时，
     所有函数返回 None，调用方回退到确定性模板路径。
     —— 没有 API Key 的环境（如本项目评测机）中，系统功能不受影响，
     这正是把模板路径设计为主路径的原因。

Prompt 全文见 agent/config/prompts/，便于团队审查与迭代（交付物之一）。
"""

import json
import os

AVAILABLE = False
try:
    import anthropic
    AVAILABLE = True
except ImportError:
    anthropic = None

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPT_DIR = os.path.join(os.path.dirname(_SRC_DIR), 'config', 'prompts')

# 模型与采样参数均可用环境变量覆盖，不改代码即可切换。
# 默认使用 Claude Opus 5（Anthropic 当前主力模型）。
MODEL = os.environ.get('ML_LLM_MODEL', 'claude-opus-5')
TIMEOUT = float(os.environ.get('ML_LLM_TIMEOUT', '60'))

_client = None


def _get_client():
    """惰性创建客户端；凭据由 SDK 按环境自动解析（ANTHROPIC_API_KEY 等）。"""
    global _client, AVAILABLE
    if not AVAILABLE:
        return None
    if _client is None:
        try:
            _client = anthropic.Anthropic(timeout=TIMEOUT, max_retries=1)
        except Exception as e:
            print('[agent.llm] 无法初始化 Anthropic 客户端: %r（回退到模板路径）' % e)
            AVAILABLE = False
            return None
    return _client


def enabled():
    """是否可用（安装 + 凭据存在）。凭据缺失要到真正调用时才报错，故只做包检查。"""
    return AVAILABLE and (os.environ.get('ANTHROPIC_API_KEY')
                          or os.environ.get('ANTHROPIC_AUTH_TOKEN'))


def _system(name):
    with open(os.path.join(PROMPT_DIR, name), 'r', encoding='utf-8') as f:
        return f.read()


def _extract_text(response):
    for block in response.content:
        if block.type == 'text':
            return block.text
    return None


def _call(system_text, user_text, effort='low', max_tokens=4096):
    client = _get_client()
    if client is None:
        return None
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            system=system_text,
            output_config={'effort': effort},
            messages=[{'role': 'user', 'content': user_text}],
        )
    except Exception as e:
        # 任何 API 错误（网络 / 鉴权 / 限流）都不允许影响主流程
        print('[agent.llm] 调用失败，回退到模板路径: %s' % e)
        return None
    if resp.stop_reason not in ('end_turn', 'max_tokens'):
        # refusal / pause_turn 等状态下不信任输出
        return None
    return _extract_text(resp)


def classify_intent(prompt):
    """
    兜底意图分类：判断用户是"完整流程"还是"仅评估"。
    返回 {'do_clean': bool} 或 None（失败即回退默认流程）。
    """
    if not enabled():
        return None
    text = _call(_system('system_intent.txt'), prompt or '', effort='low',
                 max_tokens=512)
    if not text:
        return None
    # 模型可能带围栏或说明文字：取第一个 JSON 对象
    start, end = text.find('{'), text.rfind('}')
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(text[start:end + 1])
    except ValueError:
        return None
    if 'do_clean' not in obj:
        return None
    return {'do_clean': bool(obj['do_clean'])}


def answer_question(question, evidence):
    """
    基于结果证据回答用户追问。
    evidence 只含已经真实执行产生的数字；返回 None 表示应回退模板。
    """
    if not enabled():
        return None
    user = '【任务结果 JSON（真实执行产物，唯一数字来源）】\n%s\n\n【用户问题】\n%s' % (
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True), question)
    return _call(_system('system_explain.txt'), user, effort='medium',
                 max_tokens=4096)
