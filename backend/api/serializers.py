from rest_framework import serializers
from .models import Category, Source, News


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


def _resolve_title(news, lang):
    """Return title in requested language."""
    if lang == 'zh' and news.source.language == 'en' and news.title_zh:
        return news.title_zh
    return news.title


def _resolve_content(news, lang):
    """Return content in requested language."""
    if lang == 'zh' and news.source.language == 'en' and news.content_zh:
        return news.content_zh
    return news.content


class NewsListSerializer(serializers.ModelSerializer):
    source_name = serializers.CharField(source='source.name', read_only=True)
    source_type = serializers.CharField(source='source.source_type', read_only=True)
    source_language = serializers.CharField(source='source.language', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    related_to = serializers.PrimaryKeyRelatedField(read_only=True)
    title = serializers.SerializerMethodField()
    content = serializers.SerializerMethodField()
    # Translation status fields
    translation_status = serializers.CharField(read_only=True)
    translation_error = serializers.CharField(read_only=True)
    translation_retry_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = News
        fields = [
            'id', 'title', 'content', 'author', 'publish_time',
            'source', 'source_name', 'source_type', 'source_language',
            'category', 'category_name',
            'url', 'cover_image', 'created_at',
            'related_to',
            'translation_status', 'translation_error', 'translation_retry_count',
        ]

    def get_title(self, obj):
        lang = self.context.get('lang', 'original')
        return _resolve_title(obj, lang)

    def get_content(self, obj):
        lang = self.context.get('lang', 'original')
        return _resolve_content(obj, lang)


class NewsDetailSerializer(serializers.ModelSerializer):
    source_name = serializers.CharField(source='source.name', read_only=True)
    source_type = serializers.CharField(source='source.source_type', read_only=True)
    source_url = serializers.URLField(source='source.url', read_only=True)
    source_language = serializers.CharField(source='source.language', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    title = serializers.SerializerMethodField()
    content = serializers.SerializerMethodField()
    # Translation status fields
    translation_status = serializers.CharField(read_only=True)
    translation_error = serializers.CharField(read_only=True)
    translation_retry_count = serializers.IntegerField(read_only=True)
    # Full article content
    full_content = serializers.CharField(read_only=True)
    full_content_fetched_at = serializers.DateTimeField(read_only=True)

    class Meta:
        model = News
        fields = [
            'id', 'title', 'content', 'author', 'publish_time',
            'source', 'source_name', 'source_type', 'source_url', 'source_language',
            'category', 'category_name',
            'url', 'cover_image', 'created_at',
            'related_to',
            'translation_status', 'translation_error', 'translation_retry_count',
            'full_content', 'full_content_fetched_at',
        ]

    def get_title(self, obj):
        lang = self.context.get('lang', 'original')
        return _resolve_title(obj, lang)

    def get_content(self, obj):
        lang = self.context.get('lang', 'original')
        return _resolve_content(obj, lang)
