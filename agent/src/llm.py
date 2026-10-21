#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
可选的大模型增强层（多服务商；仅用标准库 HTTP）

设计红线（接口规范第 2.2 节 + 迭代一需求"不得编造结果"）：
  1. LLM 只用于【理解用户表述】和【解释已经真实执行的结果】，
     绝不生成或修改任何评分、条数、版本、时间边界。
  2. 传给模型的是结果 JSON 的只读摘录 + 强制"只引用给定数字"的系统提示。
  3. 本层完全可选：未配置凭据、或调用失败时，所有函数返回 None，
     调用方回退到确定性模板路径。
     —— 没有 API Key 的环境（如本项目评测机）中，系统功能不受影响，
     这正是把模板路径设计为主路径的原因。

支持的服务商（两种协议，均用标准库 urllib 实现，**无需安装任何包**）：

  anthropic 协议  POST {base}/v1/messages
    · Anthropic Claude（官方或经 ANTHROPIC_BASE_URL 中转）

  openai 协议     POST {base}/chat/completions
    · OpenAI、DeepSeek、通义千问(DashScope 兼容模式)、Moonshot、
      智谱 GLM、SiliconFlow、火山方舟、Ollama / vLLM / OneAPI 等自建网关
      —— 只要是 OpenAI 兼容接口即可，填 base_url + 模型名即可接入

凭据与配置（优先级：真实环境变量 > .env > 代码默认值）：

  ML_LLM_PROVIDER      服务商，见下方 PROVIDERS；不填则按已配凭据自动判断
  ML_LLM_API_KEY       统一凭据（优先于各服务商专用变量）
  ML_LLM_BASE_URL      接口地址（不填则用该服务商的默认地址）
  ML_LLM_MODEL         模型名（不填则用该服务商的建议默认值）
  ML_LLM_TIMEOUT       单次调用超时秒数（默认 60）
  ML_LLM_MAX_RETRIES   网络类失败的重试次数（默认 1）
  ML_LLM_TEMPERATURE   可选，采样温度；不设则不下发该字段（兼容推理类模型）
  ML_LLM_DISABLE=1     强制关闭，即使配了凭据

  兼容旧变量：ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN /
             ANTHROPIC_BASE_URL / OPENAI_API_KEY

