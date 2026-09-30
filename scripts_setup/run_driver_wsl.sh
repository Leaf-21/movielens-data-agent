#!/usr/bin/env bash
# =============================================================================
# 在 WSL 中运行成员A的 driver（完整流程）
#   - 载入 Hadoop 环境变量
#   - 工作目录放 /tmp（WSL 内，避免 /mnt/d 的权限/性能问题）
#   - 可通过环境变量覆盖：STAGE / MODE / TASK_ID / DATA_DIR / REPO
# =============================================================================
set -euo pipefail

export JAVA_HOME="${JAVA_HOME:-/usr/lib/jvm/java-11-openjdk-amd64}"
export HADOOP_HOME="${HADOOP_HOME:-$HOME/opt/hadoop}"
export HADOOP_CONF_DIR="$HADOOP_HOME/etc/hadoop"
export PATH="$HADOOP_HOME/bin:$HADOOP_HOME/sbin:$PATH"
export ML_STREAMING_JAR="$HADOOP_HOME/share/hadoop/tools/lib/hadoop-streaming-3.4.1.jar"

REPO="${REPO:-$HOME/movielens-data-agent}"
STAGE="${STAGE:-all}"
MODE="${MODE:-hadoop}"
TASK_ID="${TASK_ID:-task_demo_001}"
DATA_DIR="${DATA_DIR:-$HOME/data/ml-1m-v2}"
WORK_DIR="${WORK_DIR:-$HOME/mlqc-work-driver}"

echo "=================================================="
echo " 运行 driver"
echo "   REPO     = $REPO"
echo "   STAGE    = $STAGE"
echo "   MODE     = $MODE"
echo "   TASK_ID  = $TASK_ID"
echo "   DATA_DIR = $DATA_DIR"
echo "   STREAMING= $ML_STREAMING_JAR"
echo "=================================================="

cd "$REPO"
python3 hadoop/src/driver.py \
  --mode "$MODE" \
  --stage "$STAGE" \
  --task-id "$TASK_ID" \
  --data-dir "$DATA_DIR" \
  --work-dir "$WORK_DIR"
