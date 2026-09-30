#!/usr/bin/env bash
# =============================================================================
# 在 WSL (Ubuntu) 中安装 Hadoop 3.4.1，并配置本项目运行所需的环境
#   - 下载解压到 ~/opt/hadoop
#   - 写 ~/.bashrc 的 HADOOP_HOME / JAVA_HOME / PATH
#   - 拷数据到 ~/data/ml-1m-v2
# 幂等：可重复执行。
# =============================================================================
set -euo pipefail

HADOOP_VERSION=3.4.1
HADOOP_MIRROR="https://repo.huaweicloud.com/apache/hadoop/common/hadoop-${HADOOP_VERSION}/hadoop-${HADOOP_VERSION}.tar.gz"
OPT_DIR="$HOME/opt"
HADOOP_HOME="$OPT_DIR/hadoop"
DATA_DIR="$HOME/data/ml-1m-v2"
DATA_ZIP="/mnt/d/大三上/大数据分析/lab2/movielens-data-agent/../ml-1m.zip"  # 占位，稍后由参数覆盖

echo "=================================================="
echo " 安装 Hadoop ${HADOOP_VERSION} 到 $HADOOP_HOME"
echo "=================================================="

mkdir -p "$OPT_DIR"

# ---- 1. 下载 ----
if [ ! -d "$HADOOP_HOME" ]; then
  if [ ! -f "$OPT_DIR/hadoop-${HADOOP_VERSION}.tar.gz" ]; then
    echo "[1/4] 下载 Hadoop ${HADOOP_VERSION} ..."
    wget -q --show-progress -O "$OPT_DIR/hadoop-${HADOOP_VERSION}.tar.gz" "$HADOOP_MIRROR"
  else
    echo "[1/4] 已存在安装包，跳过下载"
  fi
  echo "[2/4] 解压 ..."
  tar -xzf "$OPT_DIR/hadoop-${HADOOP_VERSION}.tar.gz" -C "$OPT_DIR"
  mv "$OPT_DIR/hadoop-${HADOOP_VERSION}" "$HADOOP_HOME"
else
  echo "[1-2/4] $HADOOP_HOME 已存在，跳过下载解压"
fi

# ---- 3. 校验 streaming jar ----
STREAMING_JAR="$HADOOP_HOME/share/hadoop/tools/lib/hadoop-streaming-${HADOOP_VERSION}.jar"
if [ ! -f "$STREAMING_JAR" ]; then
  echo "[错误] 找不到 $STREAMING_JAR" >&2
  exit 1
fi
echo "[3/4] Streaming jar: $STREAMING_JAR  ✓"

# ---- 4. 配置 ~/.bashrc ----
JAVA_HOME="/usr/lib/jvm/java-11-openjdk-amd64"
MARK_BEGIN="# >>> movielens-agent hadoop >>>"
MARK_END="# <<< movielens-agent hadoop <<<"
if ! grep -q "$MARK_BEGIN" "$HOME/.bashrc" 2>/dev/null; then
  cat >> "$HOME/.bashrc" <<EOF

$MARK_BEGIN
export JAVA_HOME=$JAVA_HOME
export HADOOP_HOME=$HADOOP_HOME
export HADOOP_CONF_DIR=\$HADOOP_HOME/etc/hadoop
export PATH=\$HADOOP_HOME/bin:\$HADOOP_HOME/sbin:\$PATH
export ML_STREAMING_JAR=$STREAMING_JAR
$MARK_END
EOF
  echo "[4/4] 已写入 ~/.bashrc 环境变量 ✓"
else
  echo "[4/4] ~/.bashrc 已配置过，跳过 ✓"
fi

echo
echo "安装完成。"
echo "  HADOOP_HOME = $HADOOP_HOME"
echo "  Streaming   = $STREAMING_JAR"
echo "  JAVA_HOME   = $JAVA_HOME"
