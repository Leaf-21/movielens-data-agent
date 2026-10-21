# -*- coding: utf-8 -*-
"""大模型接入层测试：.env 解析、多服务商解析、凭据判定、失败降级。

不访问真实 API：所有网络出口（_post_json）一律 mock，
真实联调只在手工执行时发生（见 README「大模型增强层」）。
"""

import os
import tempfile
import unittest
from unittest import mock

import _paths  # noqa: F401


_CLEAN_ENV = ('ML_LLM_PROVIDER', 'ML_LLM_API_KEY', 'ML_LLM_BASE_URL',
              'ML_LLM_MODEL', 'ML_LLM_TIMEOUT', 'ML_LLM_MAX_RETRIES',
              'ML_LLM_TEMPERATURE', 'ML_LLM_DISABLE',
              'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_BASE_URL',
              'OPENAI_API_KEY')


class _EnvMixin(object):
    """把 LLM 相关的环境变量清空后再注入给定值，避免本机 .env 干扰。"""

    def patch_env(self, **env):
        clean = {k: '' for k in _CLEAN_ENV}
        clean.update({k: v for k, v in env.items() if v is not None})
        # 用空串表示“存在但为空”，再让被测代码按空值处理；更彻底的做法是删除
        ctx = mock.patch.dict(os.environ, clean, clear=False)
        start = ctx.start()
        self.addCleanup(ctx.stop)
        for k, v in list(os.environ.items()):
            if k in _CLEAN_ENV and v == '':
                os.environ.pop(k, None)
        return start


class TestDotenvParse(unittest.TestCase):

    def setUp(self):
        import dotenv
        self.d = dotenv

    def test_basic_pairs(self):
        self.assertEqual(self.d.parse('A=1\nB=two\n'), {'A': '1', 'B': 'two'})

    def test_comments_and_blank_lines(self):
        got = self.d.parse('# 注释\n\nA=1\n   # 缩进注释\nB=2\n')
        self.assertEqual(got, {'A': '1', 'B': '2'})

    def test_export_prefix(self):
        self.assertEqual(self.d.parse('export A=1\n'), {'A': '1'})

    def test_quoted_values_keep_inner(self):
        got = self.d.parse('A="a # not comment"\nB=\'b c\'\n')
        self.assertEqual(got['A'], 'a # not comment')
        self.assertEqual(got['B'], 'b c')

    def test_inline_comment_stripped(self):
        self.assertEqual(self.d.parse('A=1 # 说明\n')['A'], '1')

    def test_invalid_lines_skipped(self):
        self.assertEqual(self.d.parse('NOEQ\n=1\n1BAD=x\nA=1\n'), {'A': '1'})

    def test_empty_value(self):
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
        p = self._write('ML_TEST_ALPHA=hello\n')
        os.environ.pop('ML_TEST_ALPHA', None)
        try:
            self.assertEqual(self.d.load([p]), {'ML_TEST_ALPHA': 'hello'})
            self.assertEqual(os.environ['ML_TEST_ALPHA'], 'hello')
        finally:
            os.environ.pop('ML_TEST_ALPHA', None)

    def test_existing_env_wins(self):
        p = self._write('ML_TEST_BETA=from_file\n')
        os.environ['ML_TEST_BETA'] = 'from_shell'
        try:
            self.assertEqual(self.d.load([p]), {})
            self.assertEqual(os.environ['ML_TEST_BETA'], 'from_shell')
        finally:
            os.environ.pop('ML_TEST_BETA', None)

    def test_override_true(self):
        p = self._write('ML_TEST_GAMMA=from_file\n')
        os.environ['ML_TEST_GAMMA'] = 'from_shell'
        try:
            self.d.load([p], override=True)
            self.assertEqual(os.environ['ML_TEST_GAMMA'], 'from_file')
        finally:
            os.environ.pop('ML_TEST_GAMMA', None)

    def test_empty_value_not_injected(self):
        p = self._write('ML_TEST_DELTA=\n')
        os.environ.pop('ML_TEST_DELTA', None)
        try:
            self.assertEqual(self.d.load([p]), {})
            self.assertNotIn('ML_TEST_DELTA', os.environ)
        finally:
            os.environ.pop('ML_TEST_DELTA', None)

    def test_missing_file_silent(self):
        self.assertEqual(self.d.load([os.path.join(self.wd.name, 'no.env')]), {})


