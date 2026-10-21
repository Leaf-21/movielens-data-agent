#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
可选的大模型增强层（Anthropic Claude）

设计红线（接口规范第 2.2 节 + 迭代一需求"不得编造结果"）：
  1. LLM 只用于【理解用户表述】和【解释已经真实执行的结果】，
     绝不生成或修改任何评分、条数、版本、时间边界。
  2. 传给模型的是结果 JSON 的只读摘录 + 强制"只引用给定数字"的系统提示。
  3. 本层完全可选：未安装 anthropic 包、或未配置任何凭据、或调用失败时，
     所有函数返回 None，调用方回退到确定性模板路径。
     —— 没有 API Key 的环境（如本项目评测机）中，系统功能不受影响，
     这正是把模板路径设计为主路径的原因。

凭据与配置（按优先级，越靠前越优先）：
  1. 真实环境变量（`export ANTHROPIC_API_KEY=...`）
  2. 仓库根 `.env` 或 `agent/.env`（模板见 `.env.example`，该文件不进仓库）
  3. 代码内默认值

  ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN   凭据（二选一）
  ANTHROPIC_BASE_URL                         可选，走代理/中转时填
  ML_LLM_MODEL                               模型名（默认 claude-opus-5）
  ML_LLM_TIMEOUT                             单次调用超时秒数（默认 60）
  ML_LLM_MAX_RETRIES                         SDK 层重试次数（默认 1）
  ML_LLM_DISABLE=1                           强制关闭，即使配了凭据

Prompt 全文见 agent/config/prompts/，便于团队审查与迭代（交付物之一）。
"""

import json
import os
import sys

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

# 必须在读取任何 ANTHROPIC_* / ML_LLM_* 之前加载 .env，
# 否则模块级常量会把默认值定死。
import dotenv                      # noqa: E402
dotenv.load()

AVAILABLE = False
SDK_ERROR = None
try:
    import anthropic
    AVAILABLE = True
except ImportError as _e:          # pragma: no cover - 取决于本机是否安装
    anthropic = None
    SDK_ERROR = str(_e)

PROMPT_DIR = os.path.join(os.path.dirname(_SRC_DIR), 'config', 'prompts')

# 模型与采样参数均可用环境变量覆盖，不改代码即可切换。
MODEL = os.environ.get('ML_LLM_MODEL', 'claude-opus-5')
TIMEOUT = float(os.environ.get('ML_LLM_TIMEOUT', '60'))
MAX_RETRIES = int(os.environ.get('ML_LLM_MAX_RETRIES', '1'))
BASE_URL = (os.environ.get('ANTHROPIC_BASE_URL') or '').strip() or None
CRED_VARS = ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN')

# 是否给 SDK 传 output_config={'effort': ...}。若服务端/SDK 不认这个参数，
# 会被自动置 False 并按标准参数重试一次（见 _call），避免一次参数不兼容
# 就让整个增强层永久失效。
_USE_OUTPUT_CONFIG = True

_client = None


def _get_client():
    """惰性创建客户端；凭据由 SDK 按环境自动解析。"""
    global _client, AVAILABLE
    if not AVAILABLE:
        return None
    if _client is None:
        kwargs = {'timeout': TIMEOUT, 'max_retries': MAX_RETRIES}
        if BASE_URL:
            kwargs['base_url'] = BASE_URL
        try:
            _client = anthropic.Anthropic(**kwargs)
        except Exception as e:
            print('[agent.llm] 无法初始化 Anthropic 客户端: %r（回退到模板路径）' % e)
            AVAILABLE = False
            return None
    return _client


def enabled():
    """是否可用（安装 + 凭据存在 + 未被显式关闭）。"""
    if not AVAILABLE:
        return False
    if str(os.environ.get('ML_LLM_DISABLE', '')).strip().lower() in ('1', 'true', 'yes', 'on'):
        return False
    return any(os.environ.get(v) for v in CRED_VARS)


def diagnose():
    """
    配置诊断（只暴露"有没有"，绝不回显密钥内容）。
    供 GET /health 与排障使用。
    """
    cred = next((v for v in CRED_VARS if os.environ.get(v)), None)
    key = os.environ.get(cred) if cred else None
    return {
        'enabled': enabled(),
        'sdk_installed': AVAILABLE,
        'sdk_error': SDK_ERROR,
        'credential_var': cred,
        'credential_masked': (key[:6] + '***' + key[-4:]) if (key and len(key) > 12) else None,
        'model': MODEL,
        'base_url_set': bool(BASE_URL),
        'timeout_s': TIMEOUT,
        'env_file_keys': dotenv.loaded_keys(),
    }


def _system(name):
    with open(os.path.join(PROMPT_DIR, name), 'r', encoding='utf-8') as f:
        return f.read()


def _extract_text(response):
    for block in getattr(response, 'content', []) or []:
        if getattr(block, 'type', None) == 'text':
            return block.text
    return None


def _is_param_rejection(err):
    """判断异常是否属于“请求里带了服务端不认识的参数”。"""
    s = str(err).lower()
    return any(k in s for k in ('output_config', 'effort', 'unexpected keyword',
                                'unrecognized', 'unknown parameter', 'extra fields',
                                'unexpected field'))


def _call(system_text, user_text, effort='low', max_tokens=4096):
    global _USE_OUTPUT_CONFIG
    client = _get_client()
    if client is None:
        return None

    kwargs = {
        'model': MODEL,
        'max_tokens': max_tokens,
        'system': system_text,
        'messages': [{'role': 'user', 'content': user_text}],
    }
    if _USE_OUTPUT_CONFIG:
        kwargs['output_config'] = {'effort': effort}

    try:
        resp = client.messages.create(**kwargs)
    except Exception as e:
        # 参数不兼容：去掉 output_config 重试一次，并永久关闭该参数
        if _USE_OUTPUT_CONFIG and _is_param_rejection(e):
            _USE_OUTPUT_CONFIG = False
            kwargs.pop('output_config', None)
            print('[agent.llm] 服务端不支持 output_config，已改用标准参数重试')
            try:
                resp = client.messages.create(**kwargs)
            except Exception as e2:
                print('[agent.llm] 调用失败，回退到模板路径: %s' % e2)
                return None
        else:
            # 任何 API 错误（网络 / 鉴权 / 限流）都不允许影响主流程
            print('[agent.llm] 调用失败，回退到模板路径: %s' % e)
            return None

    if getattr(resp, 'stop_reason', None) not in ('end_turn', 'max_tokens'):
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
