from rest_framework import serializers
from .models import Category, Source, News, Favorite, BlockedNews, ProviderComparison, ResearchSession, ResearchSearchResult


class CategorySerializer(serializers.ModelSerializer):
    news_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'description', 'news_count']


class SourceSerializer(serializers.ModelSerializer):
    news_count = serializers.IntegerField(read_only=True, default=0)
    source_type = serializers.CharField(read_only=True)

    class Meta:
        model = Source
        fields = ['id', 'name', 'url', 'logo', 'country', 'language', 'source_type', 'news_count']


class NewsListSerializer(serializers.ModelSerializer):
    source_name = serializers.CharField(source='source.name', read_only=True)
    source_type = serializers.CharField(source='source.source_type', read_only=True)
    source_language = serializers.CharField(source='source.language', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    related_to = serializers.PrimaryKeyRelatedField(read_only=True)
    # title / content are the ORIGINAL language values from DB
    # title_zh / content_zh are Chinese translations (may be empty)
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
        model = News
        fields = [
            'id', 'title', 'content', 'title_zh', 'content_zh', 'author', 'publish_time',
            'source', 'source_name', 'source_type', 'source_language',
            'category', 'category_name',
            'url', 'cover_image', 'created_at',
            'related_to',
            'translation_status', 'translation_error', 'translation_retry_count',
            'full_content_fetch_status', 'full_content_fetch_error',
            'full_content_fetch_provider', 'full_content_quality_score',
            'full_content_retry_count', 'last_full_content_attempt',
        ]


class NewsDetailSerializer(serializers.ModelSerializer):
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
    full_content = serializers.CharField(read_only=True)
    full_content_fetched_at = serializers.DateTimeField(read_only=True)
    full_content_zh = serializers.CharField(read_only=True)
    full_content_zh_fetched_at = serializers.DateTimeField(read_only=True)
    full_content_zh_source = serializers.SerializerMethodField()
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
        fields = [
            'id', 'title', 'content', 'title_zh', 'content_zh', 'author', 'publish_time',
            'source', 'source_name', 'source_type', 'source_url', 'source_language',
            'category', 'category_name',
            'url', 'cover_image', 'created_at',
            'related_to',
            'translation_status', 'translation_error', 'translation_retry_count',
            'full_content', 'full_content_fetched_at',
            'full_content_zh', 'full_content_zh_fetched_at', 'full_content_zh_source',
            'full_content_fetch_status', 'full_content_fetch_error',
            'full_content_fetch_provider', 'full_content_quality_score',
            'full_content_retry_count', 'last_full_content_attempt',
            'full_translation_active',
        ]

    def get_full_translation_active(self, obj):
        """True if a background translation worker is still running for this article."""
        try:
            from .services.translation_jobs import get_job
            job = get_job(obj.pk)
            return bool(job and not job.done)
        except Exception:
            return False

    def get_full_content_zh_source(self, obj):
        """Return source of Chinese translation: 'link' or 'llm'."""
        if not obj.full_content_zh:
            return None
        return 'llm'


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
        if not News.objects.filter(pk=news_id).exists():
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
        if not _News.objects.filter(pk=news_id).exists():
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
