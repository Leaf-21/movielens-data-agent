#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
格式检查 —— Mapper（Hadoop Streaming）

职责：逐条读取原始记录，按表类型做字段级合法性检查，输出计数器。

输入：stdin，每行一条原始记录（bytes，ISO-8859-1）
输出：stdout，格式为  <指标名>\t<数值>

表类型由环境变量 ML_TABLE 指定：ratings | movies | users

对应指标编号见 docs/evaluation-method.md 第 4 节：
  A1-A4  ratings 字段合法性
  A5-A8  users 字段合法性
  A9-A10 movies 标题合法性
  C7     Genres 内部重复/空项
  C8     Genres 类别合法性
  C9     Zip-code 格式
  C10    编码非 ASCII（标题特殊字符）
  以及各表的字段数检查（结构完整性）
"""

import sys
import os
import re

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'common'))
import ml_common as ml


# 标题结尾的年份形如 "(1995)"，允许其后有空白
TITLE_YEAR_RE = re.compile(r'\((\d{4})\)\s*$')

# 判据来自 docs/evaluation-method.md 的 A10：年份须落在 1900-2003
YEAR_MIN, YEAR_MAX = 1900, 2003


def check_ratings(fields, out):
    """ratings.dat: UserID::MovieID::Rating::Timestamp"""
    if len(fields) != 4:
        out['malformed'] = out.get('malformed', 0) + 1
    out['lines'] = out.get('lines', 0) + 1

    # 记录总数本身作为分母使用
    out['total'] = out.get('total', 0) + 1

    uid, mid, rat, ts = (fields + [b''] * 4)[:4]

    # --- 必需字段缺失（A1/A2/A3/A4 的缺失部分）---
    # 因已按 :: 切分，空字段表现为空 bytes
    if uid == b'' or mid == b'' or rat == b'' or ts == b'':
        out['missing'] = out.get('missing', 0) + 1

    # --- A1 UserID 为正整数 ---
    if not ml.is_positive_int_str(uid):
        out['r_uid_bad'] = out.get('r_uid_bad', 0) + 1

    # --- A2 MovieID 为正整数 ---
    if not ml.is_positive_int_str(mid):
        out['r_mid_bad'] = out.get('r_mid_bad', 0) + 1

    # --- A3 Rating 为 1-5 的整数 ---
    rating_ok = False
    if ml.is_digits(rat):
        v = ml.parse_int(rat)
        if v is not None and 1 <= v <= 5:
            rating_ok = True
    if not rating_ok:
        out['r_rating_bad'] = out.get('r_rating_bad', 0) + 1

    # --- A4 Timestamp 可解释且落在实测区间内（D1/D2/D3）---
    ts_ok = False
    if ml.is_digits(ts):
        t = ml.parse_int(ts)
        if t is not None and t > 0:
            out['d1_ok'] = out.get('d1_ok', 0) + 1
            if ml.TS_MIN <= t <= ml.TS_MAX:
                ts_ok = True
                out['d2_ok'] = out.get('d2_ok', 0) + 1
    if not ts_ok:
        out['r_ts_bad'] = out.get('r_ts_bad', 0) + 1
    return out


def check_movies(fields, out):
    """movies.dat: MovieID::Title::Genres"""
    if len(fields) != 3:
        out['malformed'] = out.get('malformed', 0) + 1
    out['total'] = out.get('total', 0) + 1

    mid, title, genres = (fields + [b''] * 3)[:3]

    # --- 必需字段缺失 ---
    if mid == b'' or title == b'':
        out['missing'] = out.get('missing', 0) + 1

    # --- A2 MovieID 为正整数（movies 侧）---
    if not ml.is_positive_int_str(mid):
        out['m_mid_bad'] = out.get('m_mid_bad', 0) + 1

    # --- A9 Title 非空 ---
    if title.strip() == b'':
        out['m_title_empty'] = out.get('m_title_empty', 0) + 1

    # --- A10 Title 结尾含 (YYYY)，且年份在 1900-2003 ---
    tm = TITLE_YEAR_RE.search(ml.to_text(title))
    if tm is None:
        out['m_year_missing'] = out.get('m_year_missing', 0) + 1
    else:
        y = int(tm.group(1))
        if y < YEAR_MIN or y > YEAR_MAX:
            out['m_year_bad'] = out.get('m_year_bad', 0) + 1

    # --- C10 Title 首尾空白 / 非 ASCII 特殊字符 ---
    if ml.has_boundary_space(title):
        out['m_title_space'] = out.get('m_title_space', 0) + 1
    if ml.has_non_ascii(title):
        out['m_title_nonascii'] = out.get('m_title_nonascii', 0) + 1

    # --- C7/C8 Genres ---
    if genres.strip() == b'':
        # Genres 缺失不计入必需字段，单独统计
        out['m_genres_empty'] = out.get('m_genres_empty', 0) + 1
    else:
        parts = [p.strip() for p in genres.split(b'|')]
        # C7 内部空项
        if any(p == b'' for p in parts):
            out['m_genres_emptyitem'] = out.get('m_genres_emptyitem', 0) + 1
        # C7 内部重复项
        seen = set()
        dup = False
        for p in parts:
            if p in seen:
                dup = True
                break
            seen.add(p)
        if dup:
            out['m_genres_dup'] = out.get('m_genres_dup', 0) + 1
        # C8 类别合法性
        if ml.GENRE_SET is not None:
            bad = [p for p in parts if ml.to_text(p) not in ml.GENRE_SET]
            if bad:
                out['m_genres_unknown'] = out.get('m_genres_unknown', 0) + 1
    return out


def check_users(fields, out):
    """users.dat: UserID::Gender::Age::Occupation::Zip-code"""
    if len(fields) != 5:
        out['malformed'] = out.get('malformed', 0) + 1
    out['total'] = out.get('total', 0) + 1

    uid, gender, age, occ, zipc = (fields + [b''] * 5)[:5]

    # --- 必需字段缺失：users 只有 UserID 是必需 ---
    if uid == b'':
        out['missing'] = out.get('missing', 0) + 1

    # --- A1 UserID 为正整数 ---
    if not ml.is_positive_int_str(uid):
        out['u_uid_bad'] = out.get('u_uid_bad', 0) + 1

    # --- A5 Gender ∈ {M, F} ---
    if ml.to_text(gender) not in ml.VALID_GENDER:
        out['u_gender_bad'] = out.get('u_gender_bad', 0) + 1

    # --- A6 Age ∈ {1,18,25,35,45,50,56} ---
    if ml.to_text(age) not in ml.VALID_AGE:
        out['u_age_bad'] = out.get('u_age_bad', 0) + 1

    # --- A7 Occupation 为 0-20 的整数 ---
    if not ml.is_digits(occ):
        out['u_occ_bad'] = out.get('u_occ_bad', 0) + 1
    else:
        v = ml.parse_int(occ)
        if v is None or v < 0 or v > 20:
            out['u_occ_bad'] = out.get('u_occ_bad', 0) + 1

    # --- A8 / C9 Zip-code 为 5 位数字 ---
    if not (len(zipc) == 5 and ml.is_digits(zipc)):
        out['u_zip_bad'] = out.get('u_zip_bad', 0) + 1
    # 前导零单独统计（这不是问题，用于证明按字符串读取正确）
    if zipc[:1] == b'0':
        out['u_zip_leadingzero'] = out.get('u_zip_leadingzero', 0) + 1
    # 属性类字段的填充率（不计入扣分）
    for nm, v in (('gender', gender), ('age', age), ('occup', occ), ('zipcode', zipc)):
        if v.strip() != b'':
            out['u_filled_' + nm] = out.get('u_filled_' + nm, 0) + 1
    return out


CHECKERS = {
    'ratings': check_ratings,
    'movies': check_movies,
    'users': check_users,
}


def main():
    table = os.environ.get('ML_TABLE', '')
    checker = CHECKERS.get(table)
    if checker is None:
        raise SystemExit(
            '[check_mapper] 环境变量 ML_TABLE 非法或缺失: %r\n'
            '  必须是 ratings / movies / users 之一。' % table
        )

    # 载入规则（同时初始化 Genres 类别集合等常量）
    ml.load_rules()
    ml.init_rules()

    out = {}
    stdin = sys.stdin.buffer
    for line in stdin:
        fields = ml.split_fields(line)
        # 空行跳过（不计入总数）
        if len(fields) == 1 and fields[0] == b'':
            continue
        checker(fields, out)

    for k, v in out.items():
        ml.emit(k, v)


if __name__ == '__main__':
    main()
