#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据清洗 —— Mapper（Hadoop Streaming，rule-v2）

职责：逐条判断记录是否需要修复、隔离，并输出可供 reducer 按业务主键分组的信息。

输入：stdin，每行一条原始记录（bytes，ISO-8859-1）
输出：stdout，格式  <分组键>\t<标签>\t<原因>\t<记录>

  分组键：合法记录的业务主键（users=UserID，movies=MovieID，ratings=UserID::MovieID），
          reducer 依赖 Hadoop 的 shuffle 把同一主键的记录聚到一组，从而完成去重与冲突消解。
          隔离记录使用以 \x01 开头的唯一键，保证它们各自成组、不干扰主键分组。
  标签：  clean     无需处置
          fixed     已按确定性规则修复（见下）
          isolated  无法确定正确值，移出主数据集

处置边界（依据 docs/迭代一_Hadoop数据清洗与Agent基础.md 第 91 行：区分修复/去重/隔离）
--------------------------------------------------------------------------------------
【修复】只有能确定正确值的才修复：
    · 分隔符被替换（, | :）—— 还原后字段数正确
    · 行尾多余字段（::EXTRA_FIELD）—— 该字段不含业务信息
    · 时间戳为毫秒（> 1e11）—— 整除 1000 换算为秒，换算后仍越界则改为隔离
    · Zip-code 为 ZIP+4（NNNNN-NNNN）—— 截取前 5 位
    · 电影标题首尾空白 —— 去除
【隔离】无法确定正确值的，绝不猜：
    · 字段数不符（信息缺失或结构损坏）
    · 标识符非正整数或超出取值域（rules.id_domains）
    · 评分不是 1-5 的整数
    · 时间戳非法（非数字、负值）或换算后仍超出数据集时间范围
    · users：Gender/Age/Occupation/Zip-code 不符合规则声明的取值域

⚠️ 本 mapper 不做去重，也不决定"冲突时保留哪一条"—— 那需要看到同一主键的全部记录，
   由 reducer 完成（见 clean/reducer.py）。

环境变量：
  ML_CLEAN_TABLE  ratings | movies | users
  ML_RULES        rules.json 路径（由 run_clean.sh 通过 -cmdenv 传入）
