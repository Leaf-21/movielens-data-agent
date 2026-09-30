#!/usr/bin/env bash
# =============================================================================
#  Hadoop Streaming 作业运行脚本（数据质量检查阶段）
#
#  用法：
#    bash hadoop/scripts/run_check.sh <作业名>
#
#  作业名：
#    format-ratings | format-movies | format-users   字段级格式检查
#    cross-users | cross-movies                      跨表引用完整性检查
#    group-u-pair | group-u-movie | group-u-user     唯一性检查
#    group-c-movie-multi | group-c-user-attr         一致性（多变体）检查
#
#  ---------------------------------------------------------------------------
#  文件系统模式（重要）
#  ---------------------------------------------------------------------------
#  本机当前处于 Hadoop「本地模式」：core-site.xml 为空，fs.defaultFS = file:///
#  即没有启动 HDFS，MapReduce 由 LocalJobRunner 在本地执行。
#
#  这种模式下真实的 HDFS 命令不可用，因此本脚本通过 ML_FS 变量区分两种模式：
#
#    ML_FS=file  （默认）本地文件系统。数据放在 $WORK_DIR，用普通 shell 命令操作。
#                 Hadoop 仍会真正执行 MapReduce（LocalJobRunner），满足
#                 "清洗与评分实际通过 Hadoop 执行"的要求。
#
#    ML_FS=hdfs  真正的 HDFS。需要先配置 core-site.xml 并启动 NameNode/DataNode。
#                 数据用 hdfs dfs 上传。
#
#  切换到 HDFS 只需： ML_FS=hdfs bash hadoop/scripts/run_check.sh format-movies
#
#  ---------------------------------------------------------------------------
#  错误处理原则
#  ---------------------------------------------------------------------------
#  本脚本不使用 `|| true` 掩盖文件系统操作失败。
#  之前版本曾用 `hdfs dfs ... || true`，导致"上传失败但作业继续跑"，
#  最终产出全 0 的结果并伪装成成功。所有关键步骤现在都会显式检查退出码。
# =============================================================================
set -euo pipefail

JOB="${1:-}"
if [ -z "$JOB" ]; then
  echo "用法: bash hadoop/scripts/run_check.sh <作业名>" >&2
  exit 2
fi

# ---------------------------------------------------------------------------
# 路径推导
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HADOOP_DIR="$(dirname "$SCRIPT_DIR")"
SRC="$HADOOP_DIR/src"
CHECK="$SRC/check"

# ---------------------------------------------------------------------------
# 可覆盖的环境变量
# ---------------------------------------------------------------------------
DATA_DIR="${ML_DATA_DIR:-$(dirname "$HADOOP_DIR")/data/ml-1m-v2}"
WORK_DIR="${ML_WORK_DIR:-$HOME/mlqc-work}"      # 工作目录（本地或 HDFS）
OUT_DIR="${ML_OUT_DIR:-$HOME/mlqc-out}"         # 结果落地目录（始终为本地）
STREAMING_JAR="${ML_STREAMING_JAR:-${HADOOP_HOME:-/usr/local/hadoop}/share/hadoop/tools/lib/hadoop-streaming-3.4.1.jar}"
ML_FS="${ML_FS:-file}"                          # file | hdfs

SCORE="$SRC/score"                              # 打分相关 mapper（如新鲜度）

# ---------------------------------------------------------------------------
# 输入数据目录
#   默认用 ML_DATA_DIR（原始数据）；
#   after 阶段需要对「清洗后数据」评分，此时由 ML_INPUT_DIR 覆盖。
#   覆盖目录必须同样包含 ratings.dat / movies.dat / users.dat 三个文件。
# ---------------------------------------------------------------------------
INPUT_DIR="${ML_INPUT_DIR:-$DATA_DIR}"

for p in "$INPUT_DIR/ratings.dat" "$INPUT_DIR/movies.dat" "$INPUT_DIR/users.dat"; do
  [ -f "$p" ] || { echo "[run_check] 找不到数据文件: $p" >&2; exit 1; }
done
[ -f "$STREAMING_JAR" ] || {
  echo "[run_check] 找不到 Hadoop Streaming JAR: $STREAMING_JAR" >&2
  exit 1
}
case "$ML_FS" in
  file|hdfs) ;;
  *) echo "[run_check] ML_FS 必须是 file 或 hdfs，得到: $ML_FS" >&2; exit 2 ;;
esac

mkdir -p "$OUT_DIR"

