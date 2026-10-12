from django.contrib import admin
from .models import Category, LegacyChatArchive, News, Source


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


@admin.register(LegacyChatArchive)
class LegacyChatArchiveAdmin(admin.ModelAdmin):
    list_display = ['session_id', 'news_id', 'title', 'created_at', 'updated_at']
    search_fields = ['title', 'url']
    readonly_fields = ['session_id', 'news_id', 'title', 'url', 'messages', 'created_at', 'updated_at']

    def has_module_permission(self, request):
        return bool(request.user.is_active and request.user.is_superuser and super().has_module_permission(request))

    def has_view_permission(self, request, obj=None):
        return bool(request.user.is_active and request.user.is_superuser and super().has_view_permission(request, obj))

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
