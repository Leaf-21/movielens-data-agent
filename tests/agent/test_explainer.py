# -*- coding: utf-8 -*-
"""结果解释单测（大模型主路径，模板已移除）。

团队决定（2026-10-21）：追问的语言表达一律交给大模型，不再用关键词模板。
因此本文件验证的是新契约：

  · 大模型不可用  -> source='unavailable'，文本明确说明不可用，**不伪造答案**
  · 大模型可用    -> source='llm'，且传给模型的证据只含真实结果字段
  · 未完成/已失败 -> source='state'，如实报告状态与失败环节（不消耗模型调用）
  · 分析任务证据  -> assignments 只含本次请求用户、coordinates 只给样例（控体积）
"""

import json
import unittest
from unittest import mock

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


def _analysis_record(gap=False):
    """最小可用的迭代二分析任务记录（聚类）。"""
    assignments = [{'user_id': 1161, 'cluster_id': 0, 'status': 'SUCCESS',
                    'reliability_low': False, 'distance_to_centroid': 1.234},
                   {'user_id': 1162, 'cluster_id': None,
                    'status': 'NO_TRAIN_HISTORY', 'reliability_low': True,
                    'distance_to_centroid': None}]
    if gap:
        # 造一批"请求用户之外"的归属，用于验证证据裁剪
        assignments += [{'user_id': 9000 + i, 'cluster_id': i % 3,
                         'status': 'SUCCESS'} for i in range(500)]
    result = {
        'task_id': 'task_an1', 'task_type': 'clustering', 'status': SUCCESS,
        'data_version': 'movielens-1m-v2-clean-v1', 'profile_version': 'profile-v1',
        'analysis_version': 'iter2-analysis-v1', 'T1': '2000-11-22',
        'T2': '2000-12-10', 'requested_user_ids': [1161, 1162],
        'result_versions': {'clustering_kmeans': 'res-x'},
        'results': [{
            'algorithm': 'kmeans', 'algorithm_tool': 'clustering_kmeans',
            'model_version': 'mdl-x', 'result_version': 'res-x',
            'parameters': {'k': 6},
            'metrics': {'k_selected': 6, 'silhouette_full': 0.11986815299158346,
                        'davies_bouldin_full': 1.9345, 'n_fit_users': 4783},
            'assignments': assignments,
            'cluster_summaries': [{'cluster_id': 0, 'size': 977,
                                   'avg_rating_mean': 3.7609,
                                   'summary_basis': '群内真实统计'}],
            'coordinates': [{'user_id': 1, 'x': 0.1, 'y': 0.2}] * 120,
            'limitations': ['轮廓系数偏低'],
        }],
    }
    return {'task_id': 'task_an1', 'status': SUCCESS, 'stage': 'COMPLETED',
            'task_type': 'clustering', 'message': '', 'plan': {'notes': []},
            'error': None, 'result': result,
            'created_at': '', 'updated_at': ''}


class TestNoModel(unittest.TestCase):
    """没有配置大模型时的行为：明确不可用，绝不编造。"""

    def setUp(self):
        self._p = mock.patch.object(explainer.llm, 'enabled', return_value=False)
        self._p.start()
        self.addCleanup(self._p.stop)

    def test_returns_unavailable_with_explicit_message(self):
        text, source = explainer.answer(_success_record(), '准确性得分怎么样')
        self.assertEqual(source, 'unavailable')
        self.assertIn('未配置可用的语言模型', text)
        self.assertIn('.env', text)          # 给出修法
        # 不能伪造任何答案性内容
        self.assertNotIn('99.0000', text)

    def test_analysis_task_also_unavailable(self):
        text, source = explainer.answer(_analysis_record(), '群体0有什么特征')
        self.assertEqual(source, 'unavailable')
        self.assertIn('未配置可用的语言模型', text)


