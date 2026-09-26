#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务调度器（Agent"任务调度"交付物）

模型：单工作线程 + FIFO 队列（串行调度）。
  迭代一为单用户联调场景；成员A的每个阶段本身要提交/模拟多个
  Hadoop 作业，并行执行只会互相抢资源并把 work_dir 写乱，
  因此串行是最稳的调度策略。多 worker 可在后续迭代平滑扩展
  （接口不变，只改本文件）。

每次阶段跳转都写 store（落盘），前端轮询即可拿到实时进度：
  PENDING -> RUNNING(PARSE_REQUEST) -> BEFORE_SCORE -> [CLEANING
  -> AFTER_SCORE] -> GENERATE_REPORT -> SUCCESS(COMPLETED)

失败语义（接口规范第 6 / 15 / 23 节）：
  任一环节失败 -> FAILED，写明环节 + 错误码 + 原因 + 指引；
  已经成功的环节的结果以"部分结果"形式保留（缺失字段为 null），
  绝不生成占位数值。
"""

import os
import queue
import sys
import threading
import traceback

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

# hadoop_tool 位于 agent/tools/（成员B交付清单指定目录），
# 先入 path 再以顶层模块导入，避免包结构差异影响联调。
_TOOLS_DIR = os.path.join(os.path.dirname(_SRC_DIR), 'tools')
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

import config                        # noqa: E402
import models                        # noqa: E402
from errors import AgentError        # noqa: E402
from hadoop_tool import HadoopToolError  # noqa: E402
import result_builder                # noqa: E402
import explainer                     # noqa: E402


class PipelineScheduler(threading.Thread):
    """FIFO 串行执行器。API 层 submit 后立即可返回（异步任务语义）。"""

    def __init__(self, store, tool, results_dir=None, name='agent-scheduler'):
        super(PipelineScheduler, self).__init__(name=name, daemon=True)
        self.store = store
        self.tool = tool
        self.q = queue.Queue()
        self.results_dir = results_dir or config.RESULTS_DIR
        os.makedirs(self.results_dir, exist_ok=True)
        self._stop = threading.Event()

    # ------------------------------------------------------------------

    def submit(self, task_id):
        self.q.put(task_id)

    def stop(self):
        self._stop.set()
        try:
            self.q.put_nowait(None)
        except Exception:
            pass

    def run(self):
        while not self._stop.is_set():
            task_id = self.q.get()
            if task_id is None:
                break
            try:
                self._execute(task_id)
            except Exception:  # 调度器自身绝不允许因单任务异常而退出
                traceback.print_exc()
            finally:
                self.q.task_done()

    # ------------------------------------------------------------------

    def _set(self, task_id, **kw):
        self.store.update(task_id, **kw)

    def _execute(self, task_id):
        rec = self.store.get(task_id)
        if rec is None:
            return
        plan = rec['plan']
        cfg = config.load_rules()
        stage = models.PARSE_REQUEST
        state = None
        try:
            self._set(task_id, status=models.RUNNING, stage=stage,
                      message=models.STAGE_MESSAGES[stage])

            # ---- 1. 清洗前评分（接口规范第 9 节）----
            stage = models.BEFORE_SCORE
            self._set(task_id, stage=stage,
                      message=models.STAGE_MESSAGES[stage])
            self.tool.quality_score_before(task_id, plan['data_version'],
                                           plan.get('score_config'))
            state = self.tool.read_state(task_id)
            self._require_state(state, ('before_metrics', 'before_scores'), stage)

            # ---- 2/3. 清洗 + 清洗后评分（第 10 / 11 节）----
            if plan['do_clean']:
                stage = models.CLEANING
                self._set(task_id, stage=stage,
                          message=models.STAGE_MESSAGES[stage])
                self.tool.clean_dataset(task_id, plan['data_version'],
                                        plan['rule_version'])
                state = self.tool.read_state(task_id)
                self._require_state(state, ('clean_statistics',), stage)

                stage = models.AFTER_SCORE
                self._set(task_id, stage=stage,
                          message=models.STAGE_MESSAGES[stage])
                # after 接口按第 11 节示例传清洗后版本
                self.tool.quality_score_after(task_id, cfg['output_version'],
                                              plan.get('score_config'))
                state = self.tool.read_state(task_id)
                self._require_state(state, ('after_metrics', 'after_scores'), stage)

            # ---- 4. 汇总与报告（第 13 / 14 节）----
            stage = models.GENERATE_REPORT
            self._set(task_id, stage=stage, message=models.STAGE_MESSAGES[stage])
            result = result_builder.build(task_id, state, cfg, plan['do_clean'])
            result['status'] = models.SUCCESS
            self._write_result_file(task_id, result)

            b_overall = (result['before_score'] or {}).get('overall')
            a_overall = (result.get('after_score') or {}).get('overall')
            msg = '任务执行完成'
            if b_overall is not None:
                msg += '（清洗前综合分 %.4f%s）' % (
                    b_overall,
                    '' if a_overall is None else ' → 清洗后 %.4f' % a_overall)
            self._set(task_id, status=models.SUCCESS, stage=models.COMPLETED,
                      message=msg, set_result=True, result=result,
                      set_error=True, error=None)

        except HadoopToolError as e:
            self._fail(task_id, stage, {'code': e.code, 'message': e.message,
                                        'stage': e.stage or stage,
                                        'detail': e.detail}, state, plan)
        except AgentError as e:
            self._fail(task_id, stage, e.to_dict(), state, plan)
        except Exception as e:
            self._fail(task_id, stage, {
                'code': 'AGENT_EXECUTION_ERROR',
                'message': 'Agent 执行失败: %s' % e,
                'stage': stage,
                'detail': traceback.format_exc()[-2000:],
            }, state, plan)

    # ------------------------------------------------------------------

    def _require_state(self, state, keys, stage):
        """
        状态文件校验：HTTP 响应成功但交接文件缺关键内容时，
        结果不可信，按接口规范第 2.2 节直接失败，不做任何补救。
        """
        if not state or any(k not in state or state[k] is None for k in keys):
            raise AgentError(
                stage, 'QUALITY_SCORE_ERROR',
                'Hadoop 阶段返回成功，但状态交接文件缺少 %s，结果不可信' % list(keys),
                '期望文件: reports/quality-report/<task_id>.json；'
                '实际内容键: %s' % (sorted(state.keys()) if state else '文件不存在'))

    def _fail(self, task_id, stage, err, state, plan):
        """失败落账：写错误 + 如实保留部分结果。"""
        partial = None
        if state and state.get('before_metrics'):
            try:
                cfg = config.load_rules()
                partial = result_builder.build(task_id, state, cfg,
                                               plan.get('do_clean', True))
                partial['status'] = models.FAILED
                partial['_note'] = ('部分结果：%s 环节失败，尚未执行的环节为 null。'
                                    % err.get('stage', stage))
                self._write_result_file(task_id, partial)
            except Exception:
                partial = None
        msg = '任务失败（环节 %s）：%s。%s' % (
            err.get('stage', stage), err.get('message', ''),
            explainer.FAILURE_GUIDANCE.get(err.get('code', ''), ''))
        try:
            self._set(task_id, status=models.FAILED, stage=err.get('stage', stage),
                      message=msg, set_error=True, error=err,
                      set_result=True, result=partial)
        except (KeyError, RuntimeError):
            pass  # 任务已被外部改写为终态时不覆盖

    def _write_result_file(self, task_id, result):
        import json
        p = os.path.join(self.results_dir, task_id + '.json')
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
