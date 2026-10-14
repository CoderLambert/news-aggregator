# NH-17 evidence fencing; NH-19 official publisher promotion; NH-32 display-only validators.
P.replace('backend/api/services/channel_topics.py',
    "    titles = list(channel_articles(source).order_by('-publish_time').values_list('title', flat=True)[:12])\n    return {'source_id': source.id, 'name': source.name[:100], 'about': profile['description'][:600],\n        'titles': [str(t).replace('\\x00', '')[:180] for t in titles], 'evidence_hash': profile['evidence_hash']}",
    "    rows = list(channel_articles(source).order_by('-publish_time', '-id').values('id', 'title', 'publish_time')[:12])\n    return {'source_id': source.id, 'name': source.name[:100], 'about': profile['description'][:600],\n        'titles': [str(row['title']).replace('\\x00', '')[:180] for row in rows],\n        'version': 'channel-evidence-2',\n        'titles_hash': digest([[row['id'], row['publish_time'], row['title']] for row in rows]),\n        'evidence_hash': profile['evidence_hash']}")
P.replace('backend/api/services/channel_ai.py',
    'from api.services.provider_credentials import personal_clients_for_user',
    'from api.services.provider_credentials import personal_clients_for_user\nfrom api.services.channel_evidence import evidence_is_current')
P.replace('backend/api/services/channel_ai.py', "PROMPT_VERSION = 'channel-topics-1'", "PROMPT_VERSION = 'channel-topics-2'")
P.replace('backend/api/services/channel_ai.py',
    "        clients = personal_clients_for_user(job.user)\n        if not clients:",
    "        if not evidence_is_current(job.evidence):\n            raise ValueError('evidence_changed')\n        clients = personal_clients_for_user(job.user)\n        if not clients:")
P.replace('backend/api/services/channel_ai.py',
    "known = {'authorization_changed', 'configuration_changed', 'model_unavailable', 'incomplete_output',",
    "known = {'authorization_changed', 'configuration_changed', 'evidence_changed', 'model_unavailable', 'incomplete_output',")
P.replace('backend/api/services/channel_ai.py',
    "        if not permitted(job):\n            error_code, result = 'authorization_changed', None\n        if result is not None and job.public_source_id:",
    "        if not permitted(job):\n            error_code, result, delay = 'authorization_changed', None, None\n        if not evidence_is_current(current.evidence):\n            error_code, result, delay = 'evidence_changed', None, None\n        if result is not None and job.public_source_id:")
P.replace('backend/api/services/channel_grouping.py',
    "    if proposal.input_snapshot != snapshot(user, proposal.source_ids):\n        raise GroupingConflict()\n    entries = payload.get('groups')",
    "    if proposal.input_snapshot != snapshot(user, proposal.source_ids):\n        raise GroupingConflict()\n    if proposal.engine == 'ai':\n        from api.services.channel_evidence import evidence_is_current\n        if not evidence_is_current(proposal.evidence):\n            raise GroupingConflict('文章标题或频道资料已更新，请重新生成预览。')\n    entries = payload.get('groups')")
P.replace('frontend/src/pages/SmartGroupingWorkspace.tsx',
    "  model_unavailable: '没有可用的模型连接。',",
    "  evidence_changed: '分类依据的文章标题或频道资料已更新，结果未应用；请重新预览。',\n  model_unavailable: '没有可用的模型连接。',")
P.replace('backend/api/services/news_ingestion.py',
    'from api.services.source_policy import POLICIES, policy_for_name',
    'from api.services.source_policy import POLICIES, policy_for_name\nfrom api.services.article_metadata import can_promote_publisher')
P.replace('backend/api/services/news_ingestion.py',
    "    changed = False\n    if news is None:",
    "    promotion = news is not None and can_promote_publisher(news, policy, url, kind)\n    promoted_from = news.source_id if promotion else None\n    changed = False\n    if news is None:")
P.replace('backend/api/services/news_ingestion.py',
    "    elif news.source_id == source.pk:\n        # Follow corrections",
    "    elif news.source_id == source.pk or promotion:\n        if promotion:\n            updates.update(source_id=source.pk, title_zh='', content_zh='',\n                author=item.get('author') or '', cover_image=item.get('cover_image') or '',\n                suggested_questions=[], suggested_questions_generated_at=None,\n                translation_status='pending', translation_error='', translation_retry_count=0)\n        # Follow corrections")
P.replace('backend/api/services/news_ingestion.py',
    "    metadata = dict(mapping.metadata or {}) if mapping else {}\n    metadata.update({'publish_time_inferred': bool(inferred), 'category_name': item['category_name']})",
    "    metadata = dict(mapping.metadata or {}) if mapping else {}\n    if promotion:\n        metadata['publisher_promotion'] = {'from_source_id': promoted_from, 'from_source_key': 'hackernews', 'at': seen.isoformat()}\n    metadata.update({'publish_time_inferred': bool(inferred), 'category_name': item['category_name']})")
P.replace('backend/api/services/feed_state.py',
    "    contract.pop('poll_seconds')\n    contract.pop('request_interval')",
    "    # Descriptions are presentation-only. Keep names (currently used to\n    # resolve Source identity) and every admission/body/date field semantic.\n    for field in ('poll_seconds', 'request_interval', 'description'):\n        contract.pop(field)")
