#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分组类检查 —— Mapper（通用，覆盖 6 个场景）

支持两类检查（依据 docs/evaluation-method.md 第 4.3、4.5 节）：

  [multi] 同一主键是否对应多个不同属性值  -> C4 / C5 / C6
  [uniq]  主键是否重复                    -> U1 / U2 / U3

由环境变量 ML_GROUP 指定检查规格，格式（分隔符统一用 |，避免与冒号冲突）：
    ML_GROUP="<table>|<keyIdx,...>|<valIdx,...>|<mode>"

  例如：
    ML_GROUP="movies|0|1,2|multi"      # movies 按第0列，看第1,2列是否多变体 (C4,C5)
    ML_GROUP="users|0|1,2,3,4|multi"   # users 按第0列，看属性列是否冲突 (C6)
    ML_GROUP="ratings|0,1||uniq"       # ratings 按 (UserID,MovieID) 查重复 (U1)

  值为空的写法：valIdx 位置留空即可（两个连续竖线）。

输出：<分组键> \t <值字段的拼接> \t <标签>
     标签为 M(multi) 或 U(uniq)，供 reducer 判定模式。

字段索引从 0 开始，与 .dat 文件中的列顺序一致。
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'common'))
import ml_common as ml


def parse_spec(spec):
    """解析 ML_GROUP 规格字符串。"""
    parts = spec.split('|')
    if len(parts) != 4:
        raise SystemExit(
            '[group_mapper] ML_GROUP 格式非法: %r\n'
            '  期望 "<table>|<keyIdx,...>|<valIdx,...>|<mode>"（共 4 段，用 | 分隔）\n'
            '  实际得到 %d 段' % (spec, len(parts))
        )
    table, key_part, val_part, mode = (p.strip() for p in parts)
    key_idx = [int(x) for x in key_part.split(',') if x.strip() != '']
    if val_part == '':
        val_idx = []
    else:
        val_idx = [int(x) for x in val_part.split(',') if x.strip() != '']
    if mode not in ('multi', 'uniq'):
        raise SystemExit('[group_mapper] mode 必须是 multi 或 uniq，得到: %r' % mode)
    if table not in ('ratings', 'movies', 'users'):
        raise SystemExit('[group_mapper] table 非法: %r' % table)
    if not key_idx:
        raise SystemExit('[group_mapper] 必须至少指定一个 keyIdx')
    return table, key_idx, val_idx, mode


def main():
    spec = os.environ.get('ML_GROUP', '')
    if not spec:
        raise SystemExit('[group_mapper] 缺少环境变量 ML_GROUP')
    table, key_idx, val_idx, mode = parse_spec(spec)
    label = 'M' if mode == 'multi' else 'U'

    stdin = sys.stdin.buffer
    for line in stdin:
        f = ml.split_fields(line)
        if len(f) == 1 and f[0] == b'':
            continue
        # 字段数不足时跳过（此类问题由格式检查负责统计）
        if key_idx and max(key_idx) >= len(f):
            continue
        if val_idx and max(val_idx) >= len(f):
            continue

        key = b'::'.join(f[i] for i in key_idx)
        if key == b'':
            continue

        if val_idx:
            val = b'|'.join(f[i] for i in val_idx)
        else:
            val = b''

        sys.stdout.write('%s\t%s\t%s\n' % (ml.to_text(key), ml.to_text(val), label))


if __name__ == '__main__':
    main()
