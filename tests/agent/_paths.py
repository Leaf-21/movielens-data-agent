# -*- coding: utf-8 -*-
"""测试路径引导：把 agent/src 与 agent/tools 加入 sys.path。"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(os.path.dirname(_HERE))
AGENT_SRC = os.path.join(REPO_DIR, 'agent', 'src')
AGENT_TOOLS = os.path.join(REPO_DIR, 'agent', 'tools')

for p in (AGENT_SRC, AGENT_TOOLS):
    if p not in sys.path:
        sys.path.insert(0, p)

# 单元测试一律不访问真实大模型：
#   · 结果解释已改为「大模型主路径」，若不关闭，测试会真的发出网络请求
#     （单次十几秒、结果不确定，还会因外部限流/欠费而随机失败）；
#   · 需要验证接入层本身的用例（test_llm_env.py）在自己的 patch_env 里
#     清掉这个变量后再注入配置。
os.environ['ML_LLM_DISABLE'] = '1'
