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