# ---------------------------------------------------------------------------
# 抽象文件系统操作（本地 / HDFS 双模式）
# ---------------------------------------------------------------------------

_ml_fs_mkdir() {
  if [ "$ML_FS" = hdfs ]; then hdfs dfs -mkdir -p "$1"; else mkdir -p "$1"; fi
}

_ml_fs_rm() {
  if [ "$ML_FS" = hdfs ]; then
    # HDFS 下删除不存在的路径会返回非 0，这里显式忽略"路径不存在"这一种情况，
    # 其它失败仍然会中止脚本（因为外层 set -e）。
    hdfs dfs -rm -r -f -skipTrash "$1" >/dev/null 2>&1 || true
  else
    rm -rf "$1"
  fi
}

_ml_fs_exists() {
  if [ "$ML_FS" = hdfs ]; then
    hdfs dfs -test -e "$1"
  else
    [ -e "$1" ]
  fi
}

_ml_fs_put() {
  if [ "$ML_FS" = hdfs ]; then hdfs dfs -put -f "$1" "$2"; else cp -f "$1" "$2"; fi
}

# 读取作业输出目录下所有 part-* 到 stdout（等价于 getmerge）
_ml_fs_getmerge() {
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
# 准备工作目录与输入数据
# ---------------------------------------------------------------------------
_ml_fs_rm "$WORK_DIR"
_ml_fs_mkdir "$WORK_DIR/input"
_ml_fs_mkdir "$WORK_DIR/out"

echo "[run_check] 文件系统模式: $ML_FS   工作目录: $WORK_DIR"
echo "[run_check] 输入数据目录: $INPUT_DIR"

for t in ratings movies users; do
  _ml_fs_put "$INPUT_DIR/$t.dat" "$WORK_DIR/input/$t.dat"
done
for t in ratings movies users; do
  _ml_fs_exists "$WORK_DIR/input/$t.dat" || {
    echo "[run_check] 输入数据未就绪: $WORK_DIR/input/$t.dat" >&2; exit 1; }
done
echo "[run_check] 输入数据已就绪（3 个文件）"

# ---------------------------------------------------------------------------
# Streaming 作业的公共参数
#   - common_file_args : 每个作业都要分发的脚本与规则文件
#   - common_env_args  : 通过容器环境变量告知规则文件位置
#
#   ⚠️ rules.json 必须随作业分发，并显式告知路径：
#      Streaming 容器的工作目录与源码树不同，靠 ml_common.py 反推路径会失败
#      （实测会推出 .../DaShuJu/config/rules.json，缺少仓库目录名）。
# ---------------------------------------------------------------------------
RULES_FILE="$HADOOP_DIR/config/rules.json"
[ -f "$RULES_FILE" ] || { echo "[run_check] 找不到规则文件: $RULES_FILE" >&2; exit 1; }

common_file_args=(
  -file "$SRC/common/ml_common.py"
  -file "$RULES_FILE"
)
common_env_args=(
  -cmdenv ML_RULES=rules.json
)

# ---------------------------------------------------------------------------
# 作业派发
# ---------------------------------------------------------------------------
case "$JOB" in

  # 零、时效性第二层：新鲜度（只读 ratings 的 Timestamp 列）
  #     输出浮点值，因此不需 reducer 的整数补零逻辑，reducer 用 cat 即可
  #     （每条 mapper 输出一行，合并即得总和；本机单 mapper 场景足够）
  freshness-ratings)
    OUT="$WORK_DIR/out/$JOB"
    _ml_fs_rm "$OUT"
    echo "[run_check] 时效性新鲜度计算（ratings）"
    hadoop jar "$STREAMING_JAR" \
      -D mapreduce.job.name="mlqc-$JOB" \
      -D mapreduce.job.reduces=1 \
      "${common_env_args[@]}" \
      -input "$WORK_DIR/input/ratings.dat" \
      -output "$OUT" \
      -mapper "python3 freshness_mapper.py" \
      -reducer "cat" \
      -file "$SCORE/freshness_mapper.py" \
      "${common_file_args[@]}"
    _ml_fs_getmerge "$OUT" "$OUT_DIR/$JOB.txt"
    ;;

  # 一、字段级格式检查
  format-ratings|format-movies|format-users)
    TABLE="${JOB#format-}"
    OUT="$WORK_DIR/out/$JOB"
    _ml_fs_rm "$OUT"
    echo "[run_check] 字段级格式检查: $TABLE"
    hadoop jar "$STREAMING_JAR" \
      -D mapreduce.job.name="mlqc-$JOB" \
      -D mapreduce.job.reduces=1 \
      -cmdenv ML_TABLE="$TABLE" \
      "${common_env_args[@]}" \
      -input "$WORK_DIR/input/$TABLE.dat" \
      -output "$OUT" \
      -mapper "python3 mapper.py" \
      -reducer "python3 reducer.py" \
      -file "$CHECK/mapper.py" \
      -file "$CHECK/reducer.py" \
      "${common_file_args[@]}"
    _ml_fs_getmerge "$OUT" "$OUT_DIR/$JOB.txt"
    ;;

  # 二、跨表引用完整性检查（reduce-side join）
  cross-users|cross-movies)
    DIRECTION="${JOB#cross-}"
    OUT="$WORK_DIR/out/$JOB"
    _ml_fs_rm "$OUT"
    echo "[run_check] 跨表引用完整性检查: ratings -> $DIRECTION"
    hadoop jar "$STREAMING_JAR" \
      -D mapreduce.job.name="mlqc-$JOB" \
      -D mapreduce.job.reduces=4 \
      -cmdenv ML_XREF="$DIRECTION" \
      "${common_env_args[@]}" \
      -input "$WORK_DIR/input/ratings.dat" \
      -input "$WORK_DIR/input/$DIRECTION.dat" \
      -output "$OUT" \
      -mapper "python3 cross_mapper.py" \
      -reducer "python3 cross_reducer.py" \
      -file "$CHECK/cross_mapper.py" \
      -file "$CHECK/cross_reducer.py" \
      "${common_file_args[@]}"
    _ml_fs_getmerge "$OUT" "$OUT_DIR/$JOB.txt"
    ;;

  # 三、分组类检查
  group-u-pair)
    TABLE="ratings"; SPEC="ratings|0,1||uniq";      METRIC="ratings_pair_dup";   REDUCES=4 ;;
  group-u-movie)
    TABLE="movies";  SPEC="movies|0||uniq";         METRIC="movies_movie_dup";   REDUCES=1 ;;
  group-u-user)
    TABLE="users";   SPEC="users|0||uniq";          METRIC="users_user_dup";     REDUCES=1 ;;
  group-c-movie-multi)
    TABLE="movies";  SPEC="movies|0|1,2|multi";     METRIC="movies_value_multi"; REDUCES=1 ;;
  group-c-user-attr)
    TABLE="users";   SPEC="users|0|1,2,3,4|multi";  METRIC="users_attr_multi";   REDUCES=1 ;;

  *)
    echo "[run_check] 未知作业名: $JOB" >&2
    echo "  可用作业: format-ratings format-movies format-users" >&2
    echo "            cross-users cross-movies" >&2
    echo "            group-u-pair group-u-movie group-u-user" >&2
    echo "            group-c-movie-multi group-c-user-attr" >&2
    exit 2
    ;;
