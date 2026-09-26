# -*- coding: utf-8 -*-
"""
结果组装单测。

夹具数据来自 fake_hadoop.py（测试专用，非真实执行结果），
重点验证三件事：
  1. 第 13 节字段齐备、算术正确（score_change、statistics 透传）；
  2. 未执行的环节必须是 null 而不是 0（接口规范第 2.2 节红线）；
  3. problems/unresolved 复用成员A的映射表且 unresolved 采用
     after 指标口径（成员B设计决定，见 pipeline_bridge 注释）。
"""

import unittest

import _paths  # noqa: F401
import config
import result_builder
from fake_hadoop import (AFTER_METRICS, AFTER_SCORES, BEFORE_METRICS,
                         BEFORE_SCORES, CLEAN_STATS)
from errors import AgentError


def _state(with_clean=True, with_after=True):
    state = {
        '_state': 'BEFORE_DONE',
        'before_metrics': dict(BEFORE_METRICS),
        'before_scores': dict(BEFORE_SCORES),
        'before_details': {'accurate': {'checks': 12}},
    }
    if with_clean:
        state['_state'] = 'CLEAN_DONE'
        state['clean_statistics'] = dict(CLEAN_STATS)
    if with_after:
        state['_state'] = 'AFTER_DONE'
        state['after_metrics'] = dict(AFTER_METRICS)
        state['after_scores'] = dict(AFTER_SCORES)
        state['after_details'] = {}
    return state


class TestBuild(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.cfg = config.load_rules()

    def test_full_result_contract_fields(self):
        r = result_builder.build('task_t1', _state(), self.cfg, True)
        for key in ('task_id', 'stage', 'data_version', 'rule_version',
                    'T1', 'T2', 'before_score', 'after_score', 'score_change',
                    'statistics', 'problems', 'unresolved_problems', 'report'):
            self.assertIn(key, r)  # 接口规范第 13 节必需字段

    def test_versions_and_time_boundaries(self):
        r = result_builder.build('task_t1', _state(), self.cfg, True)
        self.assertEqual(r['input_version'], 'movielens-1m-v2')
        self.assertEqual(r['data_version'], 'movielens-1m-v2-clean-v1')
        self.assertEqual(r['T1_epoch'], 974862386)   # 与 rules.json 一致（epoch 必须精确）
        self.assertEqual(r['T2_epoch'], 976422054)
        self.assertEqual(r['T1'], '2000-11-22')
        self.assertEqual(r['T2'], '2000-12-10')
        self.assertEqual(r['rule_version'], 'rule-v2')

    def test_score_change_arithmetic(self):
        r = result_builder.build('task_t1', _state(), self.cfg, True)
        self.assertEqual(r['score_change']['accurate'], 1.0)     # 100-99
        self.assertEqual(r['score_change']['consistent'], 0.3)   # 98.3-98
        self.assertEqual(r['score_change']['unique'], 0.0)
        self.assertEqual(r['score_change']['up_to_date'], 0.0)

    def test_statistics_passthrough(self):
        r = result_builder.build('task_t1', _state(), self.cfg, True)
        st = r['statistics']
        self.assertEqual(st['before_count'], CLEAN_STATS['before_count'])
        self.assertEqual(st['after_count'], CLEAN_STATS['after_count'])
        self.assertEqual(st['fixed_count'], 4)
        self.assertEqual(st['isolated_count'], 1)
        # 隔离 != 修复：两个计数必须独立存在，不被合并
        self.assertNotEqual(st['fixed_count'], st['isolated_count'])
        # rule-v2：主键冲突三个统计字段必须透传（否则前端看不到未解决冲突）
        self.assertEqual(st['conflict_count'], CLEAN_STATS['conflict_count'])
        self.assertEqual(st['conflict_key_count'], CLEAN_STATS['conflict_key_count'])
        self.assertEqual(st['conflict_record_count'],
                         CLEAN_STATS['conflict_record_count'])

    def test_problems_and_unresolved(self):
        r = result_builder.build('task_t1', _state(), self.cfg, True)
        codes = [p['code'] for p in r['problems']]
        self.assertIn('users_u_zip_bad', codes)             # before 中 5 条
        self.assertIn('movies_m_title_nonascii', codes)
        # after 指标中 zip_bad=0；nonascii 是 keep，也不算未解决。
        # 但主键冲突只存在于清洗统计中（after 指标看不出），必须显式补入。
        self.assertEqual([p['code'] for p in r['unresolved_problems']],
                         ['clean_conflict_keys'])
        self.assertEqual(r['unresolved_problems'][0]['count'],
                         CLEAN_STATS['conflict_key_count'])
        # report.unresolved 与之一致（成员A的构建函数生成）
        self.assertEqual([p['code'] for p in r['report']['unresolved']],
                         ['clean_conflict_keys'])

    def test_report_structure(self):
        r = result_builder.build('task_t1', _state(), self.cfg, True)
        rep = r['report']
        for key in ('method', 'improvements', 'unresolved', 'limitations'):
            self.assertIn(key, rep)  # 接口规范第 14 节
        self.assertEqual(len(rep['improvements']), 5)
        self.assertEqual(rep['method']['rule_version'], 'rule-v2')
        self.assertTrue(rep['limitations'])  # 来自成员A的固定文案

    def test_before_only_has_nulls_not_zeros(self):
        r = result_builder.build('task_t1', _state(with_clean=False,
                                                   with_after=False),
                                 self.cfg, False)
        self.assertIsNone(r['after_score']['accurate'])
        self.assertIsNone(r['score_change']['accurate'])
        st = r['statistics']
        self.assertIsNone(st['after_count'])
        self.assertIsNone(st['fixed_count'])
        self.assertIn('_note', st)  # 明确解释为什么是 null
        # 未清洗时 unresolved 按 before 口径：zip_bad 计划处置
        self.assertIn('users_u_zip_bad',
                      [p['code'] for p in r['unresolved_problems']])
        self.assertEqual(r['data_version'], 'movielens-1m-v2')
        self.assertIsNone(r['output_version'])

    def test_clean_done_but_after_failed(self):
        r = result_builder.build('task_t1', _state(with_after=False),
                                 self.cfg, True)
        self.assertIsNone(r['after_score']['overall'])
        # 清洗统计已产生，仍如实保留
        self.assertEqual(r['statistics']['isolated_count'], 1)

    def test_missing_before_raises(self):
        with self.assertRaises(AgentError):
            result_builder.build('task_t1', {}, self.cfg, True)


if __name__ == '__main__':
    unittest.main()
