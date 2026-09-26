#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
时效性第二层（新鲜度）—— Mapper（Hadoop Streaming）

职责：为每条评分记录计算 freshness 值并求和，供 driver 求均值。

对应 docs/evaluation-method.md 第 4.4 节「第二层：时间新鲜度」：

    freshness(r) = clamp( (t_r − T1) ÷ (T2 − T1), 0, 1 )

语义（务必理解，否则会误判该维度）：
    t ≤ T1        -> 0    位于训练期，对新近程度无贡献
    T1 < t ≤ T2   -> (t−T1)/(T2−T1)，随接近 T2 线性升到 1
    t > T2        -> 1    已进入测试期，视为最新
    t < T1        -> 0    与 t ≤ T1 相同（clamp 下界）

⚠️ 本数据集的实际结果（实测，请勿凭直觉推断）
-----------------------------------------------
T1 = 2000-11-22（974862386）、T2 = 2000-12-10（976422054）为分位数切点，
因此按定义必然有 70% 的记录落在 T1 之前、15% 在 T1~T2 之间、15% 在 T2 之后。
实测分布：

    clamp 到 0  (t <= T1) :  700,144  (70.00%)
    线性区间    (T1~T2)   :  150,035  (15.00%)
    clamp 到 1  (t > T2)  :  150,030  (15.00%)

    freshness 合计 : 215430.8298798208
    freshness 均值 : 0.215385814245

均值为 0.2154 的含义：整体数据窗口的"新近程度"约为 21.5%。
这是**客观事实的如实反映**，不是缺陷 —— T1/T2 一旦按分位数确定，
该均值就基本被锁定了（线性区间贡献约 0.075，T2 之后的 15% 贡献 0.15）。

依据 docs/迭代一_Hadoop数据清洗与Agent基础.md 第 51 行，
数据年代较早并不必然是错误。因此该维度得分低**不代表数据质量差**，
必须在报告中说明清楚，不可单独作为"数据质量差"的依据。

输出：<指标名>\t<数值>（浮点，保留 10 位小数）
    ratings_freshness_sum   全部记录 freshness 之和
    ratings_freshness_n     参与计算的记录数
    ratings_freshness_skipped  时间戳不合法而跳过的记录数

为什么用浮点而不是整数：freshness 是 [0,1] 的实数，若取整会丢失全部信息
（单条 freshness 最大 1，取整后几乎全为 0）。
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'common'))
import ml_common as ml


def compute_freshness(ts, t1, t2):
    """
    计算单条记录的新鲜度，返回 [0, 1] 的浮点数。

    ts  该评分的时间戳（秒）
    t1  训练期截止（秒）
    t2  验证期截止（秒）
    """
    span = float(t2 - t1)
    if span <= 0:
        # T1/T2 配置异常，不能静默返回 0（那会伪装成"数据不新鲜"）
        raise SystemExit(
            '[freshness_mapper] T1/T2 配置非法: T1=%d T2=%d，要求 T1 < T2。\n'
            '  请检查 hadoop/config/rules.json 的 time 段。' % (t1, t2)
        )
    v = (float(ts) - float(t1)) / span
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


def main():
    ml.init_rules()
    t1, t2 = ml.T1, ml.T2
    if t1 is None or t2 is None:
        raise SystemExit('[freshness_mapper] 未能从规则中读取 T1/T2')

    total = 0.0
    n = 0
    skipped = 0

    stdin = sys.stdin.buffer
    for line in stdin:
        fields = ml.split_fields(line)
        if len(fields) < 4:
            skipped += 1
            continue
        ts_b = fields[3]
        if not ml.is_digits(ts_b):
            skipped += 1
            continue
        ts = ml.parse_int(ts_b)
        if ts is None:
            skipped += 1
            continue

        total += compute_freshness(ts, t1, t2)
        n += 1

    ml.emit_float('ratings_freshness_sum', total)
    ml.emit('ratings_freshness_n', n)
    ml.emit('ratings_freshness_skipped', skipped)


if __name__ == '__main__':
    main()
