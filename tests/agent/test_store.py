# -*- coding: utf-8 -*-
"""任务存储与状态机单测"""

import tempfile
import unittest

import _paths  # noqa: F401
from store import TaskStore
from models import PENDING, RUNNING, SUCCESS, FAILED


class TestTaskStore(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = TaskStore(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def _create(self):
        tid = self.store.new_task_id()
        self.store.create(tid, 'p', {'do_clean': True})
        return tid

    def test_new_task_id_format(self):
        tid = self.store.new_task_id()
        self.assertRegex(tid, r'^task_\d{8}_\d{4}$')
        tid2 = self.store.new_task_id()
        self.assertNotEqual(tid, tid2)

    def test_create_then_pending(self):
        rec = self.store.get(self._create())
        self.assertEqual(rec['status'], PENDING)
        self.assertIsNone(rec['stage'])

    def test_legal_transitions(self):
        tid = self._create()
        self.store.update(tid, status=RUNNING, stage='BEFORE_SCORE')
        self.store.update(tid, stage='CLEANING')          # RUNNING -> RUNNING
        self.store.update(tid, status=SUCCESS, stage='COMPLETED',
                          set_result=True, result={'x': 1})
        self.assertEqual(self.store.get(tid)['status'], SUCCESS)

    def test_terminal_is_frozen(self):
        tid = self._create()
        self.store.update(tid, status=RUNNING)
        self.store.update(tid, status=SUCCESS, set_result=True, result={})
        with self.assertRaises(RuntimeError):
            self.store.update(tid, status=FAILED)

    def test_illegal_transition_rejected(self):
        tid = self._create()
        with self.assertRaises(RuntimeError):
            self.store.update(tid, status=SUCCESS)  # PENDING -> SUCCESS 非法

    def test_persistence_and_restart_marks_interrupted(self):
        tid = self._create()
        self.store.update(tid, status=RUNNING, stage='CLEANING')
        # 模拟重启：新实例从磁盘恢复
        store2 = TaskStore(self.dir.name)
        recovered = store2.load()
        self.assertEqual(recovered, 1)
        rec = store2.get(tid)
        self.assertEqual(rec['status'], FAILED)
        self.assertEqual(rec['error']['code'], 'AGENT_EXECUTION_ERROR')
        self.assertIn('CLEANING', rec['message'])  # 如实写明中断环节

    def test_queue_position(self):
        a, b = self._create(), self._create()
        self.assertEqual(self.store.queue_position(a), 1)
        self.assertEqual(self.store.queue_position(b), 2)
        self.store.update(a, status=RUNNING)
        self.assertEqual(self.store.queue_position(b), 1)
        self.assertIsNone(self.store.queue_position(a))

    def test_result_file_written(self):
        import json
        import os
        tid = self._create()
        self.store.update(tid, status=RUNNING)
        self.store.update(tid, status=SUCCESS, set_result=True,
                          result={'task_id': tid})
        p = os.path.join(self.dir.name, tid + '.json')
        with open(p, encoding='utf-8') as f:
            self.assertEqual(json.load(f)['status'], SUCCESS)


if __name__ == '__main__':
    unittest.main()
