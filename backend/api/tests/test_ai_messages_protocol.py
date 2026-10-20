"""Native Messages boundaries using synthetic content and no database."""
import copy
from types import SimpleNamespace as N
from unittest import TestCase
from unittest.mock import Mock

from api.services.ai_gateway import AIGatewayError, _GatewayCompletions, _GatewayClient
from api.services.ai_messages_protocol import (
    MessagesProtocolError, messages_completion, messages_input, messages_payload,
)
from api.services.ai_responses_protocol import completion_object
from api.services.ai_model_registry import catalog_for, get_trusted_preset, supports_article_chat
from api.services.research.byok_execution import (
    ResearchBYOKError, continuation_payload, native_messages, preserve_native_fields, visible_messages,
)

MODEL = 'anthropic/claude-haiku-5-5'
THINKING = {'type': 'thinking', 'thinking': '', 'signature': 'synthetic-opaque-signature'}
REDACTED = {'type': 'redacted_thinking', 'data': 'synthetic-redacted-block'}
CALL = {'type': 'tool_use', 'id': 'toolu_1', 'name': 'search_news', 'input': {'query': 'synthetic'}}
FINAL = {'type': 'text', 'text': 'Synthetic report'}
TOOLS = [{'type': 'function', 'function': {'name': 'search_news', 'description': 'Search local news',
          'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}}}}}]


def response(blocks, stop_reason='end_turn'):
    return {'id': 'msg_synthetic', 'type': 'message', 'role': 'assistant',
            'model': 'claude-haiku-5-5', 'content': copy.deepcopy(blocks),
            'stop_reason': stop_reason, 'usage': {'input_tokens': 11, 'output_tokens': 3}}


class NativeMessagesTests(TestCase):
    def test_manual_claude_model_uses_messages_without_borrowing_preset_options(self):
        native, chat = Mock(), Mock()
        native.create.return_value = response([FINAL])
        alias = 'anthropic/synthetic-future-model'
        gateway = _GatewayCompletions(chat, 'synthetic-key', messages_getter=lambda: native)
        gateway.create(model=alias, messages=[{'role': 'user', 'content': 'synthetic'}], max_tokens=128)
        request = native.create.call_args.kwargs
        self.assertEqual(request['model'], alias)
        self.assertNotIn('thinking', request)
        self.assertNotIn('output_config', request)
        chat.create.assert_not_called()
        self.assertEqual(continuation_payload({'model': {'proxy_alias': alias}}, [])['protocol'],
                         'anthropic-messages-v1')

    def test_parallel_tools_results_thinking_and_followup_stay_native_and_private(self):
        blocks = [THINKING, REDACTED, CALL, {**CALL, 'id': 'toolu_2'}]
        first = completion_object(messages_completion(response(blocks, 'tool_use')))
        assistant = {'role': 'assistant', 'tool_calls': [{'id': 'toolu_1'}, {'id': 'toolu_2'}]}
        preserve_native_fields(first.choices[0].message, assistant)
        history = [{'role': 'system', 'content': 'Synthetic instructions'},
                   {'role': 'user', 'content': 'Find synthetic news'}, assistant,
                   {'role': 'tool', 'tool_call_id': 'toolu_1', 'content': '{}'},
                   {'role': 'tool', 'tool_call_id': 'toolu_2', 'content': '{"items":[]}'}]
        payload = messages_payload({'model': MODEL, 'messages': history, 'max_tokens': 8000,
                                    'tools': TOOLS, 'tool_choice': 'auto', 'temperature': 0.3})
        self.assertEqual(payload['system'], 'Synthetic instructions')
        self.assertEqual(payload['messages'][1]['content'], blocks)
        self.assertEqual(payload['messages'][2], {'role': 'user', 'content': [
            {'type': 'tool_result', 'tool_use_id': 'toolu_1', 'content': '{}'},
            {'type': 'tool_result', 'tool_use_id': 'toolu_2', 'content': '{"items":[]}'}]})
        self.assertEqual(payload['tools'][0]['input_schema'], TOOLS[0]['function']['parameters'])
        self.assertNotIn('temperature', payload)
        final = completion_object(messages_completion(response([FINAL])))
        last = {'role': 'assistant', 'content': final.choices[0].message.content}
        preserve_native_fields(final.choices[0].message, last)
        history.extend([last, {'role': 'user', 'content': 'Follow up'}])
        self.assertEqual(messages_input(history)[1][-2:], [
            {'role': 'assistant', 'content': [FINAL]}, {'role': 'user', 'content': 'Follow up'}])
        snapshot = {'model': {'proxy_alias': MODEL, 'model_config_id': 'original'}}
        session = N(native_continuation=continuation_payload(snapshot, history))
        self.assertEqual(session.native_continuation['protocol'], 'anthropic-messages-v1')
        self.assertEqual(native_messages(session, snapshot), history)
        self.assertNotIn('signature', str(visible_messages(history)))
        self.assertNotIn('anthropic_content', str(visible_messages(history)))
        for other in ('openai/gpt-5.4-mini', 'deepseek/deepseek-flash'):
            with self.assertRaises(ResearchBYOKError):
                native_messages(session, {'model': {'proxy_alias': other}})

    def test_incomplete_refused_unknown_and_inconsistent_outputs_fail_closed(self):
        invalid = [response([FINAL], reason) for reason in (
            None, 'max_tokens', 'pause_turn', 'refusal', 'stop_sequence')]
        invalid.extend([response([FINAL], 'tool_use'), response([CALL]),
                        response([THINKING]), response([CALL, CALL], 'tool_use'),
                        response([{'type': 'server_tool_use'}], 'tool_use'),
                        response([{**THINKING, 'signature': ''}]),
                        response([{**CALL, 'caller': {'type': 'code_execution'}}], 'tool_use')])
        for item in invalid:
            with self.subTest(item=item), self.assertRaises(MessagesProtocolError):
                messages_completion(item)

    def test_tool_results_cannot_be_missing_duplicated_or_orphaned(self):
        assistant = {'role': 'assistant', 'anthropic_content': [CALL]}
        tool = {'role': 'tool', 'tool_call_id': 'toolu_1', 'content': '{}'}
        for history in ([assistant], [tool], [assistant, tool, tool],
                        [assistant, {'role': 'user', 'content': 'premature'}],
                        [assistant, tool, assistant, tool]):
            with self.subTest(history=history), self.assertRaises(MessagesProtocolError):
                messages_input(history)

    def test_gateway_uses_only_messages_once_and_no_sampling_or_stream(self):
        chat, native = Mock(), Mock()
        native.create.return_value = response([FINAL])
        getter = Mock(return_value=native)
        gateway = _GatewayCompletions(chat, 'synthetic-vendor-key', messages_getter=getter)
        result = gateway.create(model=MODEL, messages=[{'role': 'user', 'content': 'synthetic'}],
                                tools=TOOLS, tool_choice='auto', max_tokens=128, temperature=0.3)
        self.assertEqual(result.choices[0].finish_reason, 'stop')
        self.assertEqual(result.usage.prompt_tokens, 11)
        native.create.assert_called_once()
        chat.create.assert_not_called()
        request = native.create.call_args.kwargs
        self.assertEqual(request['extra_body'], {'api_key': 'synthetic-vendor-key'})
        self.assertEqual(request['thinking'], {'type': 'disabled'})
        self.assertNotIn('temperature', request)
        for extra in ({'stream': True}, {'extra_body': {'api_key': 'injected'}}):
            with self.assertRaises(AIGatewayError):
                gateway.create(model=MODEL, **extra)
        self.assertEqual(native.create.call_count, 1)

    def test_native_sdk_is_lazy_and_owned_clients_close(self):
        client, http_client, native = Mock(), Mock(), Mock()
        factory = Mock(return_value=native)
        gateway = _GatewayClient(client, http_client, 'synthetic-vendor-key', messages_factory=factory)
        factory.assert_not_called()
        self.assertIs(gateway._native_messages(), native.messages)
        self.assertIs(gateway._native_messages(), native.messages)
        factory.assert_called_once()
        gateway.close()
        native.close.assert_called_once()
        client.close.assert_called_once()
        http_client.close.assert_called_once()

    def test_classification_json_instruction_and_bounded_timeout_reach_native_sdk(self):
        native = Mock()
        native.create.return_value = response([{'type': 'text', 'text': '{"channels":[]}'}])
        gateway = _GatewayCompletions(Mock(), 'synthetic-key', messages_getter=lambda: native)
        gateway.create(model=MODEL, messages=[{'role': 'system', 'content': 'Classify channels'},
                       {'role': 'user', 'content': 'synthetic'}], stream=False,
                       response_format={'type': 'json_object'}, max_tokens=6000, timeout=60)
        request = native.create.call_args.kwargs
        self.assertIn('valid JSON object', request['system'])
        self.assertEqual(request['timeout'], 60)
        self.assertNotIn('response_format', request)
        for timeout in (0, 181, True, float('nan')):
            with self.assertRaises(AIGatewayError):
                gateway.create(model=MODEL, timeout=timeout)
        self.assertEqual(native.create.call_count, 1)

    def test_preset_is_profile_bound_and_buffered_without_claiming_capability(self):
        connection = N(provider_id='anthropic', endpoint_profile='anthropic_default', endpoint_profile_version=1)
        catalog = catalog_for(connection)
        self.assertEqual([item['model_id'] for item in catalog], ['claude-haiku-5-5'])
        self.assertEqual((catalog[0]['text'], catalog[0]['tools']), ('unknown', 'unknown'))
        self.assertTrue(supports_article_chat(connection, 'claude-haiku-5-5'))
        from api.services.ai_model_registry import get_trusted_route
        route = get_trusted_route(connection, 'claude-haiku-5-5')
        self.assertEqual(route['delivery_mode'], 'buffered')
        self.assertFalse(route['stream_verified'])
        connection.endpoint_profile_version = 2
        self.assertIsNone(get_trusted_preset(connection, 'claude-haiku-5-5'))
