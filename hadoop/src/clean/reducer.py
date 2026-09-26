#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据清洗 —— Reducer（Hadoop Streaming，rule-v2）

⚠️ 为什么不用 MultipleOutputs
-----------------------------
最初的实现尝试用 Java 的 MultipleOutputs 把记录路由到不同输出目录，实测在
Streaming 下走不通（Streaming 用标准 CPython，无法访问 JVM 内的类；
SuffixMultipleTextOutputFormat 在 Hadoop 3.4.1 中也不存在）。
因此采用纯 Python 方案：reducer 只输出「标签 + 记录」，由 driver 按标签分流。

输入：<分组键>\t<标签>\t<原因>\t<记录>     （分组键已由 Hadoop 按 key 排序并分区）
输出：<标签>\t<记录>                       供 driver 分流
      ###COUNTS###\t<指标名>\t<数值>        统计行，供 driver 解析

本 reducer 承担三件事（rule-v2 新增第 2、3 项）：
  1. 隔离透传：mapper 判定为 isolated 的记录原样输出，不做任何"修复"
  2. 去重：同一主键下完全相同的记录只保留一条（信息不丢失）
  3. 冲突处置：同一主键下多条**不同**记录时，按 rules.conflict_policy 分表处置：
       · ratings（事实表）：整组隔离 —— 无法判定真值，且隔离不产生引用断裂
       · users / movies（维表）：按确定性规则保留一条、其余移除 ——
         主键被 ratings 引用，整条删除会造成引用断裂
     两类都属于「无法从数据本身确定真值」的未解决问题，必须计入 conflict_key_count
     并在报告中如实说明。保留一条 / 隔离都不是"修正"。
     —— 之所以放在 reducer：只有 shuffle 之后，同一业务主键的全部记录才会聚到一起。

统计口径（重要）：
  total_input_count   mapper 读入的记录数
  total_count         输出的数据行数（= clean + fixed + conflict + isolated）
  deduped_count       因重复/冲突被移除的记录数（不进入输出）
  conflict_key_count  存在冲突的主键数（未解决）
  conflict_record_count 涉及冲突的记录数
  reason_<原因>       各隔离/修复原因命中数，供报告细化

环境变量：ML_CLEAN_TABLE  ratings | movies | users
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'common'))
import ml_common as ml

TAG_CLEAN = 'clean'
TAG_FIXED = 'fixed'
TAG_ISOLATED = 'isolated'
TAG_CONFLICT = 'conflict'          # 冲突中被保留的那一条（进入清洗后数据集）
VALID_TAGS = (TAG_CLEAN, TAG_FIXED, TAG_ISOLATED, TAG_CONFLICT)

COUNTS_PREFIX = '###COUNTS###'


def rank(record):
    """
    冲突消解排序键（越小越优先保留）。规则见 rules.json conflict_policy.resolve_by：
      1. 无修复动作（clean）优先于已修复（fixed）
      2. 非空字段更多（信息更完整）者优先
      3. 字节序最小者优先，保证结果可复现
    """
    tag, body = record
    return (0 if tag == TAG_CLEAN else 1,
            -ml.count_nonempty_fields(body.split(b'::')),
            body)


