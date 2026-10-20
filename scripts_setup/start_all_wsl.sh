#!/usr/bin/env bash
# =============================================================================
# 在 WSL 中一键启动三件套服务
#   Hadoop(8080)  ->  Agent(8090)  ->  前端(8000)
# 日志写入 ~/movielens-data-agent/logs/
# 用法（在 WSL 中）：bash scripts_setup/start_all_wsl.sh
# 停止：bash scripts_setup/stop_all_wsl.sh
# =============================================================================
set -euo pipefail

# ---- 解析可用的 JDK：优先已设置的 JAVA_HOME，否则按顺序探测 ----
if [ -z "${JAVA_HOME:-}" ] || [ ! -d "${JAVA_HOME:-/nonexistent}" ]; then
  for _jdk in "$HOME/opt/jdk-17.0.20.1+1" "/usr/lib/jvm/java-11-openjdk-amd64" "/usr/lib/jvm/java-1.11.0-openjdk-amd64" "/usr/lib/jvm/openjdk-11"; do
    if [ -d "$_jdk" ] && [ -x "$_jdk/bin/java" ]; then JAVA_HOME="$_jdk"; break; fi
  done
fi
if [ -z "${JAVA_HOME:-}" ] || [ ! -x "${JAVA_HOME}/bin/java" ]; then
  echo "[x] 找不到可用的 JDK，请安装或设置 JAVA_HOME" >&2
  exit 1
fi
export JAVA_HOME

export HADOOP_HOME="${HADOOP_HOME:-$HOME/opt/hadoop}"
export HADOOP_CONF_DIR="$HADOOP_HOME/etc/hadoop"
export PATH="$JAVA_HOME/bin:$HADOOP_HOME/bin:$HADOOP_HOME/sbin:$PATH"
export ML_STREAMING_JAR="$HADOOP_HOME/share/hadoop/tools/lib/hadoop-streaming-3.4.1.jar"

# 自动定位仓库根：本脚本位于 <repo>/scripts_setup/ 下
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# 原始数据目录（Hadoop 输入）。默认用仓库内的 data/，若不存在回退到 ~/data/ml-1m-v2
if [ -d "$REPO/data/ml-1m-v2" ]; then
DATA_DIR="$REPO/data/ml-1m-v2"
  else
  DATA_DIR="${ML_DATA_DIR:-$HOME/data/ml-1m-v2}"
  fi
LOGS="$REPO/logs"
mkdir -p "$LOGS" "$HOME/mlqc-server-work" "$HOME/mlqc-server-out"

echo "== 停止可能在运行的旧服务 =="
pkill -f 'hadoop/src/server.py' 2>/dev/null || true
pkill -f 'agent/src/api.py' 2>/dev/null || true
pkill -f 'frontend/src/serve.py' 2>/dev/null || true
sleep 1

cd "$REPO"

echo "== 启动 Hadoop 服务 (8080) =="
nohup python3 hadoop/src/server.py --port 8080 --mode hadoop \
  --data-dir "$DATA_DIR" --work-dir "$HOME/mlqc-server-work" \
  > "$LOGS/hadoop.log" 2>&1 &
echo "   pid=$!"

sleep 2

echo "== 启动 Agent 服务 (8090) =="
nohup python3 agent/src/api.py --port 8090 \
  --hadoop-url http://127.0.0.1:8080 \
  > "$LOGS/agent.log" 2>&1 &
echo "   pid=$!"

sleep 2

echo "== 启动前端服务 (8000) =="
nohup python3 frontend/src/serve.py --port 8000 \
  --agent-url http://127.0.0.1:8090 \
  > "$LOGS/frontend.log" 2>&1 &
echo "   pid=$!"

sleep 3

echo "== 健康检查 =="
for pair in "Hadoop:8080/health" "Agent:8090/health" "前端:8000/health"; do
  name="${pair%%:*}"; path="${pair#*:}"
  if curl -s --max-time 5 "http://127.0.0.1:$path" >/dev/null 2>&1; then
    echo "   $name  OK"
  else
    echo "   $name  未就绪（查看 $LOGS/${name,}.log）"
  fi
done

echo
echo "服务已启动。浏览器访问： http://localhost:8000"
echo "日志目录： $LOGS"

