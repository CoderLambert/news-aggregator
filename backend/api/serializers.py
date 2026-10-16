from rest_framework import serializers
from .models import Category, Source, News, Favorite, BlockedNews, ProviderComparison, ResearchSession, ResearchSearchResult, ChatGPTArticleTranslation


class CategorySerializer(serializers.ModelSerializer):
    news_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'description', 'news_count']


class SourceSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    news_count = serializers.SerializerMethodField()
    source_type = serializers.CharField(read_only=True)
    reading_policy = serializers.SerializerMethodField()
    subscription_status = serializers.SerializerMethodField()
    subscription_reason = serializers.SerializerMethodField()

    def get_name(self, obj):
        from api.rss.models import SourcePublication
        try:
            return obj.publication.display_name or obj.name
        except SourcePublication.DoesNotExist:
            return obj.name

    def get_reading_policy(self, obj):
        from api.rss.models import SourcePublication
        try:
            return obj.publication.reading_policy
        except SourcePublication.DoesNotExist:
            return 'summary_only'

    def get_news_count(self, obj):
        if hasattr(obj, 'rss_news_count'):
            return obj.rss_news_count
        from api.rss.access import authorized_news, news_in_sources
        user = getattr(self.context.get('request'), 'user', None)
        return news_in_sources(authorized_news(user), Source.objects.filter(pk=obj.pk)).count()

    def get_subscription_status(self, obj):
        from api.services.channel_catalog import subscription_status
        return subscription_status(obj)[0]

    def get_subscription_reason(self, obj):
        from api.services.channel_catalog import subscription_status
        return subscription_status(obj)[1]

    class Meta:
        model = Source
        fields = ['id', 'name', 'url', 'logo', 'country', 'language', 'source_type', 'news_count', 'description', 'region', 'reading_policy', 'subscription_status', 'subscription_reason']


class AccessNewsListSerializer(serializers.ListSerializer):
    def to_representation(self, data):
        from api.rss.access import prepare_article_previews
        items = list(data)
        user = getattr(self.context.get('request'), 'user', None)
        self.child._preview_snapshots = prepare_article_previews(user, items)
        from api.models import LegacyTranslationSnapshot
        from hashlib import sha256
        self.child._legacy_batch = {(r.news_id, r.field, r.source_hash, r.source_text): r.translated_text
            for r in LegacyTranslationSnapshot.objects.filter(news_id__in=[item.pk for item in items],
                field__in=('title', 'content'), origin__in=('legacy', 'legacy-bound'),
                source_hash__in=[sha256(value.encode()).hexdigest()
                    for item in items for value in (item.title, item.content)]).order_by('captured_at', 'pk')}
        try:
            return super().to_representation(items)
        finally:
            self.child._preview_snapshots = None
            self.child._legacy_batch = None


