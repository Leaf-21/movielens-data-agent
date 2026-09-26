#!/usr/bin/env bash
# =============================================================================
#  数据清洗作业运行脚本
#
#  用法：
#    bash hadoop/scripts/run_clean.sh <表名>
#      <表名> = ratings | movies | users
#
#  作用：
#    对指定表执行 Hadoop Streaming 清洗作业，输出带处置标签的记录。
#
#  输出（写入 $ML_OUT_DIR，默认 $HOME/mlqc-out-clean）：
#    <表名>.tagged        形如 <标签>\t<记录原文>，标签为 clean/fixed/isolated
#    <表名>.counts        形如 <指标名>\t<数值>，来自 reducer 的 ###COUNTS### 行
#
#  ⚠️ 为什么不在 Hadoop 内部分流到不同目录
#  ---------------------------------------------------------------------------
#  最初的实现使用 Java 的 MultipleOutputs。实测证明这条路在 Streaming 下不通：
#    · from org.apache.hadoop.mapred.lib import MultipleOutputs
#      -> ModuleNotFoundError: No module named 'org'
#      原因：Hadoop Streaming 用标准 CPython 而非 Jython，无法访问 JVM 内的类。
#    · 备选的 -outputformat SuffixMultipleTextOutputFormat 在 Hadoop 3.4.1 中
#      不存在（class not found）。
#
#  因此改为：reducer 只输出「标签 + 记录」，由 driver 读取后按标签分流。
#  本脚本只负责跑作业并落地带标签的输出，分流由 driver 完成。
#
#  文件系统模式同 run_check.sh，由 ML_FS 控制（file | hdfs）。
# =============================================================================
set -euo pipefail

TABLE="${1:-}"
case "$TABLE" in
  ratings|movies|users) ;;
  *) echo "用法: bash hadoop/scripts/run_clean.sh <ratings|movies|users>" >&2; exit 2 ;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HADOOP_DIR="$(dirname "$SCRIPT_DIR")"
SRC="$HADOOP_DIR/src"
CLEAN_DIR_SRC="$SRC/clean"

DATA_DIR="${ML_DATA_DIR:-$HOME/data/ml-1m}"
# after 阶段可对清洗后数据再清洗（理论上不需要，但保持一致性）
INPUT_DIR="${ML_INPUT_DIR:-$DATA_DIR}"
WORK_DIR="${ML_WORK_DIR:-$HOME/mlqc-work-clean}"
OUT_DIR="${ML_OUT_DIR:-$HOME/mlqc-out-clean}"
STREAMING_JAR="${ML_STREAMING_JAR:-${HADOOP_HOME:-/usr/local/hadoop}/share/hadoop/tools/lib/hadoop-streaming-3.4.1.jar}"
ML_FS="${ML_FS:-file}"

[ -f "$INPUT_DIR/$TABLE.dat" ] || {
  echo "[run_clean] 找不到输入数据: $INPUT_DIR/$TABLE.dat" >&2; exit 1; }
[ -f "$STREAMING_JAR" ] || {
  echo "[run_clean] 找不到 Hadoop Streaming JAR: $STREAMING_JAR" >&2; exit 1; }
case "$ML_FS" in
  file|hdfs) ;;
  *) echo "[run_clean] ML_FS 必须是 file 或 hdfs，得到: $ML_FS" >&2; exit 2 ;;
esac

mkdir -p "$OUT_DIR"

# ---------------------------------------------------------------------------
# 文件系统抽象（与 run_check.sh 保持一致）
# ---------------------------------------------------------------------------
_fs_mkdir() { if [ "$ML_FS" = hdfs ]; then hdfs dfs -mkdir -p "$1"; else mkdir -p "$1"; fi; }
_fs_rm() {
  if [ "$ML_FS" = hdfs ]; then
    hdfs dfs -rm -r -f -skipTrash "$1" >/dev/null 2>&1 || true
  else
    rm -rf "$1"
  fi
}
_fs_put() { if [ "$ML_FS" = hdfs ]; then hdfs dfs -put -f "$1" "$2"; else cp -f "$1" "$2"; fi; }
_fs_getmerge() {
  local out="$1" dest="$2"
  if [ "$ML_FS" = hdfs ]; then
    hdfs dfs -getmerge "$out" "$dest"
  else
    : > "$dest"
    local f
    for f in "$out"/part-*; do
      [ -e "$f" ] || continue
      cat "$f" >> "$dest"
    done
  fi
}

