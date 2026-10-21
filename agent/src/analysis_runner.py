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
    cmd = [sys.executable, '-I', tool_file,
           '--request', req_path, '--output', out_path]
    timeout = float(entry.get('timeout_s', 600))
    last = None
    for attempt in (1, 2):
        t0 = time.time()
        # 每次尝试前清掉旧输出，避免把残留/半截文件误当本轮结果
        if os.path.exists(out_path):
            os.remove(out_path)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=timeout)
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
    raise AnalysisError(
        'ALGORITHM_ERROR',
        '%s 子进程执行失败（已重试）: %s' % (algo, last[0] if last else '未知原因'),
        {'algorithm': algo, 'exit': last[1] if last else None,
         'stderr_tail': (last[2] if last else '')[-1500:]})


def _profile_stage(store, task_id):
    """PROFILE_BUILD：确保画像已构建/可复用（子进程隔离同规则，重试一次）。"""
    store.update(task_id, stage=models.PROFILE_BUILD,
                 message=models.STAGE_MESSAGES[models.PROFILE_BUILD])
    acfg = config.load_analysis()
    script = os.path.join(_TOOLS_DIR, 'clustering', 'build_profile.py')
    last_err = None
    for _ in (1, 2):
        try:
            proc = subprocess.run([sys.executable, '-I', script],
                                  capture_output=True, text=True, timeout=300)
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