class ChannelNewsSerializer(serializers.ModelSerializer):
    publish_time_inferred = serializers.SerializerMethodField()
    source_region = serializers.CharField(source='source.region', read_only=True)
    channel_ids = serializers.SerializerMethodField()
    channel_names = serializers.SerializerMethodField()
    is_medical = serializers.SerializerMethodField()
    reading_policy = serializers.SerializerMethodField()
    body_access_granted = serializers.SerializerMethodField()
    can_fetch_full_content = serializers.SerializerMethodField()

    def get_body_access_granted(self, obj):
        from api.services.body_access import can_view_article_body
        return can_view_article_body(getattr(self.context.get("request"), "user", None))

    def get_can_fetch_full_content(self, obj):
        from api.rss.access import authorized_sources
        from api.services.full_content_status import fetch_eligibility
        user = getattr(self.context.get('request'), 'user', None)
        if obj.body_owner_binding_id or not authorized_sources(user, body=True).filter(
                pk=obj.body_owner_source_id, publication__owner='legacy').exists():
            return False
        return obj.full_content_fetch_status != 'blocked' and obj.full_content_retry_count < 5 and not fetch_eligibility(obj, privileged=self.get_body_access_granted(obj))

    full_content_completeness = serializers.SerializerMethodField()
    content_completeness = serializers.SerializerMethodField()
    has_readable_content = serializers.SerializerMethodField()
    body_owner = serializers.SerializerMethodField()

    def _load_stored(self, user, obj):
        from api.rss.access import get_stored_article
        return get_stored_article(user, obj.pk)

    def _stored(self, obj):
        from api.rss.access import get_stored_article
        current = getattr(self, '_current_stored', None)
        return current if current and current.news_id == obj.pk else get_stored_article(
            getattr(self.context.get('request'), 'user', None), obj.pk)

    def _sources(self, obj):
        from api.rss.access import article_sources
        current = getattr(self, '_current_sources', None)
        return current if current is not None else list(article_sources(
            getattr(self.context.get('request'), 'user', None), obj).select_related('publication'))

    def _channel_policies(self, obj):
        from api.services.source_policy import policy_for_name
        return [p for source in self._sources(obj) if (p := policy_for_name(source.name))]

    def get_channel_ids(self, obj):
        return [source.pk for source in self._sources(obj)]

    def get_channel_names(self, obj):
        return [source.publication.display_name or source.name for source in self._sources(obj)]

    def get_publish_time_inferred(self, obj):
        items = list(obj.source_items.all())
        return bool(items) and all(item.metadata.get('publish_time_inferred', False) for item in items)

    def get_is_medical(self, obj):
        return obj.category.name == '医疗健康' or any(p.default_category == '医疗健康' for p in self._channel_policies(obj))

    def get_reading_policy(self, obj):
        if self._stored(obj).scope == 'summary':
            return 'rss_summary_only'
        return 'standard'

    def get_full_content_completeness(self, obj):
        return self._stored(obj).completeness

    get_content_completeness = get_full_content_completeness

    def get_has_readable_content(self, obj):
        return self._stored(obj).scope == 'full' or bool(self._stored(obj).markdown.strip())

    def get_body_owner(self, obj):
        return self._stored(obj).body_owner

    def _legacy_text(self, obj, field, original):
        from hashlib import sha256
        digest = sha256(original.encode('utf-8')).hexdigest()
        batch = getattr(self, '_legacy_batch', None)
        if batch is not None:
            return batch.get((obj.pk, field, digest, original), '')
        from api.services.stored_readers import legacy_translation
        record = legacy_translation(obj.pk, field, original)
        return record.translated_text if record else ''

    def to_representation(self, instance):
        from api.rss.access import article_sources, authorized_news, get_stored_article
        user = getattr(self.context.get('request'), 'user', None)
        # Bound only to this synchronous representation, never across requests.
        self._translation_key = None
        self._current_stored = self._load_stored(user, instance)
        snapshots = getattr(self, '_preview_snapshots', None)
        self._current_sources = snapshots[instance.pk][1] if snapshots is not None else list(article_sources(user, instance).select_related('publication'))
        try:
            data = super().to_representation(instance)
            stored = self._current_stored
            for key, attr in [('title', 'title'), ('content', 'summary'), ('url', 'url'),
                              ('full_content_revision', 'revision'), ('content_kind', 'content_kind')]:
                if key in data and hasattr(stored, attr):
                    data[key] = getattr(stored, attr)
            for field in ('title', 'content'):
                if field + '_zh' in data:
                    original = getattr(stored, 'summary' if field == 'content' else field, getattr(instance, field))
                    data[field + '_zh'] = self._legacy_text(instance, field, original)
            visible = self._current_sources
            if not visible:
                from django.http import Http404
                raise Http404
            primary = next((s for s in visible if s.pk == instance.source_id), visible[0])
            replacements = dict(source=primary.pk, source_name=primary.publication.display_name or primary.name,
                source_type=primary.source_type, source_region=primary.region, source_url=primary.url,
                source_language=primary.language)
            for key, value in replacements.items():
                if key in data:
                    data[key] = value
            if data.get('related_to') and not authorized_news(user).filter(pk=data['related_to']).exists():
                data['related_to'] = None
            if self._current_stored.scope != 'full':
                data['has_full_content'] = False
                for key in ('full_content', 'full_content_zh'):
                    if key in data:
                        data[key] = ''
                from api.rss.access import BODY_POLICIES
                from api.services.source_policy import policy_for_name
                owner_source = instance.body_owner_source_id or (instance.source_id if instance.body_owner_binding_id is None else None)
                origin = next((source for source in visible if source.pk == owner_source), None)
                policy = policy_for_name(origin.name) if origin else None
                readable_origin = bool(origin and origin.publication.owner == 'legacy'
                    and origin.publication.reading_policy in BODY_POLICIES
                    and (not policy or policy.reading_policy != 'rss_summary_only' or self.get_body_access_granted(instance)))
                if 'can_rss_refetch' in self.fields:
                    readable_origin |= getattr(self, 'get_can_rss_refetch', lambda obj: False)(instance)
                if not readable_origin:
                    for key in ('full_content_fetch_error', 'full_content_fetch_provider', 'full_content_error_code'):
                        if key in data:
                            data[key] = ''
                    for key in ('full_content_fetched_at', 'full_content_zh_fetched_at', 'full_content_quality_score', 'last_full_content_attempt', 'full_content_next_attempt_at'):
                        if key in data:
                            data[key] = None
                    for key in ('full_content_revision', 'full_content_retry_count', 'full_content_priority'):
                        if key in data:
                            data[key] = 0
                    if 'full_content_state' in data:
                        data['full_content_state'] = 'missing'
                    if 'full_content_fetch_status' in data:
                        data['full_content_fetch_status'] = 'unsupported'
            return data
        finally:
            self._current_stored = self._current_sources = None


