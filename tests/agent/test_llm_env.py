# -*- coding: utf-8 -*-
"""大模型接入层测试：.env 解析、凭据判定、失败降级、参数兼容。

不访问真实 API：需要客户端的用例一律用假 client 注入，
真实网络调用只在手工联调时发生（见 README「大模型增强层」）。
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

import _paths  # noqa: F401


class TestDotenvParse(unittest.TestCase):

    def setUp(self):
        import dotenv
        self.d = dotenv

    def test_basic_pairs(self):
        got = self.d.parse('A=1\nB=two\n')
        self.assertEqual(got, {'A': '1', 'B': 'two'})

    def test_comments_and_blank_lines_ignored(self):
        got = self.d.parse('# 注释\n\nA=1\n   # 缩进注释\nB=2\n')
        self.assertEqual(got, {'A': '1', 'B': '2'})

    def test_export_prefix(self):
        self.assertEqual(self.d.parse('export A=1\n'), {'A': '1'})

    def test_quoted_values_keep_inner_content(self):
        got = self.d.parse('A="a # not comment"\nB=\'b c\'\n')
        self.assertEqual(got['A'], 'a # not comment')
        self.assertEqual(got['B'], 'b c')

    def test_inline_comment_stripped_when_unquoted(self):
        self.assertEqual(self.d.parse('A=1 # 说明\n')['A'], '1')

    def test_invalid_lines_skipped(self):
        got = self.d.parse('NOEQ\n=1\n1BAD=x\nA=1\n')
        self.assertEqual(got, {'A': '1'})

    def test_empty_value_parsed_as_empty(self):
        self.assertEqual(self.d.parse('A=\n'), {'A': ''})


class TestDotenvLoad(unittest.TestCase):

    def setUp(self):
        import dotenv
        self.d = dotenv
        self.wd = tempfile.TemporaryDirectory()
        self.addCleanup(self.wd.cleanup)
        self.fp = os.path.join(self.wd.name, '.env')

    def _write(self, text):
        with open(self.fp, 'w', encoding='utf-8') as f:
            f.write(text)
        return self.fp

    def test_load_sets_env(self):
        p = self._write('ML_TEST_KEY_ALPHA=hello\n')
        key = 'ML_TEST_KEY_ALPHA'
        os.environ.pop(key, None)
        try:
            loaded = self.d.load([p])
            self.assertEqual(os.environ[key], 'hello')
            self.assertEqual(loaded, {key: 'hello'})
        finally:
            os.environ.pop(key, None)

    def test_existing_env_not_overridden(self):
        p = self._write('ML_TEST_KEY_BETA=from_file\n')
        key = 'ML_TEST_KEY_BETA'
        os.environ[key] = 'from_shell'
        try:
            loaded = self.d.load([p])
            self.assertEqual(os.environ[key], 'from_shell')
            self.assertEqual(loaded, {})
        finally:
            os.environ.pop(key, None)

    def test_override_true_replaces(self):
        p = self._write('ML_TEST_KEY_GAMMA=from_file\n')
        key = 'ML_TEST_KEY_GAMMA'
        os.environ[key] = 'from_shell'
        try:
            self.d.load([p], override=True)
            self.assertEqual(os.environ[key], 'from_file')
        finally:
            os.environ.pop(key, None)

    def test_empty_value_skipped_by_default(self):
        p = self._write('ML_TEST_KEY_DELTA=\n')
        key = 'ML_TEST_KEY_DELTA'
        os.environ.pop(key, None)
        try:
            loaded = self.d.load([p])
            self.assertEqual(loaded, {})
            self.assertNotIn(key, os.environ)
        finally:
            os.environ.pop(key, None)

    def test_missing_file_is_silent(self):
        loaded = self.d.load([os.path.join(self.wd.name, 'nope.env')])
        self.assertEqual(loaded, {})

    def test_candidate_paths_prefers_ml_env_file(self):
        with mock.patch.dict(os.environ, {'ML_ENV_FILE': '/tmp/custom.env'}):
            paths = self.d.candidate_paths()
        self.assertEqual(paths[0], '/tmp/custom.env')


class TestLlmEnabled(unittest.TestCase):

    def setUp(self):
        import llm
        self.llm = llm

    def test_disabled_without_credential(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.object(self.llm, 'AVAILABLE', True):
            self.assertFalse(self.llm.enabled())

    def test_enabled_with_api_key(self):
        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-x'}, clear=True), \
             mock.patch.object(self.llm, 'AVAILABLE', True):
            self.assertTrue(self.llm.enabled())

    def test_enabled_with_auth_token(self):
        with mock.patch.dict(os.environ, {'ANTHROPIC_AUTH_TOKEN': 'tok'}, clear=True), \
             mock.patch.object(self.llm, 'AVAILABLE', True):
            self.assertTrue(self.llm.enabled())

    def test_disabled_when_sdk_missing(self):
        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-x'}, clear=True), \
             mock.patch.object(self.llm, 'AVAILABLE', False):
            self.assertFalse(self.llm.enabled())

    def test_ml_llm_disable_kills_it(self):
        env = {'ANTHROPIC_API_KEY': 'sk-x', 'ML_LLM_DISABLE': '1'}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(self.llm, 'AVAILABLE', True):
            self.assertFalse(self.llm.enabled())

    def test_empty_credential_counts_as_absent(self):
        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': ''}, clear=True), \
             mock.patch.object(self.llm, 'AVAILABLE', True):
            self.assertFalse(self.llm.enabled())


class TestLlmDiagnose(unittest.TestCase):

    def setUp(self):
        import llm
        self.llm = llm

    def test_masks_credential(self):
        env = {'ANTHROPIC_API_KEY': 'sk-ant-abcdefghijklmnop'}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(self.llm, 'AVAILABLE', True):
            d = self.llm.diagnose()
        self.assertEqual(d['credential_var'], 'ANTHROPIC_API_KEY')
        self.assertIn('***', d['credential_masked'])
        self.assertNotIn('abcdefghijklmnop', d['credential_masked'])

    def test_never_leaks_full_key(self):
        secret = 'sk-ant-SUPERSECRETVALUE0123456789'
        env = {'ANTHROPIC_API_KEY': secret}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(self.llm, 'AVAILABLE', True):
            d = self.llm.diagnose()
        for v in d.values():
            self.assertNotIn(secret, str(v))

    def test_reports_missing_credential(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.object(self.llm, 'AVAILABLE', True):
            d = self.llm.diagnose()
        self.assertIsNone(d['credential_var'])
        self.assertIsNone(d['credential_masked'])
        self.assertFalse(d['enabled'])


class _FakeMessages(object):
    def __init__(self, reject_output_config=False):
        self.reject = reject_output_config
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.reject and 'output_config' in kwargs:
            raise TypeError("create() got an unexpected keyword argument 'output_config'")
        return mock.Mock(stop_reason='end_turn',
                         content=[mock.Mock(type='text', text='OK')])


class _FakeClient(object):
    def __init__(self, reject_output_config=False):
        self.messages = _FakeMessages(reject_output_config)


class TestLlmCall(unittest.TestCase):

    def setUp(self):
        import llm
        self.llm = llm
        self._orig_use = llm._USE_OUTPUT_CONFIG
        self.addCleanup(setattr, llm, '_USE_OUTPUT_CONFIG', self._orig_use)

    def test_returns_none_without_client(self):
        with mock.patch.object(self.llm, '_get_client', return_value=None):
            self.assertIsNone(self.llm._call('sys', 'user'))

    def test_normal_call_returns_text(self):
        fake = _FakeClient()
        with mock.patch.object(self.llm, '_get_client', return_value=fake):
            self.llm._USE_OUTPUT_CONFIG = True
            self.assertEqual(self.llm._call('sys', 'user'), 'OK')
        self.assertIn('output_config', fake.messages.calls[0])

    def test_output_config_rejected_then_retried(self):
        """服务端不认 output_config 时，应去掉该参数重试一次并永久关闭。"""
        fake = _FakeClient(reject_output_config=True)
        with mock.patch.object(self.llm, '_get_client', return_value=fake):
            self.llm._USE_OUTPUT_CONFIG = True
            self.assertEqual(self.llm._call('sys', 'user'), 'OK')
            self.assertFalse(self.llm._USE_OUTPUT_CONFIG)
        self.assertEqual(len(fake.messages.calls), 2)
        self.assertIn('output_config', fake.messages.calls[0])
        self.assertNotIn('output_config', fake.messages.calls[1])

    def test_api_error_returns_none(self):
        fake = mock.Mock()
        fake.messages.create.side_effect = RuntimeError('boom: network down')
        with mock.patch.object(self.llm, '_get_client', return_value=fake):
            self.assertIsNone(self.llm._call('sys', 'user'))

    def test_untrusted_stop_reason_returns_none(self):
        fake = mock.Mock()
        fake.messages.create.return_value = mock.Mock(
            stop_reason='refusal', content=[mock.Mock(type='text', text='x')])
        with mock.patch.object(self.llm, '_get_client', return_value=fake):
            self.assertIsNone(self.llm._call('sys', 'user'))

    def test_param_rejection_detector(self):
        self.assertTrue(self.llm._is_param_rejection(
            TypeError("unexpected keyword argument 'output_config'")))
        self.assertTrue(self.llm._is_param_rejection(
            RuntimeError('unknown parameter: effort')))
        self.assertFalse(self.llm._is_param_rejection(
            RuntimeError('401 authentication_error')))


class TestLlmPublicApi(unittest.TestCase):

    def setUp(self):
        import llm
        self.llm = llm

    def test_classify_intent_none_when_disabled(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(self.llm.classify_intent('清洗一下数据'))

    def test_answer_question_none_when_disabled(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(self.llm.answer_question('群体2是什么', {}))

    def test_classify_intent_parses_json_with_fence(self):
        env = {'ANTHROPIC_API_KEY': 'sk-x'}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(self.llm, 'AVAILABLE', True), \
             mock.patch.object(self.llm, '_call',
                               return_value='```json\n{"do_clean": true, "confidence": "high"}\n```'):
            self.assertEqual(self.llm.classify_intent('清洗并评估'),
                             {'do_clean': True})

    def test_classify_intent_bad_json_returns_none(self):
        env = {'ANTHROPIC_API_KEY': 'sk-x'}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(self.llm, 'AVAILABLE', True), \
             mock.patch.object(self.llm, '_call', return_value='抱歉我无法判断'):
            self.assertIsNone(self.llm.classify_intent('随便什么'))


if __name__ == '__main__':
    unittest.main()
