#!/usr/bin/env bash
# =============================================================================
# 最小验证：只跑一个 Hadoop Streaming 作业（freshness-ratings）
# 用于快速确认 Hadoop / Streaming / 数据 / 路径 都正常。
# 在 WSL 中执行：bash scripts_setup/test_one_job.sh
# =============================================================================
set -euo pipefail

export JAVA_HOME="${JAVA_HOME:-$HOME/opt/jdk-17.0.20.1+1}"
export HADOOP_HOME="${HADOOP_HOME:-$HOME/opt/hadoop}"
export HADOOP_CONF_DIR="$HADOOP_HOME/etc/hadoop"
export PATH="$HADOOP_HOME/bin:$HADOOP_HOME/sbin:$PATH"
export ML_STREAMING_JAR="$HADOOP_HOME/share/hadoop/tools/lib/hadoop-streaming-3.4.1.jar"

REPO="${REPO:-$HOME/movielens-data-agent}"
export ML_DATA_DIR="${ML_DATA_DIR:-$REPO/data/ml-1m-v2}"
export ML_WORK_DIR="${ML_WORK_DIR:-$HOME/mlqc-test/work}"
export ML_OUT_DIR="${ML_OUT_DIR:-$HOME/mlqc-test/out}"

echo "python3   = $(which python3)"
echo "hadoop    = $(which hadoop)"
echo "jar       = $ML_STREAMING_JAR"
echo "data      = $ML_DATA_DIR"
echo "--------------------------------------------------"

cd "$REPO"
bash hadoop/scripts/run_check.sh freshness-ratings

echo "--------------------------------------------------"
echo "输出:"
cat "$ML_OUT_DIR/freshness-ratings.txt"
