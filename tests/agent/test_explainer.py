# -*- coding: utf-8 -*-
"""
结果解释单测（模板主路径）。

验证要点（迭代一角色B"结果解释"交付物的硬规则）：
  · 回答中的数字全部来自结果 JSON（夹具数值 99.0/95.04/隔离 1 条等）；
  · 隔离 ≠ 修复的措辞纪律；
  · FAILED 回答必须含环节+原因+指引；
  · 本环境无 LLM，source 必须是 template。
"""

import tempfile
import unittest

import _paths  # noqa: F401
import config
import explainer
import result_builder
from fake_hadoop import AFTER_METRICS  # noqa: F401  (夹具来源标记)
from fake_hadoop import AFTER_SCORES, BEFORE_METRICS, BEFORE_SCORES, CLEAN_STATS
from models import PENDING, RUNNING, SUCCESS, FAILED


def _success_record():
    cfg = config.load_rules()
    state = {
        '_state': 'AFTER_DONE',
        'before_metrics': dict(BEFORE_METRICS),
        'before_scores': dict(BEFORE_SCORES),
        'before_details': {},
        'clean_statistics': dict(CLEAN_STATS),
        'after_metrics': {'ratings_total': 999, 'movies_total': 100,
                          'users_total': 60, 'users_u_zip_bad': 0,
                          'movies_m_title_nonascii': 3},
        'after_scores': dict(AFTER_SCORES),
        'after_details': {},
    }
    result = result_builder.build('task_exp1', state, cfg, True)
    result['status'] = SUCCESS
    return {'task_id': 'task_exp1', 'status': SUCCESS, 'stage': 'COMPLETED',
            'message': '', 'prompt': 'p', 'plan': {'notes': []},
            'error': None, 'result': result,
            'created_at': '', 'updated_at': ''}


class TestAnswerRouting(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.rec = _success_record()

    def _ask(self, q):
        text, source = explainer.answer(self.rec, q)
        self.assertEqual(source, 'template')  # 无 LLM 环境必须是纯模板
        return text

    def test_dimension_question_uses_real_numbers(self):
        text = self._ask('准确性得分怎么样')
        self.assertIn('99.0000', text)   # 清洗前 accurate=99.0
        self.assertIn('100.0000', text)  # 清洗后
        self.assertIn('提升', text)

    def test_isolation_not_fix(self):
        text = self._ask('被隔离的记录算修复了吗')
        self.assertIn('未被修正', text)
        self.assertIn('不能表述为', text)
        self.assertIn('1', text)  # isolated_count=1，数字取自结果

    def test_version_question(self):
        text = self._ask('数据版本和划分是什么')
        self.assertIn('974862386', text)  # T1 epoch 精确值
        self.assertIn('976422054', text)  # T2 epoch 精确值
        self.assertIn('70%', text)

    def test_weights_question(self):
        text = self._ask('权重是多少')
        self.assertIn('设计选择', text)  # 权重不是测量结果的提醒

    def test_limitations_question(self):
        text = self._ask('这套评价有什么局限')
        self.assertIn('局限', text)

    def test_unmatched_falls_back_to_summary(self):
        text = self._ask('你好啊随便问一句')
        self.assertIn('未命中已登记的解释模板', text)
        self.assertIn('综合质量分', text)  # 兜底给摘要

    def test_no_fabricated_numbers(self):
        # 摘要中出现的综合分必须是夹具值，且不得凭空出现真实数据集量级数字
        text = self._ask('总体情况如何')
        self.assertIn('94.6000', text)
        self.assertIn('95.0400', text)
        self.assertNotIn('1010132', text)  # 真实 ml-1m 数值不该出现在夹具回答里


class TestNonSuccessRecords(unittest.TestCase):

    def test_failed_record_explains_stage_and_guidance(self):
        rec = {'task_id': 't', 'status': FAILED, 'stage': 'CLEANING',
               'message': '失败', 'plan': {}, 'created_at': '', 'updated_at': '',
               'error': {'code': 'HADOOP_EXECUTION_ERROR',
                         'message': '模拟：清洗作业执行失败', 'stage': 'CLEANING'},
               'result': None}
        text, source = explainer.answer(rec, '现在怎么样了')
        self.assertEqual(source, 'template')
        self.assertIn('FAILED', text)
        self.assertIn('CLEANING', text)          # 环节
        self.assertIn('清洗作业执行失败', text)   # 原因
        self.assertIn('检查 Hadoop 服务', text)   # 指引

    def test_failed_with_partial_result(self):
        base = _success_record()
        rec = dict(base, status=FAILED,
                   error={'code': 'QUALITY_SCORE_ERROR',
                          'message': '清洗后评分失败', 'stage': 'AFTER_SCORE'})
        text, _ = explainer.answer(rec, '发生了什么')
        self.assertIn('真实结果仍然有效', text)
        self.assertIn('null，不代表 0', text)

    def test_running_record(self):
        rec = {'task_id': 't', 'status': RUNNING, 'stage': 'CLEANING',
               'message': '', 'plan': {'notes': ['将执行清洗']}, 'error': None,
               'result': None, 'created_at': '', 'updated_at': ''}
        text, source = explainer.answer(rec, '得分多少')
        self.assertEqual(source, 'template')
        self.assertIn('尚未完成', text)
        self.assertIn('CLEANING', text)

    def test_pending_record(self):
        rec = {'task_id': 't', 'status': PENDING, 'stage': None,
               'message': '', 'plan': {}, 'error': None, 'result': None,
               'created_at': '', 'updated_at': ''}
        text, _ = explainer.answer(rec, '得分多少')
        self.assertIn('排队中', text)


class TestSummarize(unittest.TestCase):

    def test_summarize_no_cleaning_shows_null_note(self):
        cfg = config.load_rules()
        state = {'before_metrics': dict(BEFORE_METRICS),
                 'before_scores': dict(BEFORE_SCORES), 'before_details': {}}
        result = result_builder.build('task_s', state, cfg, False)
        lines = explainer.summarize(result)
        joined = '\n'.join(lines)
        self.assertIn('未执行清洗', joined)
        self.assertIn('原始数据总量', joined)


if __name__ == '__main__':
    unittest.main()