class NewsListSerializer(ChannelNewsSerializer):
    """Bounded article previews; complete bodies belong to the detail endpoint."""
    SUMMARY_LIMIT = 300
    summary = serializers.SerializerMethodField()
    summary_zh = serializers.SerializerMethodField()
    has_full_content = serializers.SerializerMethodField()
    source_name = serializers.CharField(source='source.name', read_only=True)
    source_type = serializers.CharField(source='source.source_type', read_only=True)
    source_language = serializers.CharField(source='source.language', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    related_to = serializers.PrimaryKeyRelatedField(read_only=True)
    # Summaries preserve the original/translated language and may be empty.
    # Frontend resolves display based on displayMode (zh / original / bilingual)
    translation_status = serializers.CharField(read_only=True)
    translation_error = serializers.CharField(read_only=True)
    translation_retry_count = serializers.IntegerField(read_only=True)
    full_content_fetch_status = serializers.CharField(read_only=True)
    full_content_fetch_error = serializers.CharField(read_only=True)
    full_content_fetch_provider = serializers.CharField(read_only=True)
    full_content_quality_score = serializers.FloatField(read_only=True)
    full_content_retry_count = serializers.IntegerField(read_only=True)
    last_full_content_attempt = serializers.DateTimeField(read_only=True)

    class Meta:
        list_serializer_class = AccessNewsListSerializer
        model = News
        read_only_fields = [
            'content_kind', 'full_content_state', 'full_content_revision',
            'full_content_next_attempt_at', 'full_content_priority', 'full_content_error_code',
        ]
        fields = [
            'source_region', 'channel_ids', 'channel_names', 'is_medical', 'reading_policy', 'body_access_granted', 'publish_time_inferred',
            'full_content_completeness', 'content_completeness', 'has_readable_content', 'body_owner',
            'id', 'title', 'summary', 'title_zh', 'summary_zh', 'author', 'publish_time',
            'has_full_content',
            'source', 'source_name', 'source_type', 'source_language',
            'category', 'category_name',
            'url', 'cover_image', 'created_at',
            'related_to',
            'translation_status', 'translation_error', 'translation_retry_count',
            'full_content_fetch_status', 'full_content_fetch_error',
            'full_content_fetch_provider', 'full_content_quality_score',
            'full_content_retry_count', 'last_full_content_attempt',
            'content_kind', 'full_content_state', 'full_content_revision',
            'full_content_next_attempt_at', 'full_content_priority', 'full_content_error_code',
        ]

    def _load_stored(self, user, obj):
        from types import SimpleNamespace
        from api.rss.access import get_article_access
        snapshots = getattr(self, '_preview_snapshots', None)
        context = snapshots[obj.pk][0] if snapshots is not None else get_article_access(user, obj.pk)
        return SimpleNamespace(news_id=obj.pk, scope=context.scope, markdown=obj.content,
                               completeness=context.completeness, body_owner=context.body_owner)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Summary previews only need the override flag when access is granted.
        # Fetch eligibility belongs to the detail response, not every list row.
        if not data.get('body_access_granted'):
            data.pop('body_access_granted', None)
        return data

    def get_summary(self, obj):
        return (obj.content or '')[:self.SUMMARY_LIMIT]

    def get_has_full_content(self, obj):
        return self._stored(obj).scope == 'full'

    def get_summary_zh(self, obj):
        return self._legacy_text(obj, 'content', obj.content)[:self.SUMMARY_LIMIT]


class NewsDetailSerializer(ChannelNewsSerializer):
    source_name = serializers.CharField(source='source.name', read_only=True)
    source_type = serializers.CharField(source='source.source_type', read_only=True)
    source_url = serializers.URLField(source='source.url', read_only=True)
    source_language = serializers.CharField(source='source.language', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    # title / content are the ORIGINAL language values from DB
    # title_zh / content_zh are Chinese translations
    translation_status = serializers.CharField(read_only=True)
    translation_error = serializers.CharField(read_only=True)
    translation_retry_count = serializers.IntegerField(read_only=True)
    # Full article content
    full_content = serializers.SerializerMethodField()
    has_full_content = serializers.SerializerMethodField()
    full_content_fetched_at = serializers.DateTimeField(read_only=True)
    full_content_zh = serializers.SerializerMethodField()
    full_content_zh_fetched_at = serializers.SerializerMethodField()
    full_content_zh_source = serializers.SerializerMethodField()
    full_content_zh_scope = serializers.SerializerMethodField()
    full_translation_personal_available = serializers.SerializerMethodField()
    full_content_fetch_status = serializers.CharField(read_only=True)
    full_content_fetch_error = serializers.CharField(read_only=True)
    full_content_fetch_provider = serializers.CharField(read_only=True)
    full_content_quality_score = serializers.FloatField(read_only=True)
    full_content_retry_count = serializers.IntegerField(read_only=True)
    last_full_content_attempt = serializers.DateTimeField(read_only=True)
    # True if a background full-article translation worker is still running
    full_translation_active = serializers.SerializerMethodField()

    class Meta:
        model = News
        read_only_fields = [
            'content_kind', 'full_content_state', 'full_content_revision',
            'full_content_next_attempt_at', 'full_content_priority', 'full_content_error_code',
        ]
        fields = [
            'source_region', 'channel_ids', 'channel_names', 'is_medical', 'reading_policy', 'body_access_granted', 'can_fetch_full_content', 'publish_time_inferred',
            'full_content_completeness', 'content_completeness', 'has_readable_content', 'body_owner',
            'id', 'title', 'content', 'title_zh', 'content_zh', 'author', 'publish_time',
            'source', 'source_name', 'source_type', 'source_url', 'source_language',
            'category', 'category_name',
            'url', 'cover_image', 'created_at',
            'related_to',
            'translation_status', 'translation_error', 'translation_retry_count',
            'full_content', 'full_content_fetched_at',
            'has_full_content',
            'full_content_zh', 'full_content_zh_fetched_at', 'full_content_zh_source',
            'full_content_zh_scope', 'full_translation_personal_available',
            'full_content_fetch_status', 'full_content_fetch_error',
            'full_content_fetch_provider', 'full_content_quality_score',
            'full_content_retry_count', 'last_full_content_attempt',
            'content_kind', 'full_content_state', 'full_content_revision',
            'full_content_next_attempt_at', 'full_content_priority', 'full_content_error_code',
            'full_translation_active',
        ]

    def _translation(self, obj):
        from api.services.stored_readers import current_translation
        stored = self._stored(obj)
        key = (stored.news_id, stored.canonical_hash, stored.scope)
        if getattr(self, '_translation_key', None) != key:
            self._translation_key = key
            self._translation_value = current_translation(getattr(self.context.get('request'), 'user', None), stored)
        return self._translation_value

    def get_full_content_zh(self, obj):
        record, _ = self._translation(obj)
        return record.content if record else ''

    def get_full_content_zh_fetched_at(self, obj):
        record, _ = self._translation(obj)
        return record.completed_at if record else None

    def get_full_content_zh_scope(self, obj):
        return self._translation(obj)[1]

    def get_full_translation_personal_available(self, obj):
        from api.services.chatgpt_subscription import active_connection_for_user
        user = getattr(self.context.get('request'), 'user', None)
        connection = active_connection_for_user(user) if getattr(user, 'is_authenticated', False) else None
        return bool(self.get_has_full_content(obj) and connection and connection.connected
                    and not connection.needs_reauth and connection.selected_model)

    def get_full_translation_active(self, obj):
        if not self.get_has_full_content(obj):
            return False
        from api.services.translation_jobs import get_job
        user = getattr(self.context.get('request'), 'user', None)
        from api.services.chatgpt_subscription import active_connection_for_user
        from api.services import chatgpt_subscription_jobs
        connection = active_connection_for_user(user) if getattr(user, 'is_authenticated', False) else None
        if connection is not None:
            private = chatgpt_subscription_jobs.get_job(user.pk, connection.pk, obj.pk, self._stored(obj).canonical_hash)
            if private and not private.done:
                return True
        job = get_job(obj.pk, user_id=getattr(user, 'pk', None), source_digest=self._stored(obj).canonical_hash)
        if job and not job.done:
            return True
        from api.services.shared_translations import task_is_running
        return task_is_running(obj, getattr(self.context.get('request'), 'user', None), stored=self._stored(obj))

    def get_full_content_zh_source(self, obj):
        record, scope = self._translation(obj)
        return ('chatgpt' if scope == 'private' else getattr(record, 'provider', 'legacy')) if record else None

    def get_full_content(self, obj):
        stored = self._stored(obj)
        return stored.markdown if stored.scope == 'full' else ''

    def get_has_full_content(self, obj):
        return self._stored(obj).scope == 'full'


class FavoriteNewsSerializer(serializers.Serializer):
    """Minimal news info embedded in favorite list."""
    id = serializers.IntegerField()
    title = serializers.CharField()
    title_zh = serializers.CharField()
    url = serializers.URLField()
    cover_image = serializers.URLField()
    source_name = serializers.CharField(source='source.name')
    category_name = serializers.CharField(source='category.name')
    publish_time = serializers.DateTimeField()
    created_at = serializers.DateTimeField()

    def to_representation(self, instance):
        from api.rss.access import article_sources, get_article_access
        user = getattr(self.context.get('request'), 'user', None)
        get_article_access(user, instance.pk)
        data = super().to_representation(instance)
        sources = list(article_sources(user, instance).select_related('publication'))
        if not sources:
            from django.http import Http404
            raise Http404
        source = next((source for source in sources if source.pk == instance.source_id), sources[0])
        data['source_name'] = source.publication.display_name or source.name
        from api.services.stored_readers import legacy_translation
        translation = legacy_translation(instance.pk, 'title', instance.title)
        data['title_zh'] = translation.translated_text if translation else ''
        return data


class FavoriteSerializer(serializers.ModelSerializer):
    news = FavoriteNewsSerializer(read_only=True)
    news_id = serializers.IntegerField(write_only=True, required=True)
    type = serializers.ChoiceField(choices=['like', 'bookmark'])

    class Meta:
        model = Favorite
        fields = ['id', 'news', 'news_id', 'type', 'created_at']
        read_only_fields = ['id', 'created_at']

    def create(self, validated_data):
        request = self.context['request']
        news_id = validated_data.pop('news_id')

        from .models import News
        from api.rss.access import authorized_news
        if not authorized_news(request.user).filter(pk=news_id).exists():
            raise serializers.ValidationError({'news_id': 'News not found'})

        fav, created = Favorite.objects.get_or_create(
            user=request.user,
            news_id=news_id,
            type=validated_data['type'],
            defaults=validated_data,
        )
        self.instance = fav
        self._created = created
        return fav

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if hasattr(self, '_created'):
            data['created'] = self._created
        elif getattr(self, '_removed', False):
            data['removed'] = True
        return data


class ProviderComparisonSerializer(serializers.ModelSerializer):
    news_title = serializers.CharField(source='news.title', read_only=True)
    source_name = serializers.CharField(source='news.source.name', read_only=True)

    class Meta:
        model = ProviderComparison
        fields = [
            'id', 'run_id', 'news', 'news_title', 'source_name', 'url',
            'expected_title', 'summary', 'provider', 'ok', 'title',
            'canonical_url', 'markdown', 'quality_score', 'error',
            'validation_reasons', 'content_length', 'extractor', 'metadata',
            'elapsed_ms', 'created_at',
        ]
        read_only_fields = fields


class ProviderComparisonRunSerializer(serializers.Serializer):
    news_id = serializers.IntegerField(required=False)
    url = serializers.URLField(required=False, max_length=500)
    expected_title = serializers.CharField(required=False, allow_blank=True, max_length=500)
    summary = serializers.CharField(required=False, allow_blank=True)
    providers = serializers.ListField(
        child=serializers.CharField(max_length=64),
        required=False,
        allow_empty=False,
    )

    def validate(self, attrs):
        if not attrs.get('news_id') and not attrs.get('url'):
            raise serializers.ValidationError('news_id or url is required')
        if attrs.get('news_id') and attrs.get('url'):
            raise serializers.ValidationError('Use either news_id or url, not both')
        return attrs


class BlockedNewsSerializer(serializers.ModelSerializer):
    news = FavoriteNewsSerializer(read_only=True)
    news_id = serializers.IntegerField(write_only=True, required=True)

    class Meta:
        model = BlockedNews
        fields = ['id', 'news', 'news_id', 'created_at']
        read_only_fields = ['id', 'created_at']

    def create(self, validated_data):
        request = self.context['request']
        news_id = validated_data.pop('news_id')

        from .models import News as _News
        from api.rss.access import authorized_news
        if not authorized_news(request.user).filter(pk=news_id).exists():
            raise serializers.ValidationError({'news_id': 'News not found'})

        block, created = BlockedNews.objects.get_or_create(
            user=request.user,
            news_id=news_id,
            defaults=validated_data,
        )
        self.instance = block
        self._created = created
        return block

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if hasattr(self, '_created'):
            data['created'] = self._created
        elif getattr(self, '_removed', False):
            data['removed'] = True
        return data


class ResearchSessionSerializer(serializers.ModelSerializer):
    """Full research session with message history."""
    message_count = serializers.SerializerMethodField()

    class Meta:
        model = ResearchSession
        fields = ['id', 'title', 'messages', 'is_archived', 'message_count', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def to_representation(self, instance):
        from api.services.research.access import require_session_evidence
        require_session_evidence(instance, getattr(self.context.get('request'), 'user', None))
        return super().to_representation(instance)

    def get_message_count(self, obj):
        return len(obj.messages) if obj.messages else 0


class ResearchSessionListSerializer(serializers.ModelSerializer):
    """Lightweight session info for list views (no full messages)."""
    message_count = serializers.SerializerMethodField()

    class Meta:
        model = ResearchSession
        fields = ['id', 'title', 'is_archived', 'message_count', 'created_at', 'updated_at']

    def get_message_count(self, obj):
        return len(obj.messages) if obj.messages else 0


class ResearchSearchResultSerializer(serializers.ModelSerializer):
    """Full search result including result_data."""
    class Meta:
        model = ResearchSearchResult
        fields = ['id', 'session', 'tool_name', 'query', 'result_type',
                  'source', 'title', 'url', 'hit_count', 'result_data', 'created_at']
        read_only_fields = fields


class ResearchSearchResultListSerializer(serializers.ModelSerializer):
    """Lightweight search result for list views (no result_data)."""
    class Meta:
        model = ResearchSearchResult
        fields = ['id', 'tool_name', 'query', 'result_type',
                  'source', 'title', 'url', 'hit_count', 'created_at']