class TestModelPath(unittest.TestCase):
    """配置了大模型时：答案完全由模型给出，证据只含真实字段。"""

    def setUp(self):
        self._p = mock.patch.object(explainer.llm, 'enabled', return_value=True)
        self._p.start()
        self.addCleanup(self._p.stop)

    def test_answer_comes_from_model(self):
        with mock.patch.object(explainer.llm, 'answer_question',
                               return_value='模型给的回答') as m:
            text, source = explainer.answer(_success_record(), '总体情况如何')
        self.assertEqual(source, 'llm')
        self.assertEqual(text, '模型给的回答')
        self.assertTrue(m.called)

    def test_llm_failure_reports_unavailable_not_fake_answer(self):
        with mock.patch.object(explainer.llm, 'answer_question', return_value=None):
            text, source = explainer.answer(_success_record(), '随便问')
        self.assertEqual(source, 'unavailable')
        self.assertIn('调用语言模型失败', text)

    def test_clean_evidence_carries_real_numbers(self):
        captured = {}

        def fake(q, ev, **kw):
            captured['ev'] = ev
            return 'ok'

        with mock.patch.object(explainer.llm, 'answer_question', side_effect=fake):
            explainer.answer(_success_record(), '得分')
        ev = captured['ev']
        self.assertEqual(ev['before_score'], BEFORE_SCORES)
        self.assertEqual(ev['after_score'], AFTER_SCORES)
        self.assertIn('statistics', ev)
        # 证据里不得凭空出现真实数据集量级数字
        self.assertNotIn('1010132', json.dumps(ev, ensure_ascii=False))

    def test_analysis_evidence_trims_assignments_to_requested_users(self):
        captured = {}

        def fake(q, ev, **kw):
            captured['ev'] = ev
            return 'ok'

        with mock.patch.object(explainer.llm, 'answer_question', side_effect=fake):
            explainer.answer(_analysis_record(gap=True), '用户1161属于哪个群体')
        algo = captured['ev']['algorithms'][0]
        ids = {a['user_id'] for a in algo['assignments']}
        self.assertEqual(ids, {1161, 1162})   # 只保留请求用户
        self.assertNotIn(9000, ids)

    def test_analysis_evidence_coordinates_sampled(self):
        captured = {}

        def fake(q, ev, **kw):
            captured['ev'] = ev
            return 'ok'

        with mock.patch.object(explainer.llm, 'answer_question', side_effect=fake):
            explainer.answer(_analysis_record(), '坐标怎么样')
        algo = captured['ev']['algorithms'][0]
        self.assertEqual(algo['coordinates_count'], 120)
        self.assertEqual(len(algo['coordinates_sample']), 5)
        self.assertNotIn('coordinates', algo)   # 全量坐标不进证据

    def test_analysis_evidence_keeps_key_metrics(self):
        captured = {}

        def fake(q, ev, **kw):
            captured['ev'] = ev
            return 'ok'

        with mock.patch.object(explainer.llm, 'answer_question', side_effect=fake):
            explainer.answer(_analysis_record(), '指标')
        algo = captured['ev']['algorithms'][0]
        self.assertEqual(algo['metrics']['silhouette_full'],
                         0.11986815299158346)
        self.assertEqual(algo['metrics']['n_fit_users'], 4783)
        self.assertEqual(algo['cluster_summaries'][0]['summary_basis'],
                         '群内真实统计')
        # 证据瘦身：metrics 里的说明性长文本不进 prompt（否则 prompt 过大、响应变慢）
        for prose in ('definition', 'k_selection_rule'):
            self.assertNotIn(prose, algo['metrics'])


class TestStateRecords(unittest.TestCase):
    """未完成 / 已失败：如实报告状态，不消耗模型调用。"""

    def test_failed_record_explains_stage_and_guidance(self):
        rec = {'task_id': 't', 'status': FAILED, 'stage': 'CLEANING',
               'message': '失败', 'plan': {}, 'created_at': '', 'updated_at': '',
               'error': {'code': 'HADOOP_EXECUTION_ERROR',
                         'message': '模拟：清洗作业执行失败', 'stage': 'CLEANING'},
               'result': None}
        text, source = explainer.answer(rec, '现在怎么样了')
        self.assertEqual(source, 'state')
        self.assertIn('FAILED', text)
        self.assertIn('CLEANING', text)
        self.assertIn('清洗作业执行失败', text)
        self.assertIn('检查 Hadoop 服务', text)

    def test_failed_with_partial_result(self):
        base = _success_record()
        rec = dict(base, status=FAILED,
                   error={'code': 'QUALITY_SCORE_ERROR',
                          'message': '清洗后评分失败', 'stage': 'AFTER_SCORE'})
        text, source = explainer.answer(rec, '发生了什么')
        self.assertEqual(source, 'state')
        self.assertIn('真实结果仍然有效', text)
        self.assertIn('null，不代表 0', text)

    def test_failed_does_not_call_model(self):
        rec = {'task_id': 't', 'status': FAILED, 'stage': 'CLEANING',
               'message': '失败', 'plan': {}, 'error': {'code': 'INTERNAL_ERROR',
                                                        'message': 'x'},
               'result': None, 'created_at': '', 'updated_at': ''}
        with mock.patch.object(explainer.llm, 'answer_question') as m:
            explainer.answer(rec, '为什么失败')
        self.assertFalse(m.called)

    def test_running_record(self):
        rec = {'task_id': 't', 'status': RUNNING, 'stage': 'CLEANING',
               'message': '', 'plan': {'notes': ['将执行清洗']}, 'error': None,
               'result': None, 'created_at': '', 'updated_at': ''}
        text, source = explainer.answer(rec, '得分多少')
        self.assertEqual(source, 'state')
        self.assertIn('尚未完成', text)
        self.assertIn('CLEANING', text)

    def test_pending_record(self):
        rec = {'task_id': 't', 'status': PENDING, 'stage': None,
               'message': '', 'plan': {}, 'error': None, 'result': None,
               'created_at': '', 'updated_at': ''}
        text, source = explainer.answer(rec, '得分多少')
        self.assertEqual(source, 'state')
        self.assertIn('排队中', text)


class TestSummarize(unittest.TestCase):
    """summarize 仍保留：失败任务的部分结果说明要用它（事实陈述，非模板答案）。"""

    def test_summarize_no_cleaning_shows_null_note(self):
        cfg = config.load_rules()
        state = {'before_metrics': dict(BEFORE_METRICS),
                 'before_scores': dict(BEFORE_SCORES), 'before_details': {}}
        result = result_builder.build('task_s', state, cfg, False)
        joined = '\n'.join(explainer.summarize(result))
        self.assertIn('未执行清洗', joined)
        self.assertIn('原始数据总量', joined)


if __name__ == '__main__':
    unittest.main()
