#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
跨表引用完整性检查（C1 / C2）—— Mapper

用途：检查 ratings 引用的 UserID / MovieID 是否存在于对应的 users / movies 表中。
      （docs/evaluation-method.md 第 4.5 节 C1、C2）

实现方式：Reduce-side Join
  - 两份输入都读进同一个 job，mapper 按输入文件名区分来源。
  - 输出 key 统一为「引用ID」，value 带来源标签。
  - 因 Hadoop 默认 HashPartitioner 对所有记录的 key 做哈希，
    所以同一 ID 的 ratings 记录与参照表记录必然进入同一个 reducer。
  - **同一个 job 只能用同一个 mapper 脚本**（Streaming 限制），
    因此本脚本对两种输入分别处理：先按文件名判断读哪一列。

由环境变量 ML_XREF 区分检查方向：
  ML_XREF=users   -> 读 ratings 的 UserID（第1列） 与 users 的 UserID（第1列）
  ML_XREF=movies  -> 读 ratings 的 MovieID（第2列）与 movies 的 MovieID（第1列）

输入文件名由 Hadoop 通过环境变量 mapreduce_map_input_file 提供。
为保证本地管道测试也能运行，该变量缺失时按 ML_INPUT_ROLE 环境变量兜底：
  ML_INPUT_ROLE=ratings  -> 全部按 ratings 处理
  ML_INPUT_ROLE=ref      -> 全部按参照表处理
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'common'))
import ml_common as ml

TAG_RATINGS = 'R'
TAG_REF = 'F'


def classify_input_file():
    """
    判断当前 mapper 正在读哪一个输入文件。
    返回 'ratings' 或 'ref'。
    """
    name = os.environ.get('mapreduce_map_input_file', '')
    if not name:
        # 本地测试兜底
        role = os.environ.get('ML_INPUT_ROLE', '')
        if role in ('ratings', 'ref'):
            return role
        raise SystemExit(
            '[cross_mapper] 无法确定输入文件。\n'
            '  在 Hadoop 下应由 mapreduce_map_input_file 提供；\n'
            '  本地测试请设置 ML_INPUT_ROLE=ratings 或 ML_INPUT_ROLE=ref。'
        )
    base = name.rsplit('/', 1)[-1].lower()
    if 'ratings' in base:
        return 'ratings'
    return 'ref'


def main():
    direction = os.environ.get('ML_XREF', '')
    if direction == 'users':
        col_idx = 0          # ratings 的 UserID 是第 1 列
    elif direction == 'movies':
        col_idx = 1          # ratings 的 MovieID 是第 2 列
    else:
        raise SystemExit(
            '[cross_mapper] 环境变量 ML_XREF 非法或缺失: %r\n'
            "  必须是 'users' 或 'movies'。" % direction
        )

    role = classify_input_file()
    stdin = sys.stdin.buffer

    if role == 'ratings':
        # ratings 侧：取引用ID，打 R 标签
        # ⚠️ 只统计结构完整（恰好 4 个字段）的记录。
        #    否则被替换掉分隔符的坏行会以整行为 key 混进来，被误判成"孤儿引用"，
        #    把结构问题重复计入一致性问题（rule-v2 修正）。
        for line in stdin:
            f = ml.split_fields(line)
            if len(f) != 4:
                continue
            key = f[col_idx]
            if key == b'':
                continue
            # 一条 ratings 记录贡献一个 R 标记
            sys.stdout.write('%s\t%s\n' % (ml.to_text(key), TAG_RATINGS))
    else:
        # 参照表侧：表内 ID 全表唯一，每个 ID 只需发一次 F 标记。
        # 但同一 reduce 分区内可能有多条重复（若参照表本身有重复），
        # reducer 侧用集合去重，因此这里直接逐行发出即可。
        for line in stdin:
            f = ml.split_fields(line)
            if len(f) == 0 or f[0] == b'':
                continue
            # 结构损坏的行不参与参照：它的首列并非合法主键
            if not ml.is_positive_int_str(f[0]):
                continue
            sys.stdout.write('%s\t%s\n' % (ml.to_text(f[0]), TAG_REF))


if __name__ == '__main__':
    main()
