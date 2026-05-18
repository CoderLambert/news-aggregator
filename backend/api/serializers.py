from rest_framework import serializers
from .models import Category, Source, News


class CategorySerializer(serializers.ModelSerializer):
    news_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'description', 'news_count']


class SourceSerializer(serializers.ModelSerializer):
    news_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Source
        fields = ['id', 'name', 'url', 'logo', 'country', 'language', 'news_count']


class NewsListSerializer(serializers.ModelSerializer):
    source_name = serializers.CharField(source='source.name', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)

    class Meta:
        model = News
        fields = [
            'id', 'title', 'author', 'publish_time',
            'source', 'source_name', 'category', 'category_name',
            'url', 'cover_image', 'created_at',
        ]


class NewsDetailSerializer(serializers.ModelSerializer):
    source_name = serializers.CharField(source='source.name', read_only=True)
    source_url = serializers.URLField(source='source.url', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)

    class Meta:
        model = News
        fields = [
            'id', 'title', 'content', 'author', 'publish_time',
            'source', 'source_name', 'source_url',
            'category', 'category_name',
            'url', 'cover_image', 'created_at',
        ]
