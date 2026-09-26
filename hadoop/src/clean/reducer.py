#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据清洗 —— Reducer（Hadoop Streaming）

⚠️ 为什么不用 MultipleOutputs
-----------------------------
最初的实现使用 Java 的 PotentialOutputs / MultipleOutputs 把记录路由到
不同输出目录。但实测证明这条路在 Hadoop Streaming 下走不通：

  1. `from org.apache.hadoop.mapred.lib import MultipleOutputs`
     失败：ModuleNotFoundError: No module named 'org'

     原因：Hadoop Streaming 用的是**标准 CPython**，不是 Jython。
     它只提供 stdin/stdout 接口，不提供 JVM 内的 Java 类访问能力。
     （历史上 Streaming 曾用 Jython，故有大量资料仍推荐该写法。）

  2. 退而求其次的 `-outputformat org.apache.hadoop.mapred.lib.SuffixMultipleTextOutputFormat`
     也不可用：Hadoop 3.4.1 中该类不存在
     （`class not found : ...SuffixMultipleTextOutputFormat`）

因此本 reducer 采用**纯 Python 方案**：
  reducer 只负责把「处置标签 + 记录原文」写到输出，
  由 driver 在读取输出后按标签分流到 清洗后数据集 / 隔离数据集，
  并统计各处置类别的条数。

这样做的好处：
  · 零 JVM 依赖，纯 Python，与其它 mapper/reducer 风格一致
  · 分流逻辑集中在 driver，便于测试与调整
  · 不依赖任何可能在版本间变动/缺失的 Java 类

输入：<标签>\t<记录原文>      标签为 clean / fixed / isolated
输出：<标签>\t<记录原文>      原样透传，标签供 driver 分流
      ###COUNTS###\t<指标名>\t<数值>   末尾的统计行，供 driver 解析

关于统计行：
  Hadoop 会丢弃容器进程的 stderr，因此不能把统计写到 stderr。
  这里用 `###COUNTS###` 作为保留前缀输出到 stdout，
  真实记录的标签只会是 clean/fixed/isolated，不会与该前缀冲突。
  driver 读取输出时先摘出这些行，剩下的才是数据。

说明：单一 reducer（reduces=1）以保证输出顺序稳定；数据量仅 24MB，
单 reducer 完全够用，无需为并行度牺牲可读性。
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'common'))
import ml_common as ml

TAG_CLEAN = 'clean'
TAG_FIXED = 'fixed'
TAG_ISOLATED = 'isolated'
VALID_TAGS = (TAG_CLEAN, TAG_FIXED, TAG_ISOLATED)

# 统计行的保留前缀。driver 依赖此常量，修改时须同步。
COUNTS_PREFIX = '###COUNTS###'


def main():
    table = os.environ.get('ML_CLEAN_TABLE', '')
    if not table:
        raise SystemExit(
            '[clean_reducer] 缺少环境变量 ML_CLEAN_TABLE\n'
            '  必须是 ratings / movies / users 之一。'
        )

    counts = {TAG_CLEAN: 0, TAG_FIXED: 0, TAG_ISOLATED: 0}
    unknown = 0
    total = 0

    stdin = sys.stdin.buffer
    out = sys.stdout.buffer

    for line in stdin:
        raw = ml.rstrip_eol(line)
        if raw == b'':
            continue

        parts = raw.split(b'\t', 1)
        if len(parts) < 2:
            unknown += 1
            continue

        tag_bytes, payload = parts[0], parts[1]
        tag = ml.to_text(tag_bytes)

        if tag not in VALID_TAGS:
            unknown += 1
            continue

        counts[tag] += 1
        total += 1
        # 原样透传：标签 + 原始记录字节，不做任何转码
        out.write(tag_bytes + b'\t' + payload + b'\n')

    # 统计行（供 driver 解析）
    for name, value in (
        ('clean_count', counts[TAG_CLEAN]),
        ('fixed_count', counts[TAG_FIXED]),
        ('isolated_count', counts[TAG_ISOLATED]),
        ('unknown_count', unknown),
        ('total_count', total),
    ):
        out.write(('%s\t%s\t%d\n' % (COUNTS_PREFIX, name, value)).encode('ascii'))

    out.flush()

    sys.stderr.write(
        '[clean_reducer] table=%s total=%d clean=%d fixed=%d isolated=%d unknown=%d\n'
        % (table, total, counts[TAG_CLEAN], counts[TAG_FIXED],
           counts[TAG_ISOLATED], unknown))
    sys.stderr.flush()


if __name__ == '__main__':
    main()
