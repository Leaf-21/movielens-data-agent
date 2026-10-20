#!/usr/bin/env bash
# =============================================================================
# 只启动成员A的 Hadoop 服务层（8080），不碰 Agent/前端。
# 用于：Agent 与前端已在 Windows 侧运行时，只补 Hadoop 服务。
#
# 与 start_all_wsl.sh 的区别：只启服务层，且显式导出 JAVA_HOME /
# HADOOP_HOME / ML_STREAMING_JAR（start_all_wsl.sh 里若 HOME 未被正确展开，
# 会出现 "找不到 Hadoop Streaming JAR: /share/hadoop/..."）。
#
# 用法（WSL 中）：bash scripts_setup/start_hadoop_only.sh
# 停止：pkill -f 'hadoop/src/server.py'
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

REPO="$HOME/movielens-data-agent"
DATA_DIR="${ML_DATA_DIR:-$HOME/data/ml-1m-v2}"
LOGS="$REPO/logs"
PORT="${ML_HADOOP_PORT:-8080}"

if [ ! -f "$ML_STREAMING_JAR" ]; then
  echo "[x] 找不到 Hadoop Streaming JAR: $ML_STREAMING_JAR" >&2
  echo "    请检查 HADOOP_HOME（当前: $HADOOP_HOME）" >&2
  exit 1
fi
if [ ! -d "$DATA_DIR" ]; then
  echo "[x] 找不到数据目录: $DATA_DIR" >&2
  exit 1
fi

mkdir -p "$LOGS" "$HOME/mlqc-server-work" "$HOME/mlqc-server-out"

echo "== 停止旧 Hadoop 服务 =="
pkill -f 'hadoop/src/server.py' 2>/dev/null || true
sleep 1

cd "$REPO"
echo "== 启动 Hadoop 服务 ($PORT, mode=hadoop) =="
echo "   JAVA_HOME    = $JAVA_HOME"
echo "   HADOOP_HOME  = $HADOOP_HOME"
echo "   STREAMING_JAR= $ML_STREAMING_JAR"
echo "   DATA_DIR     = $DATA_DIR"
nohup python3 hadoop/src/server.py --port "$PORT" --mode hadoop \
  --data-dir "$DATA_DIR" --work-dir "$HOME/mlqc-server-work" \
  > "$LOGS/hadoop.log" 2>&1 &
PID=$!
echo "   pid=$PID"

sleep 3
if curl -s --max-time 5 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
  echo "== 健康检查 OK =="
  curl -s "http://127.0.0.1:$PORT/health"
  echo
else
  echo "== 健康检查失败，日志末尾 ==" >&2
  tail -30 "$LOGS/hadoop.log" >&2
  exit 1
fi

