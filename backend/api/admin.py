from django.contrib import admin
from .models import (
    ArticleFetchEvent,
    Category,
    JinaFallbackPolicy,
    LegacyChatArchive,
    News,
    Source,
    SourceConfig,
    SourceEndpoint,
)


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


class SourceEndpointInline(admin.TabularInline):
    model = SourceEndpoint
    extra = 0
    can_delete = False
    fields = [
        'kind', 'url', 'allowed_domains', 'priority', 'parser_config', 'conditional_requests',
        'request_interval_seconds', 'max_response_bytes', 'max_pages', 'max_items', 'enabled',
    ]
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SourceConfig)
class SourceConfigAdmin(admin.ModelAdmin):
    list_display = ['source_key', 'publisher_name', 'channel_name', 'status', 'config_version', 'probed_at', 'approved_at']
    list_filter = ['status', 'region', 'content_kind', 'reading_policy']
    search_fields = ['source_key', 'publisher_name', 'channel_name']
    inlines = [SourceEndpointInline]
    readonly_fields = [field.name for field in SourceConfig._meta.fields]

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


@admin.register(News)
class NewsAdmin(admin.ModelAdmin):
    list_display = ['title', 'source', 'category', 'publish_time', 'created_at', 'title_hash', 'related_to']
    list_filter = ['source', 'category', 'publish_time', 'related_to']
    search_fields = ['title', 'content', 'author']
    readonly_fields = [
        'created_at', 'title_hash', 'url', 'content_kind',
        *[field.name for field in News._meta.fields if field.name.startswith('full_content')],
        'last_full_content_attempt',
    ]
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


@admin.register(JinaFallbackPolicy)
class JinaFallbackPolicyAdmin(admin.ModelAdmin):
    list_display = ['domain', 'enabled', 'auto_discovered', 'failure_count', 'last_seen_at', 'updated_at']
    list_filter = ['enabled', 'auto_discovered']
    search_fields = ['domain']
    readonly_fields = [
        'domain', 'auto_discovered', 'failure_count', 'last_failure_codes',
        'last_seen_at', 'updated_by', 'created_at', 'updated_at',
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ArticleFetchEvent)
class ArticleFetchEventAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'news_id', 'domain', 'outcome', 'provider', 'persistence_outcome', 'physical_requests', 'elapsed_ms']
    list_filter = ['outcome', 'provider', 'created_at']
    search_fields = ['domain', 'provider']
    readonly_fields = [
        'news', 'domain', 'outcome', 'provider', 'failure_codes', 'quality_score',
        'content_length', 'elapsed_ms', 'created_at', 'source_key', 'http_statuses',
        'physical_requests', 'retry_after_at', 'persistence_outcome', 'logical_outcome',
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
