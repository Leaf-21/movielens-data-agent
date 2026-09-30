#!/usr/bin/env bash
# 停止三件套服务
pkill -f 'hadoop/src/server.py' 2>/dev/null || true
pkill -f 'agent/src/api.py' 2>/dev/null || true
pkill -f 'frontend/src/serve.py' 2>/dev/null || true
sleep 1
echo "已停止三件套服务。"