class TestProviderResolve(_EnvMixin, unittest.TestCase):

    def setUp(self):
        import llm
        self.llm = llm

    def test_no_credential_returns_none(self):
        self.patch_env()
        self.assertIsNone(self.llm.resolve())
        self.assertFalse(self.llm.enabled())

    def test_anthropic_auto_detected(self):
        self.patch_env(ANTHROPIC_API_KEY='sk-ant-xxxxxxxxxxxx')
        cfg = self.llm.resolve()
        self.assertEqual(cfg['provider'], 'anthropic')
        self.assertEqual(cfg['protocol'], 'anthropic')
        self.assertEqual(cfg['model'], 'claude-opus-5')
        self.assertIn('anthropic.com', cfg['base_url'])

    def test_openai_auto_detected(self):
        self.patch_env(OPENAI_API_KEY='sk-openai-xxxxxxxx')
        cfg = self.llm.resolve()
        self.assertEqual(cfg['provider'], 'openai')
        self.assertEqual(cfg['protocol'], 'openai')

    def test_explicit_provider_wins(self):
        self.patch_env(ML_LLM_API_KEY='k-1234567890', ML_LLM_PROVIDER='deepseek')
        cfg = self.llm.resolve()
        self.assertEqual(cfg['provider'], 'deepseek')
        self.assertEqual(cfg['protocol'], 'openai')
        self.assertEqual(cfg['model'], 'deepseek-chat')
        self.assertIn('deepseek.com', cfg['base_url'])

    def test_unified_key_beats_provider_specific(self):
        self.patch_env(ML_LLM_KEY_UNUSED='x', ML_LLM_API_KEY='unified-key-abcdef',
                       ANTHROPIC_API_KEY='sk-ant-specific-key')
        cfg = self.llm.resolve()
        self.assertEqual(cfg['api_key'], 'unified-key-abcdef')
        self.assertEqual(cfg['key_var'], 'ML_LLM_API_KEY')

    def test_custom_base_url_and_model_override(self):
        self.patch_env(ML_LLM_API_KEY='k-1234567890', ML_LLM_PROVIDER='qwen',
                       ML_LLM_BASE_URL='https://my-gateway.example.com/v1',
                       ML_LLM_MODEL='my-model')
        cfg = self.llm.resolve()
        self.assertEqual(cfg['base_url'], 'https://my-gateway.example.com/v1')
        self.assertEqual(cfg['model'], 'my-model')

    def test_unknown_provider_reports_error(self):
        self.patch_env(ML_LLM_API_KEY='k-1234567890', ML_LLM_PROVIDER='nosuch')
        cfg = self.llm.resolve()
        self.assertIn('error', cfg)
        self.assertFalse(self.llm.enabled())
        self.assertIn('未知服务商', self.llm.diagnose()['reason'])

    def test_ollama_works_without_key(self):
        self.patch_env(ML_LLM_PROVIDER='ollama')
        cfg = self.llm.resolve()
        self.assertEqual(cfg['provider'], 'ollama')
        self.assertTrue(self.llm.enabled())

    def test_all_documented_providers_have_presets(self):
        for name in ('anthropic', 'openai', 'deepseek', 'qwen',
                     'moonshot', 'zhipu', 'ollama'):
            self.assertIn(name, self.llm.PROVIDERS)
            proto, base, model = self.llm.PROVIDERS[name]
            self.assertIn(proto, ('anthropic', 'openai'))
            self.assertTrue(base.startswith('http'))
            self.assertTrue(model)


