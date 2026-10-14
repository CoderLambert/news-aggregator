# NH-20 explicit completion semantics; NH-23 bounded atomic TTS.
P.replace('backend/api/tests/test_metadata_corrections.py',
    "    source = Source.objects.create(name='BBC Health', url='https://feeds.bbci.co.uk/news/health/rss.xml', country='US')",
    "    source, _ = Source.objects.update_or_create(name='BBC Health', defaults={'url': 'https://feeds.bbci.co.uk/news/health/rss.xml', 'country': 'US'})")
P.region('backend/api/services/chat_history.py',
    'def append_assistant_message(*, user_id: int, news_id: int, session_id: int,',
    'def clear_chat_history(*, user_id: int, news_id: int) -> bool:',
    '''def append_assistant_message(*, user_id: int, news_id: int, session_id: int,
                             generation: int, content: str, completion_status=None,
                             context_scope=None, web_sources=None) -> ChatSnapshot:
    message = {'role': 'assistant', 'content': content}
    if completion_status is not None:
        if completion_status not in {'complete', 'interrupted', 'failed'}:
            raise ValueError('invalid_chat_completion_status')
        message['status'] = completion_status
    if context_scope in {'full', 'summary', 'excerpt'}:
        message['context_scope'] = context_scope
    if web_sources:
        message['web_sources'] = web_sources[:10]
    return _append_message(user_id=user_id, news_id=news_id, message=message,
        session_id=session_id, generation=generation, create=False)


''')
P.replace('backend/api/services/llm_translator.py',
    '    if not clients:\n        yield "抱歉，当前 AI 服务暂时不可用，请稍后再试。"\n        return',
    '    if not clients:\n        if require_completed:\n            raise ValueError("model_unavailable")\n        yield "抱歉，当前 AI 服务暂时不可用，请稍后再试。"\n        return')
P.replace('backend/api/services/llm_translator.py',
    '    logger.error("All LLM providers failed. Last error: %s", last_err)',
    '    if require_completed:\n        raise ValueError("all_chat_providers_failed")\n    logger.error("All LLM providers failed. Last error: %s", last_err)')
P.replace('backend/api/views.py',
    '        for msg in chat_snapshot.messages[-20:]:\n            messages.append(msg)',
    '        from api.services.chat_delivery import deliver_chat, prompt_history\n        messages.extend(prompt_history(chat_snapshot.messages))')
P.region('backend/api/views.py',
    '        def generate():\n            full_response = []',
    'class CategoryListView(generics.ListAPIView):',
    '''        def chunks_factory():
            # The subscription adapter already requires response.completed.
            if subscription_connection is not None:
                return stream_chat_response(subscription_connection, messages)
            return stream_chat(messages, max_tokens=16000, temperature=0.7,
                               clients=provider_clients, require_completed=True)

        def persist(content, completion_status):
            append_assistant_message(user_id=request.user.pk, news_id=news.pk,
                session_id=chat_snapshot.session_id, generation=chat_snapshot.generation,
                content=content, completion_status=completion_status,
                context_scope=chat_scope, web_sources=web_sources)

        response = StreamingHttpResponse(deliver_chat(chunks_factory, persist,
            context_scope=chat_scope, content_state=news.full_content_state,
            web_sources=web_sources), content_type='text/event-stream')
        if web_search:
            response['X-Web-Search-Used'] = 'true'
        return response


''')
P.replace('backend/api/services/tts_service.py',
    "    if os.path.isfile(path) and os.path.getsize(path) > 100:",
    "    if not os.path.islink(path) and os.path.isfile(path) and os.path.getsize(path) > 100:")
P.region('backend/api/services/tts_service.py', 'def save_to_cache(news_id: int, variant: str, audio_bytes: bytes) -> str:', 'def build_cache_variant(',
    '''def reserve_audio_writer(news_id: int, variant: str, *, reserve_slot=True):
    from api.services.tts_cache import AtomicAudioWriter
    return AtomicAudioWriter(_cache_directory(), _cache_key(news_id, variant), reserve_slot=reserve_slot)


def save_to_cache(news_id: int, variant: str, audio_bytes: bytes) -> str:
    """Atomically publish complete audio while preserving any old good file."""
    with reserve_audio_writer(news_id, variant, reserve_slot=False) as writer:
        writer.append(audio_bytes)
        return writer.publish()


''')
P.replace('backend/api/views.py',
    '            get_cached_audio, pick_tts_voice, resolve_tts_content, save_to_cache,',
    '            get_cached_audio, pick_tts_voice, resolve_tts_content, reserve_audio_writer,')
P.replace('backend/api/views.py',
    '        clean_content = clean_for_tts(resolved.content)',
    "        from api.services.tts_cache import MAX_TEXT_CHARS, AudioBusy\n        from api.services.tts_stream import BoundedAudioStream, audio_response\n        if len(resolved.content) > MAX_TEXT_CHARS * 4:\n            return Response({'code': 'tts_text_limit', 'message': '文章过长，请选择摘要朗读。'}, status=422)\n        clean_content = clean_for_tts(resolved.content)")
P.replace('backend/api/views.py',
    '        cache_variant = build_cache_variant(resolved, scope, voice, speech_text)',
    "        if len(speech_text) > MAX_TEXT_CHARS:\n            return Response({'code': 'tts_text_limit', 'message': '文章过长，请选择摘要朗读。'}, status=422)\n        cache_variant = build_cache_variant(resolved, scope, voice, speech_text)")
