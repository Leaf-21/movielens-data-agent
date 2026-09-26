#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
格式检查 —— Reducer（Hadoop Streaming）

职责：把各 mapper 输出的 <指标名>\t<数值> 记录按键求和，
     并加上表名前缀，避免三张表的同名指标在驱动程序中互相覆盖。

输入：stdin，格式  <指标名>\t<数值>
输出：stdout，格式 <表名>_<指标名>\t<合计值>

⚠️ 关于前缀：三个表的格式检查都使用同一个 mapper/reducer 脚本，
   而 mapper 输出的 total / missing 等指标名在各表中含义不同
   （total 分别表示 ratings/movies/users 的记录数）。
   若不加前缀，三个作业的结果汇总时会互相覆盖，导致数据规模统计错误。
   因此这里强制加 <表名>_ 前缀，驱动程序按带前缀的名字读取。

注意：Hadoop Streaming 会自动按 key 排序，相同 key 的记录连续到达。
为稳妥起见，这里用字典聚合后再输出，不依赖到达顺序。
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'common'))
import ml_common as ml


def main():
    table = os.environ.get('ML_TABLE', '')
    if not table:
        raise SystemExit('[reducer] 缺少环境变量 ML_TABLE')

    totals = ml.read_counters(sys.stdin)

    # 补零：未命中的指标必须显式输出 0，
    # 否则下游 driver 无法区分"计数为 0"与"该任务未运行"。
    for name in ml.all_metrics_for(table):
        totals.setdefault(name, 0)

    prefix = table + '_'
    for name in sorted(totals):
        ml.emit(prefix + name, totals[name])


if __name__ == '__main__':
    main()
