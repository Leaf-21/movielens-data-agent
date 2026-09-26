#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
跨表引用完整性检查（C1 / C2）—— Reducer

输入：<ID>\t<标签>，标签为 R（来自 ratings）或 F（来自参照表 users/movies）
输出：参照完整性统计指标

判定逻辑（每个 ID 一行）：
  - 出现 R，未出现 F  -> 该 ID 是「孤儿引用」，对应 ratings 记录无法关联到主表
  - 同时出现 R 和 F   -> 关联成功
  - 只出现 F          -> 参照表中存在但无评分引用（正常，如无人评分的电影）

输出指标（由 ML_XREF 决定前缀 users_ 或 movies_）：
  xref_rating_records   参与检查的 ratings 记录总数（含孤儿记录）
  xref_matched_records  成功关联的记录数
  xref_orphan_records   孤儿记录数  ← 即 C1 / C2 的违规数
  xref_orphan_ids       涉及孤儿引用的不同 ID 个数
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'common'))
import ml_common as ml

TAG_RATINGS = 'R'
TAG_REF = 'F'


def main():
    direction = os.environ.get('ML_XREF', '')
    if direction not in ('users', 'movies'):
        raise SystemExit(
            '[cross_reducer] 环境变量 ML_XREF 非法或缺失: %r' % direction
        )

    rating_records = 0     # R 标记总数（= 参与检查的记录数）
    matched_records = 0    # 有 F 的 R 记录数
    orphan_records = 0     # 无 F 的 R 记录数
    orphan_ids = 0         # 涉及孤儿引用的不同 ID 数

    cur_key = None
    cur_r = 0
    cur_has_f = False

    def flush():
        """处理分组结束时的一次结算。"""
        nonlocal rating_records, matched_records, orphan_records, orphan_ids
        if cur_key is None:
            return
        rating_records += cur_r
        if cur_has_f:
            matched_records += cur_r
        elif cur_r > 0:
            orphan_records += cur_r
            orphan_ids += 1

    stdin = sys.stdin.buffer
    for raw in stdin:
        if isinstance(raw, bytes):
            raw = raw.decode(ml.ENCODING)
        raw = raw.rstrip('\n').rstrip('\r')
        if not raw:
            continue
        parts = raw.split('\t')
        if len(parts) < 2:
            continue
        key, tag = parts[0], parts[1]

        if key != cur_key:
            flush()
            cur_key = key
            cur_r = 0
            cur_has_f = False

        if tag == TAG_RATINGS:
            cur_r += 1
        elif tag == TAG_REF:
            cur_has_f = True
        # 其他标签忽略

    flush()

    p = direction + '_'
    ml.emit(p + 'rating_records', rating_records)
    ml.emit(p + 'matched_records', matched_records)
    ml.emit(p + 'orphan_records', orphan_records)
    ml.emit(p + 'orphan_ids', orphan_ids)


if __name__ == '__main__':
    main()