class TestDiagnose(_EnvMixin, unittest.TestCase):

    def setUp(self):
        import llm
        self.llm = llm

    def test_masks_credential(self):
        self.patch_env(ANTHROPIC_API_KEY='sk-ant-abcdefghijklmnop')
        d = self.llm.diagnose()
        self.assertTrue(d['enabled'])
        self.assertIn('***', d['credential_masked'])
        self.assertNotIn('abcdefghijklmnop', d['credential_masked'])

    def test_never_leaks_full_key(self):
        secret = 'sk-ant-SUPERSECRETVALUE0123456789'
        self.patch_env(ANTHROPIC_API_KEY=secret)
        d = self.llm.diagnose()
        for v in d.values():
            self.assertNotIn(secret, str(v))

    def test_reason_when_unconfigured(self):
        self.patch_env()
        d = self.llm.diagnose()
        self.assertFalse(d['enabled'])
        self.assertIn('未配置', d['reason'])
        # 未配置时也应告诉调用方支持哪些服务商，便于排障
        for name in ('anthropic', 'openai', 'deepseek'):
            self.assertIn(name, d['supported_providers'])

    def test_disable_flag(self):
        self.patch_env(ANTHROPIC_API_KEY='sk-ant-abcdefghijklmnop',
                       ML_LLM_DISABLE='1')
        d = self.llm.diagnose()
        self.assertFalse(d['enabled'])
        self.assertIn('ML_LLM_DISABLE', d['reason'])

    def test_base_url_host_only_no_path(self):
        self.patch_env(ML_LLM_API_KEY='k-1234567890', ML_LLM_PROVIDER='openai',
                       ML_LLM_BASE_URL='https://gw.example.com/v1/secret-path')
        d = self.llm.diagnose()
        self.assertEqual(d['base_url_host'], 'gw.example.com')
        self.assertNotIn('secret-path', str(d))


