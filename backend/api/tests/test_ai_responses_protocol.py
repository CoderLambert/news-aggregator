"""Native Responses research round trips, with zero database/provider access."""
import copy
from types import SimpleNamespace as N
from unittest import TestCase
from unittest.mock import Mock

from api.services.ai_gateway import _GatewayCompletions, AIGatewayError
from api.services.ai_responses_protocol import (
    ResponsesProtocolError, completion_object, responses_completion, responses_input, responses_payload,
)
from api.services.ai_model_registry import catalog_for, get_trusted_preset, supports_article_chat
from api.services.research.byok_execution import (
    continuation_payload, native_messages, preserve_native_fields, visible_messages, ResearchBYOKError,
)

MODEL = 'openai/gpt-5.4-mini'
REASONING = {'id': 'reasoning_1', 'type': 'reasoning', 'summary': [],
             'encrypted_content': 'synthetic-encrypted-native-item'}
CALL = {'id': 'fc_1', 'type': 'function_call', 'call_id': 'call_1',
        'name': 'search_news', 'arguments': '{"query":"synthetic"}', 'status': 'completed'}
FINAL = {'id': 'msg_1', 'type': 'message', 'role': 'assistant', 'status': 'completed',
         'content': [{'type': 'output_text', 'text': 'Synthetic report', 'annotations': []}]}