source = P.read('backend/api/views.py')
marker = '        # Complete the upstream handshake and receive the first audio chunk'
assert source.count(marker) == 1
old = source[source.index(marker):]
assert old.rstrip().endswith('return response')
P.replace('backend/api/views.py', old, '''        writer = None
        stream = None
        try:
            writer = reserve_audio_writer(pk, cache_variant)
            stream = BoundedAudioStream(edge_tts.Communicate(speech_text, voice), writer)
            stream.prepare()
            return audio_response(stream)
        except AudioBusy:
            return Response({'code': 'tts_busy', 'message': '语音生成繁忙，请稍后重试。'},
                            status=429, headers={'Retry-After': '15'})
        except Exception as exc:
            if stream is not None:
                stream.close()
            elif writer is not None:
                writer.close()
            logging.getLogger(__name__).warning('TTS startup failed (%s)', type(exc).__name__)
            return Response({'code': 'tts_unavailable', 'message': '语音服务暂不可用，请稍后重试。'}, status=503)
''')
P.replace('frontend/src/services/newsWorkflowApi.ts',
    "  context_scope?: 'full' | 'summary' | 'excerpt'\n}",
    "  context_scope?: 'full' | 'summary' | 'excerpt'\n  status?: 'complete' | 'interrupted' | 'failed' | 'legacy_unknown'\n}")
P.replace('frontend/src/services/newsWorkflowApi.ts',
    "  const message: ChatMessage = { role: value.role, content: value.content }",
    "  const message: ChatMessage = { role: value.role, content: value.content }\n  if (value.status === 'complete' || value.status === 'interrupted' || value.status === 'failed' || value.status === 'legacy_unknown') message.status = value.status\n  if (value.context_scope === 'full' || value.context_scope === 'summary' || value.context_scope === 'excerpt') message.context_scope = value.context_scope")
P.replace('frontend/src/hooks/useChat.ts',
    "function consumeMetaFrame(",
    "import { parseChatDeliveryMetadata, type ChatDeliveryMetadata } from '@/services/chatDelivery'\n\nfunction consumeMetaFrame(")
P.replace('frontend/src/hooks/useChat.ts',
    "  onScope?: (scope: NonNullable<ChatMessage['context_scope']>) => void,\n): string {",
    "  onScope?: (scope: NonNullable<ChatMessage['context_scope']>) => void,\n  onDelivery?: (value: ChatDeliveryMetadata) => void,\n): string {")
P.replace('frontend/src/hooks/useChat.ts',
    "    if (scope) onScope?.(scope)\n    remaining = remaining.slice(end + META_MARKER.length)",
    "    if (scope) onScope?.(scope)\n    const delivery = parseChatDeliveryMetadata(remaining.slice(META_MARKER.length, end))\n    if (delivery) onDelivery?.(delivery)\n    remaining = remaining.slice(end + META_MARKER.length)")
P.replace('frontend/src/hooks/useChat.ts',
    "      let frameBuffer = ''\n      const applyScope",
    "      let frameBuffer = ''\n      const delivery: { versioned: boolean; terminal: ChatMessage['status']; saved: boolean } = { versioned: false, terminal: undefined, saved: false }\n      const applyDelivery = (value: ChatDeliveryMetadata) => {\n        if (value.contract === 2) delivery.versioned = true\n        if (value.status) { delivery.terminal = value.status; delivery.saved = value.saved === true }\n      }\n      const applyScope")
P.replace('frontend/src/hooks/useChat.ts', '            applyScope,\n          )', '            applyScope,\n            applyDelivery,\n          )')
P.replace('frontend/src/hooks/useChat.ts', '          applyScope,\n        )', '          applyScope,\n          applyDelivery,\n        )')
P.replace('frontend/src/hooks/useChat.ts',
    '        const completedAssistant: ChatMessage = { ...request.assistant, content: accumulated }',
    "        if (delivery.versioned && (delivery.terminal !== 'complete' || !delivery.saved)) {\n          request.assistant = { ...request.assistant, content: accumulated, status: delivery.terminal ?? 'interrupted' }\n          throw new Error('回答未完整生成或尚未保存，请检查记录后决定是否重新提问。')\n        }\n        const completedAssistant: ChatMessage = { ...request.assistant, content: accumulated, status: delivery.versioned ? 'complete' : 'legacy_unknown' }")
P.replace('frontend/src/components/chat/ChatMessageList.tsx',
    "import XiaowenMascot from '@/components/mascot/XiaowenMascot'",
    "import XiaowenMascot from '@/components/mascot/XiaowenMascot'\nimport { completionLabel } from '@/services/chatDelivery'")
P.replace('frontend/src/components/chat/ChatMessageList.tsx',
    "            {message.role === 'assistant' && (message.context_scope === 'summary' || message.context_scope === 'excerpt') && (",
    "            {message.role === 'assistant' && completionLabel(message.status) && <p className=\"mb-2 text-xs text-muted-foreground\" role=\"status\">{completionLabel(message.status)}</p>}\n            {message.role === 'assistant' && (message.context_scope === 'summary' || message.context_scope === 'excerpt') && (")