class TestCallDispatch(_EnvMixin, unittest.TestCase):

    def setUp(self):
        import llm
        self.llm = llm

    def test_returns_none_when_disabled(self):
        self.patch_env()
        self.assertIsNone(self.llm._call('sys', 'user'))

    def test_anthropic_payload_shape(self):
        self.patch_env(ANTHROPIC_API_KEY='sk-ant-abcdefghijklmnop')
        canned = {'stop_reason': 'end_turn',
                  'content': [{'type': 'text', 'text': 'hello'}]}
        captured = {}

        def fake_post(url, body, headers, timeout):
            captured.update(url=url, body=body, headers=headers)
            return canned

        with mock.patch.object(self.llm, '_post_json', side_effect=fake_post):
            self.assertEqual(self.llm._call('S', 'U'), 'hello')
        self.assertTrue(captured['url'].endswith('/v1/messages'))
        self.assertEqual(captured['body']['system'], 'S')
        self.assertEqual(captured['body']['messages'][0]['content'], 'U')
        self.assertIn('x-api-key', captured['headers'])
        self.assertIn('anthropic-version', captured['headers'])

    def test_openai_payload_shape(self):
        self.patch_env(ML_LLM_API_KEY='k-1234567890', ML_LLM_PROVIDER='deepseek')
        canned = {'choices': [{'finish_reason': 'stop',
                               'message': {'content': 'hi'}}]}
        captured = {}

        def fake_post(url, body, headers, timeout):
            captured.update(url=url, body=body, headers=headers)
            return canned

        with mock.patch.object(self.llm, '_post_json', side_effect=fake_post):
            self.assertEqual(self.llm._call('S', 'U'), 'hi')
        self.assertTrue(captured['url'].endswith('/chat/completions'))
        self.assertEqual(captured['body']['messages'][0]['role'], 'system')
        self.assertEqual(captured['body']['messages'][1]['role'], 'user')
        self.assertTrue(captured['headers']['authorization'].startswith('Bearer '))

    def test_ollama_sends_no_auth_header(self):
        self.patch_env(ML_LLM_PROVIDER='ollama')
        captured = {}

        def fake_post(url, body, headers, timeout):
            captured.update(headers=headers)
            return {'choices': [{'message': {'content': 'x'}}]}

        with mock.patch.object(self.llm, '_post_json', side_effect=fake_post):
            self.llm._call('S', 'U')
        self.assertNotIn('authorization', captured['headers'])

    def test_http_4xx_not_retried(self):
        self.patch_env(ANTHROPIC_API_KEY='sk-ant-abcdefghijklmnop',
                       ML_LLM_MAX_RETRIES='3')
        calls = []

        def fake_post(*a, **k):
            calls.append(1)
            raise RuntimeError('HTTP 401 unauthorized')

        with mock.patch.object(self.llm, '_post_json', side_effect=fake_post):
            self.assertIsNone(self.llm._call('S', 'U'))
        self.assertEqual(len(calls), 1)

    def test_network_error_retried(self):
        self.patch_env(ANTHROPIC_API_KEY='sk-ant-abcdefghijklmnop',
                       ML_LLM_MAX_RETRIES='2')
        calls = []

        def fake_post(*a, **k):
            calls.append(1)
            raise RuntimeError('网络错误 timed out')

        with mock.patch.object(self.llm, '_post_json', side_effect=fake_post):
            self.assertIsNone(self.llm._call('S', 'U'))
        self.assertEqual(len(calls), 3)          # 1 次 + 重试 2 次

    def test_untrusted_finish_reason_returns_none(self):
        self.patch_env(ML_LLM_API_KEY='k-1234567890', ML_LLM_PROVIDER='openai')
        canned = {'choices': [{'finish_reason': 'content_filter',
                               'message': {'content': 'x'}}]}
        with mock.patch.object(self.llm, '_post_json', return_value=canned):
            self.assertIsNone(self.llm._call('S', 'U'))

    def test_temperature_omitted_by_default(self):
        self.patch_env(ML_LLM_API_KEY='k-1234567890', ML_LLM_PROVIDER='openai')
        captured = {}

        def fake_post(url, body, headers, timeout):
            captured.update(body=body)
            return {'choices': [{'message': {'content': 'x'}}]}

        with mock.patch.object(self.llm, '_post_json', side_effect=fake_post):
            self.llm._call('S', 'U')
        self.assertNotIn('temperature', captured['body'])

    def test_temperature_sent_when_configured(self):
        self.patch_env(ML_LLM_API_KEY='k-1234567890', ML_LLM_PROVIDER='openai',
                       ML_LLM_TEMPERATURE='0.2')
        captured = {}

        def fake_post(url, body, headers, timeout):
            captured.update(body=body)
            return {'choices': [{'message': {'content': 'x'}}]}

        with mock.patch.object(self.llm, '_post_json', side_effect=fake_post):
            self.llm._call('S', 'U')
        self.assertEqual(captured['body']['temperature'], 0.2)


class TestPublicApi(_EnvMixin, unittest.TestCase):

    def setUp(self):
        import llm
        self.llm = llm

    def test_classify_intent_none_when_disabled(self):
        self.patch_env()
        self.assertIsNone(self.llm.classify_intent('清洗一下'))

    def test_answer_question_none_when_disabled(self):
        self.patch_env()
        self.assertIsNone(self.llm.answer_question('群体2是什么', {}))

    def test_classify_intent_parses_fenced_json(self):
        self.patch_env(ANTHROPIC_API_KEY='sk-ant-abcdefghijklmnop')
        with mock.patch.object(self.llm, '_call',
                               return_value='```json\n{"do_clean": true}\n```'):
            self.assertEqual(self.llm.classify_intent('清洗并评估'),
                             {'do_clean': True})

    def test_classify_intent_bad_json(self):
        self.patch_env(ANTHROPIC_API_KEY='sk-ant-abcdefghijklmnop')
        with mock.patch.object(self.llm, '_call', return_value='无法判断'):
            self.assertIsNone(self.llm.classify_intent('随便'))


if __name__ == '__main__':
    unittest.main()