Prompt 全文见 agent/config/prompts/，便于团队审查与迭代（交付物之一）。
"""

import json
import os
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

# 必须在读取任何凭据/模型相关变量之前加载 .env，
# 否则模块级默认值会被定死。
import dotenv                      # noqa: E402
dotenv.load()

PROMPT_DIR = os.path.join(os.path.dirname(_SRC_DIR), 'config', 'prompts')

#: 标准库 HTTP 通路恒可用；是否真正启用由 enabled() 判断。
#: （保留该常量是为了兼容 parser.py 里 `and llm.AVAILABLE` 的写法）
AVAILABLE = True
SDK_ERROR = None                   # 历史字段，保留以免调用方 KeyError

# 服务商 → (协议, 默认 base_url, 建议默认模型)
PROVIDERS = {
    'anthropic': ('anthropic', 'https://api.anthropic.com', 'claude-opus-5'),
    'openai':    ('openai', 'https://api.openai.com/v1', 'gpt-4o-mini'),
    'deepseek':  ('openai', 'https://api.deepseek.com/v1', 'deepseek-chat'),
    'qwen':      ('openai',
                  'https://dashscope.aliyuncs.com/compatible-mode/v1', 'qwen-plus'),
    'moonshot':  ('openai', 'https://api.moonshot.cn/v1', 'moonshot-v1-8k'),
    'zhipu':     ('openai', 'https://open.bigmodel.cn/api/paas/v4', 'glm-4-plus'),
    'ollama':    ('openai', 'http://127.0.0.1:11434/v1', 'qwen2.5'),
}

#: 各服务商的凭据环境变量（按顺序取第一个非空的）
_CRED_VARS = {
    'anthropic': ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN'),
    'openai':    ('OPENAI_API_KEY',),
}
_UNIFIED_KEY = 'ML_LLM_API_KEY'
_DEFAULT_TIMEOUT = 60.0
_DEFAULT_MAX_RETRIES = 1


def _env(name, default=None):
    v = os.environ.get(name)
    return v if (v is not None and str(v).strip() != '') else default


def _first_env(names):
    for n in names:
        v = _env(n)
        if v:
            return n, v
    return None, None


def disabled_by_flag():
    return str(os.environ.get('ML_LLM_DISABLE', '')).strip().lower() in (
        '1', 'true', 'yes', 'on')


def _auto_provider():
    """未显式指定时，按已配置的凭据推断服务商。"""
    if _first_env(_CRED_VARS['anthropic'] + (_UNIFIED_KEY,))[1]:
        # 只有 ANTHROPIC_* 时才判为 anthropic
        name, _ = _first_env(_CRED_VARS['anthropic'])
        if name or _env(_UNIFIED_KEY):
            if name:
                return 'anthropic'
    if _first_env(_CRED_VARS['openai'])[1]:
        return 'openai'
    if _env(_UNIFIED_KEY):
        return 'openai'
    return None


def resolve():
    """
    解析当前生效的配置。返回 dict（不含敏感字段的完整回显由 diagnose 控制），
    未配置任何凭据时返回 None。
    """
    raw_provider = (_env('ML_LLM_PROVIDER') or '').strip().lower()
    if raw_provider and raw_provider not in PROVIDERS:
        # 认不出的服务商名：不静默回退，直接视为未配置，由 diagnose 说明
        return {'error': '未知服务商 %r（可选: %s）'
                         % (raw_provider, ', '.join(sorted(PROVIDERS)))}
    provider = raw_provider or _auto_provider()
    if not provider:
        return None

    protocol, default_base, default_model = PROVIDERS[provider]

    key_var = None
    api_key = _env(_UNIFIED_KEY)
    if api_key:
        key_var = _UNIFIED_KEY
    else:
        cands = _CRED_VARS.get(protocol, ())
        key_var, api_key = _first_env(cands)

    # 本地 Ollama 不要求密钥
    if not api_key and provider == 'ollama':
        api_key = 'ollama'
        key_var = '(本地无需密钥)'

    if not api_key:
        return None

    base_url = (_env('ML_LLM_BASE_URL')
                or (_env('ANTHROPIC_BASE_URL') if protocol == 'anthropic' else None)
                or default_base)
    model = _env('ML_LLM_MODEL') or default_model
    try:
        timeout = float(_env('ML_LLM_TIMEOUT', _DEFAULT_TIMEOUT))
    except ValueError:
        timeout = _DEFAULT_TIMEOUT
    try:
        retries = int(_env('ML_LLM_MAX_RETRIES', _DEFAULT_MAX_RETRIES))
    except ValueError:
        retries = _DEFAULT_MAX_RETRIES
    temp = _env('ML_LLM_TEMPERATURE')
    try:
        temperature = float(temp) if temp is not None else None
    except ValueError:
        temperature = None

    return {'provider': provider, 'protocol': protocol,
            'base_url': base_url.rstrip('/'), 'api_key': api_key,
            'key_var': key_var, 'model': model,
            'timeout': timeout, 'max_retries': max(0, retries),
            'temperature': temperature}


def enabled():
    """是否可用（已配置凭据 + 未被显式关闭 + 服务商合法）。"""
    if disabled_by_flag():
        return False
    cfg = resolve()
    return bool(cfg) and 'error' not in cfg


def diagnose():
    """
    配置诊断：暴露"有没有/是什么"，**绝不回显密钥内容**。
    供 GET /health 与排障使用。
    """
    cfg = resolve()
    out = {'enabled': False, 'disabled_by_flag': disabled_by_flag(),
           'supported_providers': sorted(PROVIDERS),
           'env_file_keys': dotenv.loaded_keys()}
    if cfg is None:
        out['reason'] = '未配置任何凭据'
        return out
    if 'error' in cfg:
        out['reason'] = cfg['error']
        return out
    key = cfg['api_key']
    out.update({
        'enabled': not out['disabled_by_flag'],
        'provider': cfg['provider'],
        'protocol': cfg['protocol'],
        'model': cfg['model'],
        'base_url_host': urlsplit(cfg['base_url']).netloc or cfg['base_url'],
        'credential_var': cfg['key_var'],
        'credential_masked': (key[:6] + '***' + key[-4:])
                             if len(key) > 12 else '***',
        'timeout_s': cfg['timeout'],
        'max_retries': cfg['max_retries'],
        'temperature': cfg['temperature'],
    })
    if out['disabled_by_flag']:
        out['reason'] = 'ML_LLM_DISABLE 已开启'
    return out


def _system(name):
    with open(os.path.join(PROMPT_DIR, name), 'r', encoding='utf-8') as f:
        return f.read()


def _post_json(url, body, headers, timeout):
    """发 POST 并解析 JSON。失败抛 RuntimeError（消息里不回显密钥）。"""
    data = json.dumps(body, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        detail = ''
        try:
            detail = e.read().decode('utf-8', 'replace')[:300]
        except Exception:                     # pragma: no cover
            pass
        raise RuntimeError('HTTP %s %s' % (e.code, detail))
    except urllib.error.URLError as e:
        raise RuntimeError('网络错误 %s' % (getattr(e, 'reason', e),))
    except Exception as e:                    # 超时等
        raise RuntimeError('%s: %s' % (type(e).__name__, e))
    try:
        return json.loads(raw)
    except ValueError:
        raise RuntimeError('响应不是 JSON: %s' % raw[:200])


def _join_v1(base, path):
    """anthropic 协议：base 可能已带 /v1，避免重复拼接。"""
    b = base.rstrip('/')
    if b.endswith('/v1'):
        return b + path
    return b + '/v1' + path


def _call_anthropic(cfg, system_text, user_text, max_tokens):
    url = _join_v1(cfg['base_url'], '/messages')
    body = {'model': cfg['model'], 'max_tokens': max_tokens,
            'system': system_text,
            'messages': [{'role': 'user', 'content': user_text}]}
    if cfg['temperature'] is not None:
        body['temperature'] = cfg['temperature']
    headers = {'content-type': 'application/json',
               'anthropic-version': '2023-06-01',
               'x-api-key': cfg['api_key']}
    data = _post_json(url, body, headers, cfg['timeout'])
    if data.get('stop_reason') not in (None, 'end_turn', 'max_tokens'):
        return None                        # refusal / pause_turn 等不信任
    for block in data.get('content') or []:
        if block.get('type') == 'text':
            return block.get('text')
    return None


def _call_openai(cfg, system_text, user_text, max_tokens):
    url = cfg['base_url'] + '/chat/completions'
    body = {'model': cfg['model'], 'max_tokens': max_tokens,
            'messages': [{'role': 'system', 'content': system_text},
                         {'role': 'user', 'content': user_text}]}
    if cfg['temperature'] is not None:
        body['temperature'] = cfg['temperature']
    headers = {'content-type': 'application/json'}
    if cfg['api_key'] and cfg['provider'] != 'ollama':
        headers['authorization'] = 'Bearer ' + cfg['api_key']
    data = _post_json(url, body, headers, cfg['timeout'])
    choices = data.get('choices') or []
    if not choices:
        return None
    if choices[0].get('finish_reason') not in (None, 'stop', 'length'):
        return None
    return (choices[0].get('message') or {}).get('content')


def _call(system_text, user_text, effort=None, max_tokens=4096):
    """
    统一调用入口。返回文本；任何失败返回 None（调用方回退模板）。
    effort 参数仅为兼容旧调用点保留，不再下发（各服务商支持不一致）。
    """
    cfg = resolve()
    if not cfg or 'error' in cfg or disabled_by_flag():
        return None
    try:
        if cfg['protocol'] == 'anthropic':
            fn = _call_anthropic
        else:
            fn = _call_openai
        attempts = cfg['max_retries'] + 1
        last = None
        for i in range(attempts):
            try:
                return fn(cfg, system_text, user_text, max_tokens)
            except RuntimeError as e:
                last = e
                # 4xx 属于配置/鉴权问题，重试无意义
                if 'HTTP 4' in str(e):
                    break
        print('[agent.llm] 调用失败（%s），追问将返回“不可用”提示: %s'
              % (cfg['provider'], last))
        return None
    except Exception as e:                  # 兜底：绝不影响主流程
        print('[agent.llm] 调用异常，追问将返回“不可用”提示: %s' % e)
        return None


#: 路由类别白名单（与 registry.CATEGORIES 一致，避免循环 import 故在此重复）
ROUTE_CATEGORIES = ('clustering', 'classification', 'dimensionality_reduction')


def classify_category(text, attempts=2):
    """
    意图路由：判断这句话涉及哪些分析类别。
    返回 {'categories': [...], 'confidence': str} 或 None。

    None 表示"无法判断"（模型不可用 / 调用失败 / 输出不合规），
    调用方应据此跳过类别一致性检查，**不得**用规则猜一个类别顶替。
    """
    if not enabled():
        return None
    system_text = _system('system_route.txt')
    for _ in range(max(1, attempts)):
        raw = _call(system_text, text or '', max_tokens=200)
        if not raw:
            continue
        start, end = raw.find('{'), raw.rfind('}')
        if start < 0 or end <= start:
            continue
        try:
            obj = json.loads(raw[start:end + 1])
        except ValueError:
            continue
        cats = obj.get('categories')
        if not isinstance(cats, list):
            continue
        # 过滤掉白名单以外的值；模型可能给出同义写法
        clean = [c for c in cats if c in ROUTE_CATEGORIES]
        return {'categories': clean,
                'confidence': obj.get('confidence') or 'low'}
    return None


def classify_intent(prompt):
    """
    兜底意图分类：判断用户是"完整流程"还是"仅评估"。
    返回 {'do_clean': bool} 或 None（失败即回退默认流程）。
    """
    if not enabled():
        return None
    text = _call(_system('system_intent.txt'), prompt or '', max_tokens=512)
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


def answer_question(question, evidence, max_tokens=1024):
    """
    基于结果证据生成回答。
    evidence 只含已经真实执行产生的数字；返回 None 表示调用失败。

    max_tokens 默认 1024：系统提示已要求回答 <=300 字，给太大反而会让
    模型长篇发挥、显著拉长响应时间。
    """
    if not enabled():
        return None
    user = '【任务结果 JSON（真实执行产物，唯一数字来源）】\n%s\n\n【用户问题】\n%s' % (
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True), question)
    return _call(_system('system_explain.txt'), user, max_tokens=max_tokens)
