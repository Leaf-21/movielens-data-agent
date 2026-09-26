#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MovieLens 数据质量检查与评分 —— 公共库

设计要点（重要，勿改）：
1. 全部以【字节串 bytes】处理数据。
   原因：ml-1m 为 ISO-8859-1 编码，movies.dat 含 é/è/ü 等字符。
   若用 UTF-8 解码会抛 UnicodeDecodeError 或产生乱码。
   ISO-8859-1 是单字节编码，所有 ASCII 分隔符（: | 换行）都是单字节，
   因此直接用 bytes.split(b'::') 即可正确切分，无需解码。
   只有需要输出人类可读文本时，才用 latin-1 解码。

2. 分隔符固定为 b'::'，字段内不含该序列（标题中的 ':' 是单字符，不构成 '::'）。

3. mapper/reducer 一律走 stdin -> stdout，符合 Hadoop Streaming 接口，
   同时便于本地用 cat | mapper | sort | reducer 直接调试。
"""

import sys
import os
import json

# ---------------------------------------------------------------------------
# 路径与常量
# ---------------------------------------------------------------------------

# 本文件所在目录
COMMON_DIR = os.path.dirname(os.path.abspath(__file__))
# hadoop/ 根目录（common -> src -> hadoop）
HADOOP_DIR = os.path.dirname(os.path.dirname(COMMON_DIR))

# rules.json 的位置。
#
# ⚠️ 为什么不能只靠相对路径推导：
#   Hadoop Streaming 会把 -file 指定的脚本复制到计算节点的临时目录，
#   mapper 运行时 __file__ 指向的是那个临时目录，从它反推 hadoop/config/
#   会得到错误路径（实测得到 .../DaShuJu/config/rules.json，少了仓库目录名）。
#
# 因此优先级为：
#   1. 环境变量 ML_RULES（由 run_check.sh 通过 -cmdenv 显式传入，最可靠）
#   2. 源码树中的 hadoop/config/rules.json（本地直接运行时可用）
# 两个位置都找不到时，load_rules() 会报错退出，而不是静默使用默认值。
_RULES_CANDIDATES = [
    os.path.join(HADOOP_DIR, 'config', 'rules.json'),
    # 兜底：从仓库根推导（适用于 common 被复制到其它位置的情况）
    os.path.join(os.path.dirname(HADOOP_DIR), 'hadoop', 'config', 'rules.json'),
]

CONFIG_PATH = _RULES_CANDIDATES[0]

SEP = b'::'
ENCODING = 'latin-1'          # 即 ISO-8859-1 的 Python 名称

# ratings 中 Timestamp 的合法区间（默认值；init_rules() 会按 rules.json 覆盖）
TS_MIN = 956703932            # 2000-04-25
TS_MAX = 1046454590           # 2003-02-28

# ---------------------------------------------------------------------------
# 由 rules.json 填充的规则常量（须先调用 init_rules()）
# ---------------------------------------------------------------------------

GENRE_SET = None              # set[str] 合法 Genres 类别
VALID_GENDER = frozenset()    # set[str] 合法性别编码
VALID_AGE = frozenset()       # set[str] 合法年龄段编码

# --- rule-v2 新增：解析容错、时间戳单位、标识符取值域、冲突策略 ---
TS_MS_THRESHOLD = 100000000000          # 超过此值判为毫秒时间戳
TOLERATED_SEPARATORS = (b',', b'|', b':')   # 被替换的分隔符候选（按此顺序尝试）
EXTRA_FIELD_MARKERS = (b'EXTRA_FIELD',)     # 行尾多余字段的标记
ZIP4_PATTERN = r'^(\d{5})-\d{4}$'           # ZIP+4，可确定性截取前 5 位
ID_MIN = {}                   # {'users': 1, 'movies': 1, ...}
ID_MAX = {}                   # {'users': 6040, 'movies': 3952}
CONFLICT_POLICY = {}
MATCH_YEAR_RE = None          # movies 标题年份正则（由 rules 编译）

# 五维权重与必需字段定义
WEIGHTS = {}
REQUIRED_FIELDS = {}

# T1 / T2 时间边界（秒）
T1 = None
T2 = None

_RULES_LOADED = False

# ---------------------------------------------------------------------------
# 规则配置加载
# ---------------------------------------------------------------------------

_RULES_CACHE = None


def resolve_rules_path(explicit=None):
    """
    确定 rules.json 的实际路径。

    查找顺序：
      1. 函数参数 explicit
      2. 环境变量 ML_RULES
      3. _RULES_CANDIDATES 中第一个存在的文件
    全部失败时返回 None，由调用方报错。
    """
    if explicit:
        return explicit if os.path.exists(explicit) else None

    env_p = os.environ.get('ML_RULES')
    if env_p:
        return env_p if os.path.exists(env_p) else None

    for p in _RULES_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def load_rules(path=None):
    """加载 rules.json。失败时抛出明确错误，绝不静默使用默认值。"""
    global _RULES_CACHE
    if _RULES_CACHE is not None and path is None:
        return _RULES_CACHE

    p = resolve_rules_path(path)
    if p is None:
        raise SystemExit(
            '[ml_common] 找不到规则配置 rules.json。\n'
            '  已尝试的位置：\n'
            '    ML_RULES 环境变量 = %r\n'
            '    %s\n'
            '  在 Hadoop 上运行时，请确认 run_check.sh 通过 -cmdenv 传入了 ML_RULES，\n'
            '  且 rules.json 已通过 -file 分发到计算节点。'
            % (os.environ.get('ML_RULES'),
               '\n    '.join(_RULES_CANDIDATES))
        )
    with open(p, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    if path is None:
        _RULES_CACHE = cfg
    return cfg


def init_rules(path=None):
    """
    把 rules.json 中的规则加载为模块级常量。
    mapper / reducer 在使用校验函数前必须调用一次。
    使用 'global' 显式赋值，避免各处重复解析 JSON。
    """
    global GENRE_SET, VALID_GENDER, VALID_AGE
    global WEIGHTS, REQUIRED_FIELDS, T1, T2, _RULES_LOADED
    global TS_MIN, TS_MAX, TS_MS_THRESHOLD, TOLERATED_SEPARATORS
    global EXTRA_FIELD_MARKERS, ZIP4_PATTERN, ID_MIN, ID_MAX, CONFLICT_POLICY

    if _RULES_LOADED:
        return

    cfg = load_rules(path)

    GENRE_SET = frozenset(cfg['genres']['valid'])
    VALID_GENDER = frozenset(cfg['users']['valid_gender'])
    VALID_AGE = frozenset(cfg['users']['valid_age'])

    # --- rule-v2：解析与域规则也以 rules.json 为唯一来源 ---
    r = cfg['ratings']
    TS_MIN = int(r['timestamp_min'])
    TS_MAX = int(r['timestamp_max'])
    TS_MS_THRESHOLD = int(r.get('timestamp_ms_threshold', 100000000000))

    p = cfg.get('parsing', {})
    TOLERATED_SEPARATORS = tuple(s.encode('latin-1')
                                 for s in p.get('tolerated_separators', [',', '|', ':']))
    EXTRA_FIELD_MARKERS = tuple(m.encode('latin-1')
                                for m in p.get('extra_field_markers', ['EXTRA_FIELD']))
    ZIP4_PATTERN = cfg['users'].get('zipcode_extended_pattern', r'^(\d{5})-\d{4}$')

    for tbl, dom in cfg.get('id_domains', {}).items():
        if tbl.startswith('_'):
            continue
        ID_MIN[tbl] = int(dom['min'])
        ID_MAX[tbl] = int(dom['max'])

    CONFLICT_POLICY = cfg.get('conflict_policy', {})

    # 过滤掉 _comment 之类的说明性键，只保留真正的规则项。
    # （rules.json 中所有以 '_' 开头的键都是注释，不是数据。）
    raw_weights = {k: v for k, v in cfg['weights'].items() if not k.startswith('_')}
    WEIGHTS = {k: float(v) for k, v in raw_weights.items()}

    # 权重必须能构成完整的一百分制，否则综合分没有意义。
    _ws = sum(WEIGHTS.values())
    if abs(_ws - 1.0) > 1e-6:
        raise SystemExit(
            '[ml_common] rules.json 的 weights 合计为 %.6f，必须等于 1.0。\n'
            '  当前权重: %r' % (_ws, WEIGHTS)
        )
    _must = {'accurate', 'complete', 'unique', 'up_to_date', 'consistent'}
    if set(WEIGHTS) != _must:
        raise SystemExit(
            '[ml_common] weights 的五维键名不符合约定。\n'
            '  缺少: %r\n  多余: %r'
            % (sorted(_must - set(WEIGHTS)), sorted(set(WEIGHTS) - _must))
        )

    REQUIRED_FIELDS = cfg['required_fields']

    t = cfg['time']
    T1 = int(t['T1_epoch'])
    T2 = int(t['T2_epoch'])

    _RULES_LOADED = True


def all_metrics_for(table):
    """
    返回某表需要输出的全部指标名（用于补零）。
    Hadoop Streaming 下，某指标若一条都没命中就不会出现在 reducer 输出里，
    因此必须先声明全集，再在汇总时补 0。
    """
    specs = {
        'ratings': [
            'total', 'lines', 'malformed', 'missing',
            'r_uid_bad', 'r_mid_bad', 'r_rating_bad', 'r_ts_bad',
            'd1_ok', 'd2_ok',
        ],
        'movies': [
            'total', 'malformed', 'missing',
            'm_mid_bad', 'm_title_empty', 'm_year_missing', 'm_year_bad',
            'm_title_space', 'm_title_nonascii',
            'm_genres_empty', 'm_genres_emptyitem', 'm_genres_dup', 'm_genres_unknown',
        ],
        'users': [
            'total', 'malformed', 'missing',
            'u_uid_bad', 'u_gender_bad', 'u_age_bad', 'u_occ_bad', 'u_zip_bad',
            'u_zip_leadingzero',
            'u_filled_gender', 'u_filled_age', 'u_filled_occup', 'u_filled_zipcode',
        ],
    }
    return specs.get(table, [])


# ---------------------------------------------------------------------------
# 基础解析
# ---------------------------------------------------------------------------

def rstrip_eol(line):
    """去掉行尾的 \n 和 \r（CRLF 兼容）。"""
    return line.rstrip(b'\n').rstrip(b'\r')


def split_fields(line):
    """按 b'::' 切分，返回字段列表（bytes）。

    ⚠️ 这是【严格】切分，用于质量检查（before/after 评分口径）。
    分隔符被替换过的行在这里会得到 1 个字段，从而被如实统计为结构异常。
    清洗侧请使用 split_fields_tolerant()，它会在容错后尝试还原记录。
    """
    return rstrip_eol(line).split(SEP)


def split_fields_tolerant(line, ncol):
    """
    清洗用【容错】切分（rule-v2 新增）。

    处理两类可确定性修复的解析问题：
      1. 分隔符被替换：标准分隔符为 '::'，实际可能是 ',' / '|' / ':'
      2. 行尾多余字段：如 `...::EXTRA_FIELD`

    返回 (fields, repairs)：
      fields   —— 字段列表；无法还原为 ncol 个字段时返回 None
      repairs  —— 本次用到的修复动作名称列表（如 ['sep_replaced', 'extra_field']）

    设计原则：只做"能确定原意"的还原。字段数不足（信息缺失）不在此处猜测，
    由调用方判定为隔离。
    """
    repairs = []
    raw = rstrip_eol(line)

    if SEP in raw:
        parts = raw.split(SEP)
    else:
        parts = None
        for cand in TOLERATED_SEPARATORS:
            if cand in raw:
                parts = raw.split(cand)
                repairs.append('sep_replaced')
                break
        if parts is None:
            return None, repairs

    # 行尾多余字段：仅当确实多出字段、且末字段是已知标记或空时才截断
    while len(parts) > ncol and parts[-1] in EXTRA_FIELD_MARKERS:
        parts = parts[:-1]
        repairs.append('extra_field')
    if len(parts) > ncol and parts[-1] == b'':
        parts = parts[:-1]
        repairs.append('extra_field')

    if len(parts) != ncol:
        return None, repairs
    return parts, repairs


def count_nonempty_fields(fields):
    """非空字段个数，用于冲突消解时比较"信息完整度"。"""
    return sum(1 for f in fields if f.strip() != b'')


def in_id_domain(table, value):
    """标识符是否落在 rules.json 声明的取值域内。"""
    lo, hi = ID_MIN.get(table), ID_MAX.get(table)
    if lo is None or hi is None:
        return True
    if not is_positive_int_str(value):
        return False
    v = parse_int(value)
    return v is not None and lo <= v <= hi


def parse_int(b):
    """bytes 转 int；非法返回 None（不抛异常）。"""
    try:
        return int(b)
    except (ValueError, TypeError):
        return None


def to_text(b):
    """bytes -> 可读字符串，用于输出与日志。"""
    if isinstance(b, str):
        return b
    return b.decode(ENCODING, errors='replace')


def ascii_only(s):
    """把字符串中非 ASCII 字符替换为 '?'，保证输出到终端/HDFS 时不乱码。"""
    return ''.join(ch if ord(ch) < 128 else '?' for ch in s)


# ---------------------------------------------------------------------------
# 校验辅助（全部针对 bytes，判断前先转 text 做正则/集合判断）
# ---------------------------------------------------------------------------

def is_digits(b, allow_leading_zero=True):
    """是否为纯数字串。"""
    if not b:
        return False
    if not allow_leading_zero and b[:1] == b'0' and len(b) > 1:
        return False
    return all(48 <= c <= 57 for c in b)


def is_positive_int_str(b):
    """
    是否为正整数字符串（按 docs/evaluation-method.md 的 A1/A2 判据）。
    判据为 ^[1-9][0-9]*$，注意首字符不能是 '0'，因此 '0' 本身不合法。
    """
    if not b:
        return False
    if b[:1] == b'0':
        return False
    return all(48 <= c <= 57 for c in b)


def has_non_ascii(b):
    """是否含非 ASCII 字节（用于 C10 编码检查）。"""
    return any(c > 127 for c in b)


def has_boundary_space(b):
    """是否首尾有空白字符。"""
    if not b:
        return False
    return b[:1] in (b' ', b'\t') or b[-1:] in (b' ', b'\t')


# ---------------------------------------------------------------------------
# 计数器输出（mapper 侧）
# ---------------------------------------------------------------------------

def emit(name, value=1, dim=None):
    """
    输出一条计数记录，格式固定为:  <指标名>\t<数值>
    reducer 依赖此格式，不要改。

    value 必须是整数。需要输出浮点值（如新鲜度均值）请用 emit_float()。
    """
    if isinstance(value, bytes):
        value = to_text(value)
    sys.stdout.write('%s\t%d\n' % (name, int(value)))


def emit_float(name, value, digits=10):
    """
    输出浮点指标，格式为: <指标名>\t<数值>

    为什么需要单独的函数：
      整数指标用 emit() 的 %d 输出即可，但 freshness 均值这类值是实数
      （清洗后实测 0.212159），若用 int() 截断会变成 0，导致该项得分被
      错误计算为 0。

    digits 默认 10 位小数，足以表达本项目的浮点指标精度。
    """
    sys.stdout.write('%s\t%s\n' % (name, ('%.' + str(digits) + 'f') % float(value)))


def read_counters(stream=None):
    """
    读取 '<指标名>\t<数值>' 流，聚合为 dict。
    同时兼容 'ALL\t<指标名>\t<数值>' 三列格式（见下面 emit_all）。
    """
    stream = stream or sys.stdin
    out = {}
    for raw in stream:
        if isinstance(raw, bytes):
            raw = raw.decode(ENCODING)
        raw = raw.rstrip('\n').rstrip('\r')
        if not raw:
            continue
        parts = raw.split('\t')
        if len(parts) == 2:
            key, val = parts
        elif len(parts) == 3:
            # 三列: ALL \t 指标名 \t 数值
            key, val = parts[1], parts[2]
        else:
            continue
        try:
            # 优先按整数解析；失败则按浮点（如新鲜度合计 0.0000001234）。
            # 两者都失败才跳过 —— 这样既保持整数指标的精确性，
            # 又不会把浮点指标静默丢弃。
            try:
                n = int(val)
            except ValueError:
                n = float(val)
        except ValueError:
            continue
        out[key] = out.get(key, 0) + n
    return out


# ---------------------------------------------------------------------------
# JSON 输出
# ---------------------------------------------------------------------------

def dump_json(obj):
    """输出 JSON（UTF-8、缩进 2、保留中文）。"""
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=False))
    sys.stdout.write('\n')
