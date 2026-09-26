#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务状态存储与状态机管理

对应分工文档"状态管理"交付物。

设计：
  · 内存 dict + 线程锁：调度线程与 HTTP 线程并发读写。
  · 每次状态变更原子落盘到 agent/runtime/tasks/{task_id}.json
    （先写 .tmp 再 rename），保证崩溃后重启可恢复到最后一个状态。
  · 重启恢复：磁盘上仍处于 PENDING/RUNNING 的任务【不假装能继续】，
    一律改写为 FAILED（code=AGENT_EXECUTION_ERROR，说明中断环节）。
    依据接口规范第 2.2 节 —— 宁可如实报失败，不产生虚假进度。
  · 任务状态机的合法迁移集中在本模块校验（models.STATUSES/STAGES），
    调度层无法把任务跳到一个非法状态。

task_id 形如 task_20260926_0001（日期 + 当日序号），与成员A状态文件
reports/quality-report/{task_id}.json 使用同一标识，三个环节天然对齐。
"""

import datetime
import json
import os
import threading

try:
    from models import (PENDING, RUNNING, SUCCESS, FAILED, is_terminal,
                        COMPLETED)
except ImportError:  # pragma: no cover
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from models import (PENDING, RUNNING, SUCCESS, FAILED, is_terminal,
                        COMPLETED)


def _atomic_write_json(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


class TaskStore(object):
    """线程安全的任务表；record 是普通 dict，字段见 create()。"""

    def __init__(self, tasks_dir, now_fn=None):
        self.tasks_dir = tasks_dir
        self._lock = threading.RLock()
        self._tasks = {}
        self._reserved = set()  # 已发放但未落账的 id，防止并发创建撞号
        self._now = now_fn or (lambda: datetime.datetime.now(datetime.timezone.utc))
        os.makedirs(tasks_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # 启动恢复
    # ------------------------------------------------------------------

    def load(self):
        """加载历史任务记录；未完成任务如实标记为中断失败。"""
        recovered = 0
        with self._lock:
            for name in sorted(os.listdir(self.tasks_dir)):
                if not name.endswith('.json'):
                    continue
                p = os.path.join(self.tasks_dir, name)
                try:
                    with open(p, 'r', encoding='utf-8') as f:
                        rec = json.load(f)
                except (ValueError, OSError):
                    continue  # 损坏的记录不阻塞启动，也不计入可查任务
                if rec.get('status') in (PENDING, RUNNING):
                    stage = rec.get('stage') or '未知环节'
                    rec['status'] = FAILED
                    rec['message'] = ('任务失败：Agent 服务在 %s 环节运行期间被重启，'
                                      '该任务已中断，无法继续。请重新提交。' % stage)
                    rec['error'] = {
                        'code': 'AGENT_EXECUTION_ERROR',
                        'message': '服务重启导致任务中断',
                        'stage': stage,
                    }
                    _atomic_write_json(p, rec)
                    recovered += 1
                self._tasks[rec['task_id']] = rec
        return recovered

    # ------------------------------------------------------------------
    # 标识生成
    # ------------------------------------------------------------------

    def new_task_id(self):
        """task_YYYYMMDD_NNNN，当日序号递增。"""
        day = self._now().strftime('%Y%m%d')
        prefix = 'task_%s_' % day
        with self._lock:
            seq = 1 + sum(1 for t in self._tasks
                          if t.startswith(prefix))
            while (prefix + '%04d' % seq) in self._tasks or \
                    (prefix + '%04d' % seq) in self._reserved:
                seq += 1
            tid = prefix + '%04d' % seq
            self._reserved.add(tid)
            return tid

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(self, task_id, prompt, plan, message='任务已创建，等待调度'):
        rec = {
            'task_id': task_id,
            'status': PENDING,
            'stage': None,
            'message': message,
            'prompt': prompt,
            'plan': plan,
            'error': None,
            'result': None,
            'created_at': self._now().strftime('%Y-%m-%dT%H:%M:%SZ'),
            'updated_at': self._now().strftime('%Y-%m-%dT%H:%M:%SZ'),
        }
        with self._lock:
            if task_id in self._tasks:
                raise ValueError('task_id 已存在: %s' % task_id)
            self._reserved.discard(task_id)
            self._tasks[task_id] = rec
            self._persist(rec)
        return rec

    def _persist(self, rec):
        _atomic_write_json(os.path.join(self.tasks_dir, rec['task_id'] + '.json'), rec)

    def get(self, task_id):
        with self._lock:
            rec = self._tasks.get(task_id)
            return dict(rec) if rec else None

    def update(self, task_id, status=None, stage=None, message=None,
               error=None, result=None, set_error=False, set_result=False):
        """
        状态迁移入口。

        合法迁移：
          PENDING -> RUNNING / FAILED
          RUNNING -> RUNNING(换阶段) / SUCCESS / FAILED
          SUCCESS/FAILED 为终态，拒绝再改（防止结果被覆盖）。
        error/result 需显式 set_* 标志才能写入/清空 —— 因为 None 本身
        是合法取值（如成功任务 error=None），不能用"缺省即不动"表达。
        """
        with self._lock:
            rec = self._tasks.get(task_id)
            if rec is None:
                raise KeyError('任务不存在: %s' % task_id)
            if is_terminal(rec['status']):
                raise RuntimeError('任务 %s 已处于终态 %s，拒绝迁移' %
                                   (task_id, rec['status']))
            if status is not None:
                ok = {
                    PENDING: {RUNNING, FAILED},
                    RUNNING: {RUNNING, SUCCESS, FAILED},
                }[rec['status']]
                if status not in ok:
                    raise RuntimeError('非法状态迁移: %s -> %s' %
                                       (rec['status'], status))
                rec['status'] = status
            if stage is not None:
                rec['stage'] = stage
            if message is not None:
                rec['message'] = message
            if set_error:
                rec['error'] = error
            if set_result:
                rec['result'] = result
            rec['updated_at'] = self._now().strftime('%Y-%m-%dT%H:%M:%SZ')
            self._persist(rec)
            return dict(rec)

    def list_summary(self):
        """供 GET /api/tasks 使用的轻量列表（不含 result 大对象）。"""
        with self._lock:
            out = []
            for rec in sorted(self._tasks.values(),
                              key=lambda r: r['created_at']):
                out.append({k: rec.get(k) for k in
                            ('task_id', 'status', 'stage', 'message',
                             'created_at', 'updated_at')})
            return out

    def pending_ids(self):
        """队列快照：仍在排队的任务（PENDING），按创建顺序。"""
        with self._lock:
            return [r['task_id'] for r in
                    sorted(self._tasks.values(), key=lambda x: x['created_at'])
                    if r['status'] == PENDING]

    def queue_position(self, task_id):
        """任务在等待队列中的位置（1 起）；不在队列返回 None。"""
        ids = self.pending_ids()
        return ids.index(task_id) + 1 if task_id in ids else None