def main():
    table = os.environ.get('ML_CLEAN_TABLE', '')
    if not table:
        raise SystemExit(
            '[clean_reducer] 缺少环境变量 ML_CLEAN_TABLE\n'
            '  必须是 ratings / movies / users 之一。'
        )

    out = sys.stdout.buffer

    counts = {TAG_CLEAN: 0, TAG_FIXED: 0, TAG_ISOLATED: 0, TAG_CONFLICT: 0}
    reasons = {}
    total_input = 0
    deduped = 0
    conflict_keys = 0
    conflict_records = 0
    unknown = 0

    cur_key = None
    cur_valid = {}        # body -> (tag, reason)：同一主键下的不同合法记录
    cur_iso = []          # [(body, reason)]：隔离记录（原样输出）
    cur_total = 0

    def flush():
        nonlocal deduped, conflict_keys, conflict_records
        if cur_key is None:
            return
        if cur_iso:
            # 隔离记录：逐条输出，保留原文与原因
            for body, reason in cur_iso:
                out.write(TAG_ISOLATED.encode('ascii') + b'\t' + reason.encode('ascii')
                          + b'\t' + body + b'\n')
                counts[TAG_ISOLATED] += 1
            return

        if not cur_valid:
            return

        if len(cur_valid) == 1:
            body, (tag, reason) = next(iter(cur_valid.items()))
            out.write(tag.encode('ascii') + b'\t' + reason.encode('ascii')
                      + b'\t' + body + b'\n')
            counts[tag] += 1
            # 该主键下完全相同的副本：只输出一条，其余计入去重移除。
            # ⚠️ 这一行不能漏：漏了会造成 total_input > total_out + deduped 的口径不平，
            #    driver 会直接判定清洗失败（历史 bug，勿删）。
            deduped += cur_total - 1
        elif table == 'ratings':
            # 事实表冲突：隔离全部变体，不猜值。
            # 依据：ratings 是事件记录，无法判定真值；隔离不会造成任何引用断裂
            #      （没有其它表引用 ratings），代价仅是数据量减少，可如实报告。
            # 若"任选一条保留"，实测 95% 的冲突键会选中被注入的评分值，
            # 等于把错误值写入清洗后数据集 —— 违背"不确定就隔离"的原则。
            for body, (tag, reason) in cur_valid.items():
                out.write(TAG_ISOLATED.encode('ascii') + b'\tconflict_isolated\t'
                          + body + b'\n')
                counts[TAG_ISOLATED] += 1
            # 组内完全相同的副本仍然属于"去重移除"，必须计入，否则口径不平
            deduped += cur_total - len(cur_valid)
            conflict_keys += 1
            conflict_records += cur_total
        else:
            # 维表冲突（users/movies）：保留一条，其余移除。
            # 依据：维表主键被 ratings 引用，整条删除会让原本合法的评分变成
            #      孤儿记录（引用断裂），代价高于"保留一条可疑值"。
            # 该处置**不等于修正**，计入未解决问题。
            winner_body, (winner_tag, _r) = min(
                cur_valid.items(), key=lambda kv: rank((kv[1][0], kv[0])))
            out.write(TAG_CONFLICT.encode('ascii') + b'\tconflict_resolved\t'
                      + winner_body + b'\n')
            counts[TAG_CONFLICT] += 1
            conflict_keys += 1
            conflict_records += cur_total
            deduped += cur_total - 1

    stdin = sys.stdin.buffer
    for line in stdin:
        raw = ml.rstrip_eol(line)
        if raw == b'':
            continue
        parts = raw.split(b'\t', 3)
        if len(parts) < 4:
            unknown += 1
            continue
        key, tag_b, reason_b, body = parts
        tag = ml.to_text(tag_b)
        reason = ml.to_text(reason_b)

        if tag not in VALID_TAGS:
            unknown += 1
            continue

        total_input += 1
        reasons[reason] = reasons.get(reason, 0) + 1

        if key != cur_key:
            flush()
            cur_key = key
            cur_valid = {}
            cur_iso = []
            cur_total = 0

        cur_total += 1
        if tag == TAG_ISOLATED:
            cur_iso.append((body, reason))
        else:
            # 同一主键下完全相同的记录合并（去重）；tag 取更"干净"的那个
            prev = cur_valid.get(body)
            if prev is None or (prev[0] != TAG_CLEAN and tag == TAG_CLEAN):
                cur_valid[body] = (tag, reason)

    flush()

    total_out = counts[TAG_CLEAN] + counts[TAG_FIXED] + counts[TAG_ISOLATED] + counts[TAG_CONFLICT]

    lines = [
        ('clean_count', counts[TAG_CLEAN]),
        ('fixed_count', counts[TAG_FIXED]),
        ('conflict_count', counts[TAG_CONFLICT]),
        ('isolated_count', counts[TAG_ISOLATED]),
        ('deduped_count', deduped),
        ('conflict_key_count', conflict_keys),
        ('conflict_record_count', conflict_records),
        ('unknown_count', unknown),
        ('total_input_count', total_input),
        ('total_count', total_out),
    ]
    for name, value in lines:
        out.write(('%s\t%s\t%d\n' % (COUNTS_PREFIX, name, value)).encode('ascii'))
    for name in sorted(reasons):
        safe = name.replace('\t', ' ')
        out.write(('%s\treason_%s\t%d\n' % (COUNTS_PREFIX, safe, reasons[name])).encode('ascii'))

    out.flush()

    # 自校验：输入 = 输出 + 被去重移除的
    if total_input != total_out + deduped:
        sys.stderr.write(
            '[clean_reducer] 口径不自洽: total_input=%d total_out=%d deduped=%d\n'
            % (total_input, total_out, deduped))

    sys.stderr.write(
        '[clean_reducer] table=%s input=%d clean=%d fixed=%d conflict=%d isolated=%d dedup=%d\n'
        % (table, total_input, counts[TAG_CLEAN], counts[TAG_FIXED],
           counts[TAG_CONFLICT], counts[TAG_ISOLATED], deduped))
    sys.stderr.flush()


if __name__ == '__main__':
    main()
