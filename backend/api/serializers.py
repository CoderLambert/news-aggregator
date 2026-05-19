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


class NewsListSerializer(serializers.ModelSerializer):
    source_name = serializers.CharField(source='source.name', read_only=True)
    source_type = serializers.CharField(source='source.source_type', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    related_to = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = News
        fields = [
            'id', 'title', 'author', 'publish_time',
            'source', 'source_name', 'source_type',
            'category', 'category_name',
            'url', 'cover_image', 'created_at',
            'related_to',
        ]


class NewsDetailSerializer(serializers.ModelSerializer):
    source_name = serializers.CharField(source='source.name', read_only=True)
    source_type = serializers.CharField(source='source.source_type', read_only=True)
    source_url = serializers.URLField(source='source.url', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)

    class Meta:
        model = News
        fields = [
            'id', 'title', 'content', 'author', 'publish_time',
            'source', 'source_name', 'source_type', 'source_url',
            'category', 'category_name',
            'url', 'cover_image', 'created_at',
            'related_to',
        ]
