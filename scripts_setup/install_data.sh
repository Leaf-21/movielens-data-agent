#!/usr/bin/env bash
# =============================================================================
# 把 MovieLens v2 数据从 Windows 拷到 WSL 的 ~/data/ml-1m-v2
#   数据源：C:\Users\39424\Downloads\ml-1m.zip（已核对 SHA256 为 v2）
# 幂等：可重复执行。
# =============================================================================
set -euo pipefail

ZIP="/mnt/c/Users/39424/Downloads/ml-1m.zip"
DEST="$HOME/data/ml-1m-v2"

# v2 的权威校验和（来自 data/DATASETS.md）
declare -A SHA=(
  [ratings.dat]="1b3c4690b619d5f6bead9283d02ad12460da88bd3087ac2a93959bb37f4995d2"
  [movies.dat]="e256099e0a8f2d7cdc4b97ac94864c5f05795b929a97b045516ac86303931e18"
  [users.dat]="c0397b2eb6210f14a683c65d15d7d927aaffac0c08bcbefddb8cc2063a988279"
)

if [ ! -f "$ZIP" ]; then
  echo "[错误] 找不到数据压缩包: $ZIP" >&2
  exit 1
fi

echo "[1/3] 解压 $ZIP ..."
TMP="$(mktemp -d)"
unzip -q "$ZIP" -d "$TMP"

mkdir -p "$DEST"
# zip 结构是 ml-1m/{ratings,movies,users}.dat
find "$TMP" -type f -name '*.dat' -exec cp -f {} "$DEST"/ \;
rm -rf "$TMP"

echo "[2/3] 校验 SHA256 ..."
ok=1
for f in ratings.dat movies.dat users.dat; do
  actual=$(sha256sum "$DEST/$f" | awk '{print $1}')
  if [ "$actual" = "${SHA[$f]}" ]; then
    echo "  $f  ✓"
  else
    echo "  $f  ✗  期望 ${SHA[$f]}  实际 $actual" >&2
    ok=0
  fi
done
[ "$ok" = 1 ] || { echo "[错误] 校验和不匹配，数据不是 v2" >&2; exit 1; }

echo "[3/3] 数据就绪: $DEST"
ls -lh "$DEST"
