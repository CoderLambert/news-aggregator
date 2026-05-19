from django.contrib import admin
from .models import Category, Source, News


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'description', 'created_at']
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ['name']


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ['name', 'url', 'country', 'language', 'source_type', 'created_at']
    list_filter = ['source_type']
    search_fields = ['name']


@admin.register(News)
class NewsAdmin(admin.ModelAdmin):
    list_display = ['title', 'source', 'category', 'publish_time', 'created_at', 'title_hash', 'related_to']
    list_filter = ['source', 'category', 'publish_time', 'related_to']
    search_fields = ['title', 'content', 'author']
    readonly_fields = ['created_at', 'title_hash']
    date_hierarchy = 'publish_time'
    raw_id_fields = ['source', 'category']
