#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分组类检查 —— Reducer（通用）

输入：<分组键> \t <值拼接> \t <标签>    （标签 M=multi，U=uniq）
输出：<指标名>_keys        参与检查的不同主键数
      <指标名>_violations  违规主键数（multi: 值不唯一；uniq: 出现重复）

指标名由环境变量 ML_METRIC 提供（在 rules.json 的
unique_keys / consistency_keys 中定义）。

内存控制：只保留当前分组键的值集合，分组切换时立即释放。
因 Hadoop 已按 key 排序并分区，同一主键不会跨越多个 reducer。
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'common'))
import ml_common as ml


def main():
    metric = os.environ.get('ML_METRIC', '')
    if not metric:
        raise SystemExit('[group_reducer] 缺少环境变量 ML_METRIC')

    total_keys = 0
    violations = 0

    cur_key = None
    cur_vals = set()
    cur_rows = 0
    cur_label = None

    def flush():
        """结算一个分组。"""
        nonlocal total_keys, violations
        if cur_key is None:
            return
        total_keys += 1
        if cur_label == 'M':
            # multi: 同一主键出现了多个不同值 -> 冲突
            if len(cur_vals) > 1:
                violations += 1
        else:
            # uniq: 同一主键出现多行 -> 重复
            if cur_rows > 1:
                violations += 1

    stdin = sys.stdin.buffer
    for raw in stdin:
        if isinstance(raw, bytes):
            raw = raw.decode(ml.ENCODING)
        raw = raw.rstrip('\n').rstrip('\r')
        if not raw:
            continue
        parts = raw.split('\t')
        if len(parts) < 3:
            continue
        key, val, label = parts[0], parts[1], parts[2]

        if key != cur_key:
            flush()
            cur_key = key
            cur_vals = set()
            cur_rows = 0
            cur_label = label

        cur_rows += 1
        if label == 'M':
            cur_vals.add(val)
        # uniq 模式不需要记录值

    flush()

    ml.emit(metric + '_keys', total_keys)
    ml.emit(metric + '_violations', violations)


if __name__ == '__main__':
    main()