TOOLS = [{'type': 'function', 'function': {'name': 'search_news', 'description': 'Search local news',
          'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}}}}}]


def response(items):
    return {'status': 'completed', 'output': copy.deepcopy(items), 'error': None,
            'usage': {'input_tokens': 11, 'output_tokens': 3}}


class NativeResponsesTests(TestCase):
    def test_tool_result_and_followup_replay_original_items(self):
        first = completion_object(responses_completion(response([REASONING, CALL])))
        assistant = {'role': 'assistant', 'tool_calls': [{'id': 'call_1'}]}
        preserve_native_fields(first.choices[0].message, assistant)
        messages = [{'role': 'user', 'content': 'Find synthetic news'}, assistant,
                    {'role': 'tool', 'tool_call_id': 'call_1', 'content': '{"articles":[]}'}]
        request = responses_payload({'model': MODEL, 'messages': messages, 'tools': TOOLS,
                                     'tool_choice': 'auto', 'max_tokens': 8000})
        self.assertFalse(request['store'])
        self.assertEqual(request['include'], ['reasoning.encrypted_content'])
        self.assertEqual(request['input'][1:3], [REASONING, CALL])
        self.assertEqual(request['input'][-1], {'type': 'function_call_output',
                         'call_id': 'call_1', 'output': '{"articles":[]}'})
        self.assertFalse(request['tools'][0]['strict'])
        final = completion_object(responses_completion(response([FINAL])))
        final_message = {'role': 'assistant', 'content': final.choices[0].message.content}
        preserve_native_fields(final.choices[0].message, final_message)
        messages.extend([final_message, {'role': 'user', 'content': 'Follow up'}])
        self.assertEqual(responses_input(messages)[-2:], [FINAL, {'role': 'user', 'content': 'Follow up'}])
        snapshot = {'model': {'proxy_alias': MODEL, 'model_config_id': 'original'}}
        session = N(native_continuation=continuation_payload(snapshot, messages))
        self.assertEqual(session.native_continuation['protocol'], 'openai-responses-v1')
        self.assertEqual(native_messages(session, snapshot), messages)
        public = visible_messages(messages)
        self.assertNotIn('encrypted', str(public))
        self.assertNotIn('responses_output', str(public))
        with self.assertRaises(ResearchBYOKError):
            native_messages(session, {'model': {'proxy_alias': 'deepseek/deepseek-flash'}})

    def test_gateway_dispatches_once_via_responses_and_keeps_key_in_body(self):
        chat, native = Mock(), Mock()
        native.create.return_value = response([FINAL])
        gateway = _GatewayCompletions(chat, 'synthetic-provider-key', responses=native)
        result = gateway.create(model=MODEL, messages=[{'role': 'user', 'content': 'synthetic'}],
                                tools=TOOLS, tool_choice='auto', max_tokens=128, temperature=0.3)
        self.assertEqual(result.choices[0].finish_reason, 'stop')
        self.assertEqual(result.usage.prompt_tokens, 11)
        native.create.assert_called_once()
        chat.create.assert_not_called()
        payload = native.create.call_args.kwargs
        self.assertEqual(payload['extra_body'], {'api_key': 'synthetic-provider-key'})
        self.assertFalse(payload['store'])
        self.assertEqual(payload['reasoning'], {'effort': 'none'})
        self.assertNotIn('temperature', payload)
        self.assertNotIn('previous_response_id', payload)
        with self.assertRaises(AIGatewayError):
            gateway.create(model=MODEL, stream=True)
        self.assertEqual(native.create.call_count, 1)

    def test_incomplete_error_refusal_and_unknown_output_never_complete(self):
        invalid = [{**response([FINAL]), 'status': status} for status in ('incomplete', 'failed', 'in_progress', None)]
        invalid += [{**response([FINAL]), 'error': {'message': 'synthetic failure'}},
                    {**response([FINAL]), 'incomplete_details': {'reason': 'max_output_tokens'}},
                    response([{**CALL, 'status': 'in_progress'}]),
                    response([{'type': 'web_search_call', 'status': 'completed'}]),
                    response([{**FINAL, 'content': [{'type': 'refusal', 'refusal': 'No'}]}])]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ResponsesProtocolError):
                responses_completion(value)

    def test_classification_json_object_and_timeout_map_to_responses(self):
        native = Mock()
        native.create.return_value = response([{**FINAL, 'content': [
            {'type': 'output_text', 'text': '{"channels":[]}'}]}])
        gateway = _GatewayCompletions(Mock(), 'synthetic-key', responses=native)
        gateway.create(model=MODEL, messages=[{'role': 'user', 'content': 'Classify as JSON'}],
                       stream=False, response_format={'type': 'json_object'}, max_tokens=6000, timeout=60)
        request = native.create.call_args.kwargs
        self.assertEqual(request['text'], {'format': {'type': 'json_object'}})
        self.assertEqual(request['timeout'], 60)
        self.assertNotIn('response_format', request)
        with self.assertRaises(AIGatewayError):
            gateway.create(model=MODEL, timeout=181)
        self.assertEqual(native.create.call_count, 1)

    def test_missing_duplicate_and_orphan_tool_outputs_are_rejected(self):
        assistant = {'role': 'assistant', 'responses_output': [CALL]}
        tool = {'role': 'tool', 'tool_call_id': 'call_1', 'content': '{}'}
        for messages in ([assistant], [tool], [assistant, tool, tool],
                         [assistant, {'role': 'user', 'content': 'premature followup'}]):
            with self.subTest(messages=messages), self.assertRaises(ResponsesProtocolError):
                responses_input(messages)
        with self.assertRaises(ResponsesProtocolError):
            responses_completion(response([CALL, CALL]))

    def test_preset_is_owner_profile_bound_and_never_claims_capability_or_streaming(self):
        connection = N(provider_id='openai', endpoint_profile='openai_default', endpoint_profile_version=1)
        catalog = catalog_for(connection)
        self.assertEqual([row['model_id'] for row in catalog], ['gpt-5.4-mini'])
        self.assertEqual((catalog[0]['text'], catalog[0]['tools']), ('unknown', 'unknown'))
        self.assertFalse(supports_article_chat(connection, 'gpt-5.4-mini'))
        connection.endpoint_profile_version = 2
        self.assertIsNone(get_trusted_preset(connection, 'gpt-5.4-mini'))
        connection = N(provider_id='deepseek', endpoint_profile='deepseek_default', endpoint_profile_version=1)
        self.assertIsNone(get_trusted_preset(connection, 'gpt-5.4-mini'))