# ---------------------------------------------------------------------------
# 准备输入
# ---------------------------------------------------------------------------
_fs_rm "$WORK_DIR"
_fs_mkdir "$WORK_DIR/input"
_fs_mkdir "$WORK_DIR/out"
_fs_put "$INPUT_DIR/$TABLE.dat" "$WORK_DIR/input/$TABLE.dat"

# ---------------------------------------------------------------------------
# 公共参数
# ---------------------------------------------------------------------------
RULES_FILE="$HADOOP_DIR/config/rules.json"
[ -f "$RULES_FILE" ] || { echo "[run_clean] 找不到规则文件: $RULES_FILE" >&2; exit 1; }

common_file_args=(
  -file "$SRC/common/ml_common.py"
  -file "$RULES_FILE"
  -file "$CLEAN_DIR_SRC/mapper.py"
  -file "$CLEAN_DIR_SRC/reducer.py"
)
common_env_args=(
  -cmdenv ML_RULES=rules.json
  -cmdenv ML_CLEAN_TABLE="$TABLE"
)

OUT="$WORK_DIR/out/$TABLE"
_fs_rm "$OUT"

echo "[run_clean] 清洗表: $TABLE   文件系统: $ML_FS"
echo "[run_clean] 输入: $INPUT_DIR/$TABLE.dat"

hadoop jar "$STREAMING_JAR" \
  -D mapreduce.job.name="mlclean-$TABLE" \
  -D mapreduce.job.reduces=1 \
  "${common_env_args[@]}" \
  -input "$WORK_DIR/input/$TABLE.dat" \
  -output "$OUT" \
  -mapper "python3 mapper.py" \
  -reducer "python3 reducer.py" \
  "${common_file_args[@]}"

# ---------------------------------------------------------------------------
# 合并作业输出目录下的所有 part-* 到一个文件
# ---------------------------------------------------------------------------
MERGED="$OUT_DIR/$TABLE.tagged"
_fs_getmerge "$OUT" "$MERGED"

if [ ! -s "$MERGED" ]; then
  echo "[run_clean] 作业输出为空，判定为失败" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# 摘出 ###COUNTS### 统计行，剩余部分为带标签数据
#
# ⚠️ 这里必须用 awk，不能用 grep。
#    原因：输出含 ISO-8859-1 特殊字符（如 movies.dat 里的 Misérables），
#    grep 会把这类文件判定为「二进制文件」并改变行为：
#      · `grep -q` 与 `grep -c` 的结果不一致
#      · `grep -v '^###COUNTS###'` 会丢弃部分数据 —— 实测 movies 因此
#        从 3883 行变成 3833 行，恰好丢掉 50 条含特殊字符的记录
#    awk 按字节处理，不受 locale 与二进制判定影响。
#    实测对比：grep -v 得 3833 行，awk 得 3883 行（正确）。
# ---------------------------------------------------------------------------
COUNTS="$OUT_DIR/$TABLE.counts"
awk -F'\t' '/^###COUNTS###/ {print $2 "\t" $3}' "$MERGED" > "$COUNTS"

if [ ! -s "$COUNTS" ]; then
  echo "[run_clean] 输出中找不到 ###COUNTS### 统计行，作业结果不可信" >&2
  exit 1
fi

TMP="$MERGED.tmp"
awk '!/^###COUNTS###/' "$MERGED" > "$TMP"
mv "$TMP" "$MERGED"

# 校验：数据行数必须等于 total_count
DATA_LINES=$(wc -l < "$MERGED")
TOTAL_COUNT=$(awk -F'\t' '$1=="total_count"{print $2}' "$COUNTS")
if [ "$DATA_LINES" != "$TOTAL_COUNT" ]; then
  echo "[run_clean] 数据行数($DATA_LINES) 与 total_count($TOTAL_COUNT) 不一致，判定为失败" >&2
  echo "  提示：若差异出现在含非 ASCII 字符的表（如 movies），" >&2
  echo "        请检查是否用了 grep 处理 ISO-8859-1 数据 —— grep 会按二进制处理并丢行。" >&2
  exit 1
fi

if [ ! -s "$MERGED" ]; then
  echo "[run_clean] 清洗输出为空，判定为失败" >&2
  exit 1
fi

echo "[run_clean] 完成: $TABLE"
echo "[run_clean]   数据: $MERGED ($DATA_LINES 行)"
echo "[run_clean]   统计: $COUNTS"
