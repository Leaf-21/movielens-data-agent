#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
迭代二分析任务执行器（成员B）

调度语义（接口扩展规范 §五）：
  PENDING -> RUNNING(PARSE_REQUEST) -> PROFILE_BUILD -> CLUSTER_FIT
          -> GENERATE_REPORT -> SUCCESS(COMPLETED)
任一环节失败 -> FAILED，error 用规范 §2.1 登记码，绝不伪造 SUCCESS。

工程要点（本机实测，见 reports/analysis 运行报告）：
  · 聚类工具在**子进程**执行（python3 -I <tool> --request --output），
    WSL2+Python3.10 环境存在非确定性解释器级崩溃（dmesg signal 11 记录），
    隔离 + 自动重试 1 次保证 API 服务恒存活、单任务可恢复；
  · 超时取 analysis.json 算法条目 timeout_s；超时/崩溃/非零退出 -> 重试一次；
  · 工具返回的信封原样进入 results[]，Agent 层不改写任何算法数值
    （任务书 §3），只做必需键校验；
  · 请求/输出的中间文件放 agent/runtime/analysis/{task_id}/（gitignore 覆盖）。
"""

import json
import os
import re
import site as _site
import subprocess
import sys
import time
import traceback

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)
_TOOLS_DIR = os.path.join(os.path.dirname(_SRC_DIR), 'tools')
for _p in (_TOOLS_DIR, os.path.join(_TOOLS_DIR, 'clustering')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config                      # noqa: E402
import models                      # noqa: E402
import registry                    # noqa: E402
from common import AnalysisError   # noqa: E402

RUNTIME_ANALYSIS_DIR = os.path.join(config.AGENT_DIR, 'runtime', 'analysis')

# ---------------------------------------------------------------------------
# 工具子进程：`-I` 隔离 + 第三方依赖可见性（2026-10-21 修复的两处环境缺陷）
# ---------------------------------------------------------------------------
# 缺陷一（依赖不可见）：工具按接口规范以 `python3 -I` 启动（隔离模式保证 WSL
#   的段错误只影响子进程，不带走 API 服务）。但 `-I` 隐含 `-s`，**不含用户级
#   site-packages**；当 numpy / scikit-learn 由 `pip install --user` 装在
#   `~/.local/lib/pythonX.Y/site-packages` 时，分类与降维工具在 import 阶段就
#   ModuleNotFoundError，被上层折叠成 "ALGORITHM_ERROR 子进程执行失败（已重试）"，
#   现象像"工具坏了"，实际只是解释器静态路径问题（聚类工具纯标准库，不受影响）。
#   处置：仍用 `-I` 起子进程，但在 `-c` 引导脚本里把用户级站点目录**追加**回
#   sys.path 后 runpy 执行工具本体 —— 既保留进程隔离，又不依赖依赖装在哪。
#   引导脚本刻意不把工具所在目录塞进 sys.path：`-I` 的语义就是"不含脚本目录"，
#   各工具自己显式入径（文件头注释），这里保持原有隔离语义不变。
#   其它目录可用 ML_TOOL_EXTRA_PATH（os.pathsep 分隔）追加。
# 缺陷二（快照路径不一致）：聚类工具读 analysis.json 的 input.clean_dir
#   （= hadoop/output/clean），而分类/降维走 agent/tools/common/split.py 的
#   clean_dir()，默认是 data/<清洗版本>/。两处默认值不同，"三类任务读同一份
#   清洗快照"这条口径在默认配置下并不成立，分类/降维直接 DATA_UNAVAILABLE。
#   处置：子进程环境里以 analysis.json 的登记值为准注入 ML_CLEAN_DIR
#   （调用方显式设置的 ML_CLEAN_DIR 优先，绝不覆盖）。
_TOOL_BOOTSTRAP = (
    'import os, runpy, sys\n'
    '_extra = sys.argv[1]\n'
    'for _p in _extra.split(os.pathsep):\n'
    '    if _p and _p not in sys.path:\n'
    '        sys.path.append(_p)\n'
    'sys.argv = sys.argv[2:]\n'
    'runpy.run_path(os.path.abspath(sys.argv[0]), run_name="__main__")\n'
)


def tool_search_paths():
    """工具子进程需要额外可见的依赖目录：存在的、去重、保序。"""
    cands = []
    extra = os.environ.get('ML_TOOL_EXTRA_PATH')
    if extra:
        cands.extend(extra.split(os.pathsep))
    try:
        user_site = _site.getusersitepackages()
    except Exception:                      # pragma: no cover - 极端解释器
        user_site = None
    if isinstance(user_site, (list, tuple)):
        cands.extend(user_site)
    elif user_site:
        cands.append(user_site)
    out = []
    for p in cands:
        p = (p or '').strip()
        if p and os.path.isdir(p) and p not in out:
            out.append(p)
    return out


def tool_command(tool_file, *args):
    """工具子进程命令行：`-I` 隔离 + 引导脚本补依赖路径。"""
    return [sys.executable, '-I', '-c', _TOOL_BOOTSTRAP,
            os.pathsep.join(tool_search_paths()), tool_file] + list(args)


def tool_env():
    """工具子进程环境：按 analysis.json 统一清洗快照路径（显式 env 优先）。"""
    env = dict(os.environ)
    if not env.get('ML_CLEAN_DIR'):
        try:
            p = config.resolve_repo_path(config.load_analysis()['input']['clean_dir'])
        except (KeyError, TypeError, RuntimeError):
            p = None
        if p and os.path.isdir(p):
            env['ML_CLEAN_DIR'] = p
    env.setdefault('PYTHONIOENCODING', 'utf-8')
    return env


# 工具信封必需键（缺任何一个都视为工具违约 -> ALGORITHM_ERROR，不入库假结果）
COMMON_ENV_KEYS = ('algorithm', 'algorithm_tool', 'model_version', 'result_version',
                   'parameters', 'data_version', 'profile_version', 'T1', 'T2',
                   'code_version', 'created_at', 'limitations')
CATEGORY_ENV_KEYS = {
    'clustering': ('metrics', 'assignments', 'cluster_summaries'),
    'classification': ('metrics', 'results'),
    'dimensionality_reduction': (
        'original_dimensions', 'reduced_dimensions', 'information_retention',
        'resource_usage', 'coordinates', 'clustering_comparison',
    ),
}
REQUIRED_ENV_KEYS = COMMON_ENV_KEYS + CATEGORY_ENV_KEYS['clustering']


def required_env_keys(category):
    return COMMON_ENV_KEYS + CATEGORY_ENV_KEYS.get(category, ())


# 第三方依赖缺失的识别：`-I` 子进程若连 numpy 都导入不了，真实原因是
# "依赖没装"或"装在解释器看不到的位置"，但原始报错只是一行 ModuleNotFoundError，
# 被折叠成"子进程执行失败"后很难判断该改什么。这里识别出来并给出可操作提示。
_IMPORT_ERROR_RE = re.compile(r"ModuleNotFoundError:\s*No module named '([^']+)'")


def missing_dependency(stderr):
    """从工具子进程 stderr 里取缺失的顶层模块名；没有则返回 None。"""
    if not stderr:
        return None
    m = _IMPORT_ERROR_RE.search(stderr)
    return m.group(1).split('.')[0] if m else None


def dependency_hint(module):
    """依赖缺失时的可操作提示（区分"没装"与"装错位置"两种情况）。"""
    return ('分析工具的第三方依赖 %r 在子进程里不可用。'
            '子进程仍以 `-I` 启动（隔离模式，避免 WSL2 段错误带走 API 服务），'
            '调度器已自动把用户级 site-packages 补进 sys.path，因此常见原因只有两个：'
            '① 本机确实没装 —— 执行 `python3 -m pip install -r requirements.txt`；'
            '② 装在解释器默认路径之外 —— 用环境变量 `ML_TOOL_EXTRA_PATH` 指向该目录'
            '（多个目录用 %r 分隔）后重试。'
            '排查:`python3 -c "import %s"` 与 `python3 -I -c "import %s"` 对比即可定位。'
            % (module, os.pathsep, module, module))


def _task_workdir(task_id):
    d = os.path.join(RUNTIME_ANALYSIS_DIR, task_id)
    os.makedirs(d, exist_ok=True)
    return d


def _run_tool_subprocess(entry, algo, task_id, payload, log_lines,
                         category='clustering'):
    """子进程执行一个工具，含崩溃/超时重试一次。返回信封 dict。"""
    tool_file = registry.module_file(entry)
    if not os.path.exists(tool_file):
        raise AnalysisError('MODEL_NOT_FOUND',
                            '注册表指向的工具文件不存在: %s' % tool_file)
    work = _task_workdir(task_id)
    req_path = os.path.join(work, 'request-%s.json' % algo)
    out_path = os.path.join(work, 'result-%s.json' % algo)
    with open(req_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False)
    cmd = tool_command(tool_file, '--request', req_path,
                      '--output', out_path)
    child_env = tool_env()
    timeout = float(entry.get('timeout_s', 600))
    last = None
    for attempt in (1, 2):
        t0 = time.time()
        # 每次尝试前清掉旧输出，避免把残留/半截文件误当本轮结果
        if os.path.exists(out_path):
            os.remove(out_path)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=timeout, env=child_env)
        except subprocess.TimeoutExpired:
            last = ('超时(%.0fs)' % timeout, -1, '')
            log_lines.append('%s 第%d次尝试超时' % (algo, attempt))
            continue
        wall = int((time.time() - t0) * 1000)
        stdout = (proc.stdout or '').strip()
        stderr = (proc.stderr or '').strip()
        if proc.returncode == 0 and os.path.exists(out_path):
            try:
                with open(out_path, 'r', encoding='utf-8') as f:
                    env = json.load(f)
            except ValueError as e:
                last = ('输出信封不可解析: %s' % e, proc.returncode, stderr)
                continue
            missing = [k for k in required_env_keys(category) if k not in env]
            if missing:
                raise AnalysisError('ALGORITHM_ERROR',
                                    '工具信封缺少必需字段: %s（工具违约，拒收）' % missing,
                                    {'algorithm': algo, 'missing': missing})
            env['_execution'] = {'mode': 'subprocess', 'attempt': attempt,
                                 'wall_ms': wall}
            log_lines.append('%s 第%d次尝试成功(%dms)' % (algo, attempt, wall))
            return env
        # 工具主动失败（退出码 2 + stdout JSON）：语义错误，不重试
        if proc.returncode == 2:
            try:
                fail = json.loads(stdout.splitlines()[-1])
            except (ValueError, IndexError):
                fail = None
            if fail and fail.get('status') == 'FAILED':
                err = fail['error']
                raise AnalysisError(err.get('code', 'ALGORITHM_ERROR'),
                                    err.get('message', '工具失败'),
                                    err.get('details'))
        if proc.returncode < 0:      # 被信号杀死（含本机实测的 segfault）
            last = ('进程被信号 %d 终止（环境级崩溃）' % -proc.returncode,
                    proc.returncode, stderr)
            log_lines.append('%s 第%d次尝试崩溃: %s' % (algo, attempt, last[0]))
            continue
        if proc.returncode != 0:
            last = ('退出码 %d' % proc.returncode, proc.returncode, stderr)
            log_lines.append('%s 第%d次尝试失败: %s' % (algo, attempt, last[0]))
            continue
        last = ('退出 0 但输出文件缺失', 0, stderr)
    reason = last[0] if last else '未知原因'
    stderr_tail = (last[2] if last else '')
    detail = {'algorithm': algo,
              'exit': last[1] if last else None,
              'stderr_tail': stderr_tail[-1500:]}
    module = missing_dependency(stderr_tail)
    if module:
        # 依赖缺失是环境问题，不是算法失败：错误消息直接给出修法，
        # 并在 detail 里单列 missing_module 便于前端/排查脚本识别。
        detail['missing_module'] = module
        raise AnalysisError(
            'ALGORITHM_ERROR',
            '%s 子进程执行失败（已重试）：%s' % (algo, dependency_hint(module)),
            detail)
    raise AnalysisError(
        'ALGORITHM_ERROR',
        '%s 子进程执行失败（已重试）: %s' % (algo, reason),
        detail)


def _profile_stage(store, task_id):
    """PROFILE_BUILD：确保画像已构建/可复用（子进程隔离同规则，重试一次）。"""
    store.update(task_id, stage=models.PROFILE_BUILD,
                 message=models.STAGE_MESSAGES[models.PROFILE_BUILD])
    acfg = config.load_analysis()
    script = os.path.join(_TOOLS_DIR, 'clustering', 'build_profile.py')
    last_err = None
    for _ in (1, 2):
        try:
            proc = subprocess.run(tool_command(script),
                                  capture_output=True, text=True,
                                  timeout=300, env=tool_env())
        except subprocess.TimeoutExpired:
            last_err = '画像构建超时'
            continue
        if proc.returncode == 0:
            return
        last_err = '画像构建失败: %s' % ((proc.stdout + proc.stderr)[-800:])
    raise AnalysisError('DATA_UNAVAILABLE', last_err)


def tool_payload(category, plan, algo):
    """runner -> 工具的统一 payload（分类额外注入算法名与预测目标）。

    分类工具是一个文件服务 gnb/cart 两个登记条目，子进程里拿不到 entry，
    必须由 payload 显式告知跑哪个算法（缺了它工具会返回 INVALID_PARAMETER）。
    """
    payload = {
        'user_ids': plan['user_ids'],
        'parameters': plan['parameters_by_algorithm'].get(algo, {}),
        'data_version': plan['data_version'],
        'profile_version': plan['profile_version'],
    }
    if category == 'classification':
        payload.update(plan.get('classification_target') or {})
        payload['algorithm'] = algo
    return payload


def run_task(store, task_id, results_dir):
    """
    执行一个分析任务（由调度线程按 task_type 分发进来）。
    本函数自己负责状态落账；抛出的异常一律兜底成 FAILED，调度线程不崩。
    """
    rec = store.get(task_id)
    if rec is None:
        return
    plan = rec['plan']
    category = plan['task_type']
    acfg = config.load_analysis()
    rcfg = config.load_rules()
    stage = models.PARSE_REQUEST
    results = []
    log_lines = []
    t_start = time.time()
    try:
        store.update(task_id, status=models.RUNNING, stage=stage,
                     message=models.STAGE_MESSAGES[stage])

        # ---- 画像 ----
        _profile_stage(store, task_id)

        # ---- 逐算法拟合 ----
        store.update(task_id, stage=models.CLUSTER_FIT,
                     message=models.STAGE_MESSAGES[models.CLUSTER_FIT])
        for algo in plan['algorithms']:
            entry = registry.require(category, algo, acfg)
            payload = tool_payload(category, plan, algo)
            results.append(_run_tool_subprocess(entry, algo, task_id, payload,
                                                log_lines, category=category))

        # ---- 装配任务级结果（规范 §4.2：Agent 透传，不改写算法数值）----
        stage = models.GENERATE_REPORT
        store.update(task_id, stage=stage, message=models.STAGE_MESSAGES[stage])
        tb = config.time_boundaries(rcfg)
        result = {
            'task_id': task_id,
            'task_type': category,
            'status': models.SUCCESS,
            'analysis_version': acfg['analysis_version'],
            'data_version': plan['data_version'],
            'profile_version': plan['profile_version'],
            'T1': tb['T1'], 'T2': tb['T2'],
            'T1_epoch': tb['T1_epoch'], 'T2_epoch': tb['T2_epoch'],
            'requested_user_ids': plan['user_ids'],
            'results': results,
            'result_versions': {r['algorithm_tool']: r['result_version']
                                for r in results},
            'code_version': results[0]['code_version'] if results else None,
            'understanding': plan['notes'],
            'execution': {'mode': 'subprocess_isolated',
                          'total_wall_ms': int((time.time() - t_start) * 1000),
                          'log': log_lines},
            'created_at': rec['created_at'],
            '_assembled_by': 'agent/analysis(成员B)',
        }
        _write_result_file(results_dir, task_id, result)
        store.update(task_id, status=models.SUCCESS, stage=models.COMPLETED,
                     message='分析任务完成（%s：%s）' % (
                         category, '、'.join(r['algorithm_tool'] for r in results)),
                     set_result=True, result=result,
                     set_error=True, error=None)
    except AnalysisError as e:
        _fail(store, task_id, stage, {'code': e.code, 'message': e.message,
                                      'stage': stage,
                                      'detail': json.dumps(e.details, ensure_ascii=False)
                                      if e.details else None},
              results, results_dir, t_start, log_lines, rec)
    except Exception as e:
        _fail(store, task_id, stage, {
            'code': 'INTERNAL_ERROR', 'message': '分析任务内部错误: %s' % e,
            'stage': stage, 'detail': traceback.format_exc()[-2000:]},
            results, results_dir, t_start, log_lines, rec)


def _fail(store, task_id, stage, err, results, results_dir, t_start, log_lines, rec):
    """失败落账：保留已完成算法的真实部分结果，缺失字段如实为 null。"""
    partial = None
    if results:
        partial = {
            'task_id': task_id, 'status': models.FAILED,
            'task_type': rec['plan']['task_type'],
            'results': results,
            '_note': '部分结果：%s 环节失败，未完成的算法不在 results 中。' % stage,
            'execution': {'total_wall_ms': int((time.time() - t_start) * 1000),
                          'log': log_lines},
        }
        _write_result_file(results_dir, task_id, partial)
    try:
        store.update(task_id, status=models.FAILED, stage=err.get('stage', stage),
                     message='任务失败（环节 %s）：%s' % (
                         err.get('stage', stage), err.get('message', '')),
                     set_error=True, error=err,
                     set_result=True, result=partial)
    except (KeyError, RuntimeError):
        pass  # 已是终态不覆盖（与迭代一调度器同规则）


def _write_result_file(results_dir, task_id, result):
    p = os.path.join(results_dir, task_id + '.json')
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)
