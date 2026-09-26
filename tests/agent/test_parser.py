# -*- coding: utf-8 -*-
"""需求解析单测（纯规则路径；本环境 LLM 不可用，llm_used 必为 False）"""

import unittest

import _paths  # noqa: F401
import parser as req_parser


class TestBuildPlan(unittest.TestCase):

    def test_default_prompt_full_pipeline(self):
        plan = req_parser.build_plan(
            '请使用默认规则清洗 MovieLens 1M，评估清洗前后的五个数据质量维度。',
            'movielens-1m-v2', 'rule-v2')
        self.assertTrue(plan['do_clean'])
        self.assertEqual(plan['clean_intent_source'], 'rule')
        self.assertFalse(plan['llm_used'])
        self.assertEqual(plan['data_version'], 'movielens-1m-v2')
        self.assertEqual(plan['rule_version'], 'rule-v2')

    def test_evaluate_only(self):
        for p in ('只评估数据质量，不清洗', '先别清洗，给我看看五维评分',
                  'run a score-only job'):
            plan = req_parser.build_plan(p, 'movielens-1m-v2', 'rule-v2')
            self.assertFalse(plan['do_clean'], p)

    def test_no_keyword_falls_back_to_default(self):
        plan = req_parser.build_plan('帮我处理一下这批 MovieLens 数据',
                                     'movielens-1m-v2', 'rule-v2')
        # 本环境 llm 不可用 -> 默认完整流程，且来源标注为 default（可追溯）
        self.assertTrue(plan['do_clean'])
        self.assertIn(plan['clean_intent_source'], ('default', 'llm'))

    def test_focus_dimensions(self):
        plan = req_parser.build_plan(
            '重点看完整性和重复问题，其余维度顺带', 'movielens-1m-v2', 'rule-v2')
        self.assertIn('complete', plan['focus_dimensions'])
        self.assertIn('unique', plan['focus_dimensions'])
        # 顺序稳定，按五维固定顺序输出
        self.assertEqual(plan['focus_dimensions'],
                         [d for d in req_parser.DIM_ORDER
                          if d in plan['focus_dimensions']])

    def test_versions_from_prompt_recorded_but_request_wins(self):
        plan = req_parser.build_plan(
            '用 rule-v3 清洗 movielens-1m-v2', 'movielens-1m-v2', 'rule-v2')
        self.assertEqual(plan['rule_version'], 'rule-v2')  # 请求字段优先
        self.assertTrue(any('rule-v3' in n for n in plan['notes']))

    def test_prompt_version_used_when_request_missing(self):
        dv, rv = req_parser.detect_versions('对 movielens-1m-v2 应用 rule-v2')
        self.assertEqual(dv, 'movielens-1m-v2')
        self.assertEqual(rv, 'rule-v2')

    def test_score_config_passthrough(self):
        sc = {'accurate': True, 'complete': True, 'unique': True,
              'up_to_date': True, 'consistent': True}
        plan = req_parser.build_plan('清洗', 'movielens-1m-v2', 'rule-v2', sc)
        self.assertEqual(plan['score_config'], sc)


class TestDetectVersions(unittest.TestCase):

    def test_clean_version_regex(self):
        dv, _ = req_parser.detect_versions('输入 movielens-1m-v2-clean-v1')
        self.assertEqual(dv, 'movielens-1m-v2-clean-v1')

    def test_absent(self):
        self.assertEqual(req_parser.detect_versions('随便看看'), (None, None))


if __name__ == '__main__':
    unittest.main()
