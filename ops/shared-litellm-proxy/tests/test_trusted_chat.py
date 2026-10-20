"""Real pinned LiteLLM CustomLLM -> raw handler -> synthetic HTTP proof."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from tools.byok_t00_probe.proxy_process import loopback_only
sys.addaudithook(loopback_only)

import test_trusted_transport as wire
from test_trusted_routes import raw_profile
from ai_endpoint_profiles import validate_endpoint_profiles


class TrustedCustomProviderTests(unittest.IsolatedAsyncioTestCase):
    asyncTearDown = wire.OneShotWireTests.asyncTearDown

    async def asyncSetUp(self):
        import litellm
        from trusted_chat import provider
        from litellm.utils import custom_llm_setup
        wire.OneShotWireTests.setUp(self)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'manifest.json'
        item = raw_profile(api_base=self.profile['api_base'])
        self.path.write_text(json.dumps([item]))
        self.profile = validate_endpoint_profiles([item])[0]
        self.environment = patch.dict(os.environ, {'AI_BYOK_ENDPOINT_MANIFEST': str(self.path),
                                                    'OPENAI_API_KEY': 'ambient-synthetic-key'})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        litellm.custom_provider_map = [{'provider': 'newshub_chat', 'custom_handler': provider}]
        custom_llm_setup()
        self.litellm = litellm

    async def call(self, model='org/model:tag', stream=False, admitted=True, key=None, provider_messages=None):
        from trusted_chat import finish_request
        from provider_key_guard import ProviderKeyGuard
        data = {'model': self.profile['route_prefix'] + '/' + model, 'stream': stream, 'api_key': key,
                'messages': [{'role': 'user', 'content': 'synthetic'}],
                'metadata': {'newshub_owner_id': 7, 'newshub_auth_mode': 'none' if key is None else 'api_key'}}
        if admitted:
            await ProviderKeyGuard().async_pre_call_hook(None, None, data, 'acompletion')
            self.addAsyncCleanup(finish_request, data)
        result = await self.litellm.acompletion(
            model='newshub_chat/' + model, messages=provider_messages or [{'role': 'user', 'content': 'synthetic'}],
            api_base=self.profile['api_base'], api_key=key, metadata=data['metadata'],
            stream=stream, max_tokens=8, num_retries=0,
        )
        if stream and admitted:
            return ProviderKeyGuard().async_post_call_streaming_iterator_hook(result, None, data)
        return result

    async def test_mature_raw_handler_completes_key_and_none_without_ambient_auth(self):
        for key in (None, 'synthetic-owner-key'):
            result = await self.call(key=key)
            self.assertEqual(result.choices[0].finish_reason, 'stop')
        self.assertEqual([request['auth'] for request in self.requests], [None, 'Bearer synthetic-owner-key'])
        self.assertEqual([request['body']['model'] for request in self.requests], ['org/model:tag', 'org/model:tag'])

    async def test_stream_stop_done_and_raw_eof_remain_distinct(self):
        good = await self.call(stream=True)
        reasons = [chunk.choices[0].finish_reason async for chunk in good if chunk.choices]
        self.assertEqual([reason for reason in reasons if reason], ['stop'])
        failed = await self.call(model='eof', stream=True)
        reasons = []
        with self.assertRaises(Exception):
            async for chunk in failed:
                reasons.extend(choice.finish_reason for choice in chunk.choices if choice.finish_reason)
        self.assertEqual(reasons, [])
        self.assertEqual(len(self.requests), 2)

    async def test_direct_unadmitted_custom_provider_cannot_send(self):
        with self.assertRaises(Exception):
            await self.call(admitted=False)
        self.assertEqual(self.requests, [])

    async def test_file_download_preprocessing_cannot_bypass_pinned_transport(self):
        module = 'litellm.llms.openai.chat.gpt_transformation'
        download = Mock(side_effect=ValueError('synthetic download trap'))
        async_download = AsyncMock(side_effect=ValueError('synthetic download trap'))
        messages = [{'role': 'user', 'content': [{'type': 'file', 'file': {
            'file_id': 'https://unapproved.invalid/document.pdf'}}]}]
        with patch(module + '.convert_url_to_base64', download), patch(
                module + '.async_convert_url_to_base64', async_download):
            with self.assertRaises(Exception):
                await self.call(provider_messages=messages)
        self.assertEqual(download.call_count + async_download.call_count, 0)
        self.assertEqual(self.requests, [])

    async def test_malformed_provider_body_never_appears_in_public_error(self):
        with self.assertRaises(Exception) as failure:
            await self.call(model='malformed')
        self.assertNotIn('private-body-sentinel', str(failure.exception))
        self.assertEqual(len(self.requests), 1)


class TrustedRequestShapeTests(unittest.TestCase):
    def test_json_object_output_is_data_only_and_other_formats_remain_denied(self):
        from trusted_chat import validate_chat_input
        from trusted_transport import EgressDenied
        messages = [{'role': 'user', 'content': 'synthetic'}]
        validate_chat_input(messages, {'response_format': {'type': 'json_object'}}, stream=False)
        with self.assertRaises(EgressDenied):
            validate_chat_input(messages, {'response_format': {'type': 'json_schema', 'url': 'https://unapproved.invalid'}}, stream=False)

    def test_only_text_and_function_tool_history_reach_adapter(self):
        from trusted_chat import validate_chat_input
        from trusted_transport import EgressDenied
        valid = [{'role': 'system', 'content': 'instructions'},
                 {'role': 'user', 'content': [{'type': 'text', 'text': 'question'}]},
                 {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'call_1', 'type': 'function',
                   'function': {'name': 'lookup', 'arguments': '{"query":"text"}'}}]},
                 {'role': 'tool', 'tool_call_id': 'call_1', 'content': 'result'}]
        validate_chat_input(valid, {'max_tokens': 8}, stream=False)
        for message in (
            {'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'https://unapproved.invalid'}}]},
            {'role': 'user', 'content': [{'type': 'input_audio', 'input_audio': {'data': 'AA==', 'format': 'wav'}}]},
            {'role': 'user', 'content': 'text', 'attachments': [{'url': 'https://unapproved.invalid'}]},
            {'role': 'assistant', 'content': {'file_id': 'https://unapproved.invalid'}},
        ):
            with self.subTest(message=message), self.assertRaises(EgressDenied):
                validate_chat_input([message], {}, stream=False)

    def test_optional_params_cannot_enable_other_network_or_multimodal_paths(self):
        from trusted_chat import validate_chat_input
        from trusted_transport import EgressDenied
        messages = [{'role': 'user', 'content': 'synthetic'}]
        for options in (
            {'web_search_options': {}}, {'modalities': ['audio']}, {'extra_headers': {'X-Test': 'value'}},
            {'extra_body': {'api_base': 'https://unapproved.invalid'}}, {'api_key': 'synthetic'},
            {'tools': [{'type': 'web_search'}]}, {'n': 2}, {'max_tokens': True}, {'temperature': float('nan')},
        ):
            with self.subTest(options=options), self.assertRaises(EgressDenied):
                validate_chat_input(messages, options, stream=False)
        with self.assertRaises(EgressDenied):
            validate_chat_input(messages, {'tools': [{'type': 'function', 'function': {
                'name': 'lookup', 'parameters': {'type': 'object'}}}]}, stream=True)