esac

# 分组类作业的统一执行入口
if [ -n "${SPEC:-}" ]; then
  OUT="$WORK_DIR/out/$JOB"
  _ml_fs_rm "$OUT"
  echo "[run_check] 分组类检查: $JOB  (table=$TABLE metric=$METRIC reduces=$REDUCES)"
  hadoop jar "$STREAMING_JAR" \
    -D mapreduce.job.name="mlqc-$JOB" \
    -D mapreduce.job.reduces="$REDUCES" \
    -cmdenv ML_GROUP="$SPEC" \
    -cmdenv ML_METRIC="$METRIC" \
    "${common_env_args[@]}" \
    -input "$WORK_DIR/input/$TABLE.dat" \
    -output "$OUT" \
    -mapper "python3 group_mapper.py" \
    -reducer "python3 group_reducer.py" \
    -file "$CHECK/group_mapper.py" \
    -file "$CHECK/group_reducer.py" \
    "${common_file_args[@]}"
  _ml_fs_getmerge "$OUT" "$OUT_DIR/$JOB.txt"
fi

# ---------------------------------------------------------------------------
# 结果校验：空输出是错误信号，不是"没有违规"
# ---------------------------------------------------------------------------
RESULT="$OUT_DIR/$JOB.txt"
if [ ! -s "$RESULT" ]; then
  echo "[run_check] 作业 $JOB 的输出为空，视为失败" >&2
  echo "  原因：空结果无法区分『确实没有违规』与『作业根本没运行』，" >&2
  echo "        因此在源头判定为失败，避免产出不可信的结果。" >&2
  exit 1
fi

echo "[run_check] 完成: $JOB  ->  $RESULT"
