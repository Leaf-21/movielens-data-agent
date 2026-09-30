#!/usr/bin/env bash
# =============================================================================
# 把项目从 Windows 中文路径同步到 WSL 内的英文路径
#   源：/mnt/d/大三上/大数据分析/lab2/movielens-data-agent
#   目标：~/movielens-data-agent
#
# 为什么需要：Hadoop 无法处理含中文的路径（会变成 ?????），
# 因此 Hadoop 流程必须在纯英文路径下运行。
#
# 用法（在 WSL 里执行）：
#   bash scripts_setup/sync_to_wsl.sh
# =============================================================================
set -euo pipefail

SRC="/mnt/d/大三上/大数据分析/lab2/movielens-data-agent"
DST="$HOME/movielens-data-agent"

mkdir -p "$DST"

rsync -a --delete \
  --exclude='.git/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='hadoop/output/' \
  --exclude='hadoop/_work/' \
  --exclude='.idea/' \
  "$SRC/" "$DST/"

echo "同步完成: $SRC  ->  $DST"
# 保证脚本可执行
chmod +x "$DST"/hadoop/scripts/*.sh 2>/dev/null || true