"""

import sys
import os
import re

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'common'))
import ml_common as ml

TAG_CLEAN = 'clean'
TAG_FIXED = 'fixed'
TAG_ISOLATED = 'isolated'

# 隔离记录的分组键前缀：保证不与业务主键（纯数字/数字::数字）冲突
ISO_PREFIX = b'\x01'

NCOL = {'ratings': 4, 'movies': 3, 'users': 5}

_zip4_re = None


def zip4_re():
    global _zip4_re
    if _zip4_re is None:
        _zip4_re = re.compile(ml.ZIP4_PATTERN)
    return _zip4_re


def _merge(repairs, extra):
    out = list(repairs)
    for e in extra:
        if e not in out:
            out.append(e)
    return out


# ---------------------------------------------------------------------------
# 各表判定
# ---------------------------------------------------------------------------

def clean_ratings(fields, repairs):
    """
    ratings.dat: UserID::MovieID::Rating::Timestamp

    返回 (标签, 原因, 标准化后的字段或 None)
    """
    uid, mid, rat, ts = fields

    # --- 标识符：正整数且在取值域内 ---
    if not ml.in_id_domain('users', uid):
        return TAG_ISOLATED, 'uid_out_of_domain', None
    if not ml.in_id_domain('movies', mid):
        return TAG_ISOLATED, 'mid_out_of_domain', None

    # --- 评分：1-5 的整数 ---
    if not ml.is_digits(rat):
        return TAG_ISOLATED, 'rating_not_integer', None
    rv = ml.parse_int(rat)
    if rv is None or rv < 1 or rv > 5:
        return TAG_ISOLATED, 'rating_out_of_range', None

    # --- 时间戳：可解释 + 单位统一 + 落在数据集区间 ---
    if not ml.is_digits(ts):
        return TAG_ISOLATED, 'timestamp_not_numeric', None
    tv = ml.parse_int(ts)
    if tv is None or tv <= 0:
        return TAG_ISOLATED, 'timestamp_not_positive', None
    if tv > ml.TS_MS_THRESHOLD:
        tv = tv // 1000
        repairs = _merge(repairs, ['timestamp_ms'])
        ts = str(tv).encode('ascii')
    if tv < ml.TS_MIN or tv > ml.TS_MAX:
        return TAG_ISOLATED, 'timestamp_out_of_range', None

    tag = TAG_FIXED if repairs else TAG_CLEAN
    reason = '+'.join(repairs) if repairs else 'ok'
    return tag, reason, [uid, mid, rat, ts]


def clean_movies(fields, repairs):
    """movies.dat: MovieID::Title::Genres"""
    mid, title, genres = fields

    if not ml.in_id_domain('movies', mid):
        return TAG_ISOLATED, 'mid_out_of_domain', None
    if title.strip() == b'':
        return TAG_ISOLATED, 'title_empty', None

    if ml.has_boundary_space(title):
        title = title.strip()
        repairs = _merge(repairs, ['title_space'])

    # --- Genres 域校验（rule-v2 新增）---
    # 依据 rules.genres.valid：出现未识别类别或空项说明该字段不可信，隔离；
    # 内部重复（如 Drama|Drama）语义不变，可确定性去重，属修复。
    items = [g for g in genres.split(b'|')]
    if genres.strip() == b'':
        return TAG_ISOLATED, 'genres_empty', None
    unknown = [g for g in items if ml.to_text(g).strip() not in ml.GENRE_SET]
    if unknown or any(g.strip() == b'' for g in items):
        return TAG_ISOLATED, 'genres_invalid', None
    seen, dedup = set(), []
    for g in items:
        if g in seen:
            repairs = _merge(repairs, ['genres_deduped'])
            continue
        seen.add(g)
        dedup.append(g)
    genres = b'|'.join(dedup)

    tag = TAG_FIXED if repairs else TAG_CLEAN
    reason = '+'.join(repairs) if repairs else 'ok'
    return tag, reason, [mid, title, genres]


def clean_users(fields, repairs):
    """users.dat: UserID::Gender::Age::Occupation::Zip-code"""
    uid, gender, age, occ, zipc = fields

    if not ml.in_id_domain('users', uid):
        return TAG_ISOLATED, 'uid_out_of_domain', None
    if ml.to_text(gender).strip() not in ml.VALID_GENDER:
        return TAG_ISOLATED, 'gender_invalid', None
    if ml.to_text(age).strip() not in ml.VALID_AGE:
        return TAG_ISOLATED, 'age_invalid', None

    if not ml.is_digits(occ):
        return TAG_ISOLATED, 'occupation_invalid', None
    ov = ml.parse_int(occ)
    if ov is None or ov < 0 or ov > 20:
        return TAG_ISOLATED, 'occupation_invalid', None

    # Zip-code：ZIP+4 可确定性截断；其余必须为 5 位数字
    zt = ml.to_text(zipc).strip()
    m = zip4_re().match(zt)
    if m:
        zipc = m.group(1).encode('ascii')
        repairs = _merge(repairs, ['zip4_truncated'])
    elif not (len(zipc) == 5 and ml.is_digits(zipc)):
        return TAG_ISOLATED, 'zipcode_invalid', None

    tag = TAG_FIXED if repairs else TAG_CLEAN
    reason = '+'.join(repairs) if repairs else 'ok'
    return tag, reason, [uid, gender, age, occ, zipc]


CLEANERS = {
    'ratings': (clean_ratings, lambda f: f[0] + b'::' + f[1]),
    'movies': (clean_movies, lambda f: f[0]),
    'users': (clean_users, lambda f: f[0]),
}


def main():
    table = os.environ.get('ML_CLEAN_TABLE', '')
    spec = CLEANERS.get(table)
    if spec is None:
        raise SystemExit(
            '[clean_mapper] 环境变量 ML_CLEAN_TABLE 非法或缺失: %r\n'
            '  必须是 ratings / movies / users 之一。' % table
        )
    cleaner, keyfunc = spec
    ncol = NCOL[table]

    ml.init_rules()

    stdin = sys.stdin.buffer
    out = sys.stdout.buffer
    seq = 0

    for line in stdin:
        original = ml.rstrip_eol(line)
        if original == b'':
            continue

        fields, repairs = ml.split_fields_tolerant(original, ncol)

        if fields is None:
            tag, reason, payload = TAG_ISOLATED, 'field_count_mismatch', None
        else:
            tag, reason, payload = cleaner(fields, repairs)

        if tag == TAG_ISOLATED or payload is None:
            # 隔离记录：唯一分组键，保证各自成组；记录原文原样保留
            seq += 1
            gkey = ISO_PREFIX + ml.to_text(reason).encode('ascii') + b'#' + str(seq).encode('ascii')
            body = original
            tag = TAG_ISOLATED
        else:
            gkey = keyfunc(payload)
            body = b'::'.join(payload)

        # ⚠️ 必须写二进制流。原因见 v1 的教训：用文本流格式化 bytes 会写成 b'...' 字面量，
        #    导致清洗后数据整体损坏（历史事故，勿回退成 '%s' 写法）。
        out.write(gkey + b'\t' + tag.encode('ascii') + b'\t' + reason.encode('ascii')
                  + b'\t' + body + b'\n')


if __name__ == '__main__':
    main()
