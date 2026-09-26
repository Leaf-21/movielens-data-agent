#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据清洗 —— Mapper（Hadoop Streaming）

职责：逐条判断记录是否需要修复、去重或隔离，并按处置结果打标签。

输入：stdin，每行一条原始记录（bytes，ISO-8859-1）
输出：stdout，格式  <标签>\t<记录原文>

标签取值（reducer 依据此路由到不同输出目录）：
  clean       无需处置，直接进入清洗后数据集
  fixed       已修复（如 ZIP+4 截为 5 位）
  isolated    无法确定正确值，移出主数据集

环境变量：
  ML_CLEAN_TABLE  ratings | movies | users

⚠️ 关于"修复"与"隔离"的边界（依据 docs/迭代一_Hadoop数据清洗与Agent基础.md 第 91 行）
------------------------------------------------------------------------------
本程序只修复**能确定正确值**的字段，并严格区分两类 Zip-code：

  · ZIP+4 形式 `NNNNN-NNNN`（66 条）
    值合法且可解释，截取前 5 位不改变语义  ->  修复

  · 6/7/9 位纯数字（15 条）
    例如 495321 无法判断是"多输一位"还是"漏了分隔符"，
    任何截断或猜测都可能引入新错误          ->  隔离，不得修复

绝不把"隔离"表述为"已修复"。
"""

import sys
import os
import re

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'common'))
import ml_common as ml

TAG_CLEAN = 'clean'
TAG_FIXED = 'fixed'
TAG_ISOLATED = 'isolated'

# ZIP+4 形式：5 位数字 + '-' + 4 位数字
ZIP4_RE = re.compile(r'^(\d{5})-\d{4}$')


def clean_users(fields):
    """
    清洗 users.dat: UserID::Gender::Age::Occupation::Zip-code

    返回 (标签, 记录字节串)
    只有 Zip-code 需要处置；其余字段实测无违规。
    """
    if len(fields) != 5:
        # 字段数异常无法定位 Zip-code，交给隔离
        return TAG_ISOLATED, None

    uid, gender, age, occ, zipc = fields
    zip_txt = ml.to_text(zipc)

    # 情形一：ZIP+4 -> 修复为 5 位主体
    m = ZIP4_RE.match(zip_txt.strip())
    if m:
        new_fields = [uid, gender, age, occ, m.group(1).encode('ascii')]
        return TAG_FIXED, b'::'.join(new_fields)

    # 情形二：标准 5 位（含前导零）-> 无需处置
    if len(zipc) == 5 and ml.is_digits(zipc):
        return TAG_CLEAN, None

    # 情形三：其他长度或含非数字 -> 无法确定正确值，隔离
    return TAG_ISOLATED, None


def clean_ratings(fields):
    """
    清洗 ratings.dat: UserID::MovieID::Rating::Timestamp

    实测无违规，本函数保留完整的判定逻辑，以便数据变化时自动生效。
    """
    if len(fields) != 4:
        return TAG_ISOLATED, None
    uid, mid, rat, ts = fields
    # 必需字段缺失
    if uid == b'' or mid == b'' or rat == b'' or ts == b'':
        return TAG_ISOLATED, None
    # 标识符与评分合法性
    if not ml.is_positive_int_str(uid) or not ml.is_positive_int_str(mid):
        return TAG_ISOLATED, None
    if not (ml.is_digits(rat) and 1 <= ml.parse_int(rat) <= 5):
        return TAG_ISOLATED, None
    # 时间戳可解释
    if not ml.is_digits(ts) or ml.parse_int(ts) <= 0:
        return TAG_ISOLATED, None
    return TAG_CLEAN, None


def clean_movies(fields):
    """
    清洗 movies.dat: MovieID::Title::Genres

    实测无违规。Title 含 ISO-8859-1 特殊字符的记录**不是错误**，
    必须保留原字节，不得转码（转码会破坏数据）。
    """
    if len(fields) != 3:
        return TAG_ISOLATED, None
    mid, title, genres = fields
    if mid == b'' or title.strip() == b'':
        return TAG_ISOLATED, None
    if not ml.is_positive_int_str(mid):
        return TAG_ISOLATED, None
    # Title 首尾空白 -> 可安全修复
    if title != title.strip():
        fixed = [mid, title.strip(), genres]
        return TAG_FIXED, b'::'.join(fixed)
    return TAG_CLEAN, None


CLEANERS = {
    'ratings': clean_ratings,
    'movies': clean_movies,
    'users': clean_users,
}


def main():
    table = os.environ.get('ML_CLEAN_TABLE', '')
    cleaner = CLEANERS.get(table)
    if cleaner is None:
        raise SystemExit(
            '[clean_mapper] 环境变量 ML_CLEAN_TABLE 非法或缺失: %r\n'
            '  必须是 ratings / movies / users 之一。' % table
        )

    ml.init_rules()

    stdin = sys.stdin.buffer
    out = sys.stdout.buffer
    for line in stdin:
        fields = ml.split_fields(line)
        if len(fields) == 1 and fields[0] == b'':
            continue

        original = ml.rstrip_eol(line)
        tag, replacement = cleaner(fields)

        # ⚠️ 必须写二进制流（sys.stdout.buffer），不能用文本流 + %s 格式化。
        #
        # 踩过的坑：原先写作
        #     sys.stdout.write('%s\t%s\n' % (TAG_CLEAN, original))
        # original 是 bytes，%s 会调用 str() 得到形如 b'6040::M::25::6::11106'
        # 的**字节字面量表示**，连同 b 和引号一起写进输出，
        # 导致清洗后数据整体损坏（6040 条全部受影响）。
        # 实测证据（od -c）：
        #     c l e a n \t b ' 6 0 4 0 : : M : : 2 5 : : 6 : : 1 1 1 0 6 ' \n
        #
        # 正确做法：按字节拼接后直接写入二进制流，保证记录原文不被改动。
        if tag == TAG_FIXED:
            payload = replacement
        elif tag == TAG_ISOLATED:
            payload = original
        else:
            payload = replacement or original

        out.write(tag.encode('ascii') + b'\t' + payload + b'\n')


if __name__ == '__main__':
    main()
