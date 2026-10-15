from rest_framework import serializers

from django.db import transaction
from urllib.parse import urlsplit

from api.models import (
    Category, CrawlBatch, CrawlRun, CrawlerSettings, CrawlerTarget, Source,
    SourceConfig, SourceEndpoint,
)


class CrawlerSettingsSerializer(serializers.ModelSerializer):
    worker_online = serializers.BooleanField(read_only=True, default=False)

    class Meta:
        model = CrawlerSettings
        fields = [
            'scheduler_enabled', 'interval_seconds', 'run_on_worker_start',
            'next_run_at', 'worker_heartbeat_at', 'worker_instance_id',
            'worker_online', 'updated_at',
        ]
        read_only_fields = [
            'next_run_at', 'worker_heartbeat_at', 'worker_instance_id',
            'worker_online', 'updated_at',
        ]

    def validate_interval_seconds(self, value):
        if value < 60 or value > 604800:
            raise serializers.ValidationError('抓取间隔必须在 60 秒到 7 天之间。')
        return value


class CrawlRunSerializer(serializers.ModelSerializer):
    source_active = serializers.SerializerMethodField()
    target_name = serializers.CharField(source='target.display_name', read_only=True)
    spider_name = serializers.CharField(source='target.spider_name', read_only=True)
    duration_seconds = serializers.SerializerMethodField()
    latest_retry_id = serializers.SerializerMethodField()
    latest_retry_status = serializers.SerializerMethodField()
    latest_retry_display_status = serializers.SerializerMethodField()

    class Meta:
        model = CrawlRun
        fields = [
            'id', 'batch', 'spider_name', 'target_name', 'status', 'queued_at',
            'started_at', 'heartbeat_at', 'finished_at', 'duration_seconds',
            'exit_code', 'items', 'responses', 'errors', 'http_statuses',
            'stats', 'safe_error', 'retry_of', 'latest_retry_id',
            'latest_retry_status', 'latest_retry_display_status', 'cancel_requested_at', 'source_active',
        ]

    def get_source_active(self, obj):
        from api.services.source_registry import runtime_registry
        # Nested serializers share their root context. Snapshot once per response,
        # rather than querying every dynamic source for every historical run.
        if 'active_source_keys' not in self.context:
            self.context['active_source_keys'] = frozenset(runtime_registry())
        return obj.target_id in self.context['active_source_keys']

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if self.context.get('dashboard_summary'):
            # The dashboard uses these outcome fields; full counters remain on
            # the run and batch detail endpoints.
            data['stats'] = {
                key: value for key, value in data['stats'].items()
                if key in {'finish_reason', 'outcome', 'entries_committed', 'entries_changed', 'warnings'}
            }
        return data

    def get_duration_seconds(self, obj):
        if not obj.started_at:
            return None
        end = obj.finished_at or obj.heartbeat_at
        if not end:
            return None
        return max(0, int((end - obj.started_at).total_seconds()))

    def _latest_retry(self, obj):
        prefetched = getattr(obj, 'prefetched_retries', None)
        if prefetched is not None:
            return prefetched[0] if prefetched else None
        if not hasattr(obj, '_serialized_latest_retry'):
            obj._serialized_latest_retry = obj.retries.order_by('-queued_at').only('id', 'status', 'exit_code', 'stats').first()
        return obj._serialized_latest_retry

    def get_latest_retry_id(self, obj):
        retry = self._latest_retry(obj)
        return retry.pk if retry else None

    def get_latest_retry_status(self, obj):
        retry = self._latest_retry(obj)
        return retry.status if retry else None

    def get_latest_retry_display_status(self, obj):
        retry = self._latest_retry(obj)
        if not retry:
            return None
        if retry.exit_code != 0 or retry.status not in {'failed', 'succeeded'}:
            return retry.status
        if retry.status == 'failed' and retry.stats.get('entries_committed', 0) > 0:
            return 'partial'
        outcome = retry.stats.get('outcome')
        return outcome if outcome in {'deferred', 'rate_limited', 'blocked', 'network_error', 'http_error', 'filtered', 'parse_failed'} else retry.status


class CrawlerTargetSerializer(serializers.ModelSerializer):
    active_run = serializers.SerializerMethodField()
    supported = serializers.SerializerMethodField()
    unsupported_reason = serializers.SerializerMethodField()
    last_result_status = serializers.SerializerMethodField()

    class Meta:
        model = CrawlerTarget
        fields = [
            'spider_name', 'display_name', 'enabled', 'sort_order', 'last_status',
            'last_started_at', 'last_finished_at', 'last_items', 'last_responses',
            'last_errors', 'last_safe_error', 'active_run', 'supported', 'unsupported_reason', 'last_result_status',
        ]
        read_only_fields = [
            'spider_name', 'display_name', 'sort_order', 'last_status',
            'last_started_at', 'last_finished_at', 'last_items', 'last_responses',
            'last_errors', 'last_safe_error', 'active_run',
        ]

    def get_active_run(self, obj):
        runs = getattr(obj, 'prefetched_active_runs', None)
        run = runs[0] if runs else None
        if run is None:
            return None
        return CrawlRunSerializer(run, context=self.context).data

    def get_supported(self, obj):
        from api.services.source_policy import policy_for_key
        policy = policy_for_key(obj.spider_name)
        return bool(policy and not policy.unsupported_reason)

    def get_last_result_status(self, obj):
        stats = getattr(obj, 'last_run_stats', None) or {}
        if getattr(obj, 'last_run_exit_code', None) != 0 or obj.last_status not in {'failed', 'succeeded'}:
            return obj.last_status
        if obj.last_status == 'failed' and stats.get('entries_committed', 0) > 0:
            return 'partial'
        outcome = stats.get('outcome')
        return outcome if outcome in {'deferred', 'rate_limited', 'blocked', 'network_error', 'http_error', 'filtered', 'parse_failed'} else obj.last_status

    def get_unsupported_reason(self, obj):
        from api.services.source_policy import policy_for_key
        policy = policy_for_key(obj.spider_name)
        reason = policy.unsupported_reason if policy else 'unknown_source'
        return {'authorized_delivery_required': '需要官方授权采集渠道。',
                'public_access_denied': '来源已拒绝公开采集，已移除。',
                'publisher_permission_required': '来源要求书面采集许可，已移除。',
                'publisher_identity_unavailable': '当前入口无法可靠核验文章链接。',
                'invalid_feed_endpoint': '尚未找到有效的官方 Feed。',
                'unknown_source': '尚未配置受支持的来源。'}.get(reason, '')

    def validate(self, attrs):
        if attrs.get('enabled') is True and self.instance and not self.get_supported(self.instance):
            raise serializers.ValidationError({'enabled': self.get_unsupported_reason(self.instance)})
        return attrs


class SourceEndpointSerializer(serializers.ModelSerializer):
    class Meta:
        model = SourceEndpoint
        fields = [
            'id', 'kind', 'url', 'allowed_domains', 'priority', 'parser_config',
            'conditional_requests', 'request_interval_seconds', 'max_response_bytes',
            'max_pages', 'max_items', 'enabled',
        ]
        read_only_fields = ['id']

    def validate_allowed_domains(self, value):
        if (not isinstance(value, list) or not 1 <= len(value) <= 10 or
                any(not isinstance(item, str) or not item or len(item) > 253 for item in value)):
            raise serializers.ValidationError('允许域名须为 1–10 个有效域名。')
        normalized = []
        for item in value:
            host = item.lower().rstrip('.')
            if host.startswith('*.') or '/' in host or ':' in host or '@' in host or host == 'localhost':
                raise serializers.ValidationError('不允许通配符、端口、本地域名或路径。')
            try:
                host = host.encode('idna').decode('ascii')
            except UnicodeError:
                raise serializers.ValidationError('域名无效。') from None
            normalized.append(host)
        return list(dict.fromkeys(normalized))

    def validate_parser_config(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('解析配置须为 JSON 对象。')
        return value

    def validate(self, attrs):
        from api.services.channel_intake import normalize_intake_url
        from bs4 import BeautifulSoup
        import re

        data = {**(self.instance and {
            field: getattr(self.instance, field)
            for field in ('kind', 'url', 'allowed_domains', 'parser_config', 'request_interval_seconds',
                          'max_response_bytes', 'max_pages', 'max_items')
        } or {}), **attrs}
        url, host, _path, _query = normalize_intake_url(data['url'])
        data['url'] = url
        attrs['url'] = url
        domains = data.get('allowed_domains', [])
        if host not in set(domains):
            raise serializers.ValidationError({'allowed_domains': '必须包含入口 URL 的官方域名。'})
        interval = data.get('request_interval_seconds', 10)
        size = data.get('max_response_bytes', 2 * 1024 * 1024)
        pages = data.get('max_pages', 1)
        items = data.get('max_items', 50)
        if not 3 <= interval <= 86400:
            raise serializers.ValidationError({'request_interval_seconds': '请求间隔须为 3 秒到 24 小时。'})
        if not 1024 <= size <= 8 * 1024 * 1024:
            raise serializers.ValidationError({'max_response_bytes': '响应上限须为 1 KiB 到 8 MiB。'})
        if not 1 <= pages <= 5 or not 1 <= items <= 200:
            raise serializers.ValidationError('分页最多 5 页，每次最多 200 条。')

        config = data.get('parser_config') or {}
        kind = data['kind']
        allowed_keys = {
            'rss': {'identity_field', 'title_field', 'link_field', 'summary_field', 'published_field', 'full_content_fields'},
            'atom': {'identity_field', 'title_field', 'link_field', 'summary_field', 'published_field', 'full_content_fields'},
            'json': {'list_path', 'fields', 'next_path'},
            'html': {'list_item', 'title', 'link', 'summary', 'date', 'content', 'date_format', 'next'},
        }[kind]
        extra = set(config) - allowed_keys
        if extra:
            raise serializers.ValidationError({'parser_config': f'不支持的解析字段：{", ".join(sorted(extra))}'})
        path_pattern = re.compile(r'^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*$')
        if kind == 'json':
            if not path_pattern.fullmatch(str(config.get('list_path', ''))):
                raise serializers.ValidationError({'parser_config': 'JSON list_path 必须是有限点路径。'})
            fields = config.get('fields')
            required = {'identity', 'title', 'link', 'published'}
            if not isinstance(fields, dict) or not required <= set(fields) or set(fields) - (required | {'summary', 'content', 'author', 'image'}):
                raise serializers.ValidationError({'parser_config': 'JSON fields 缺少必需映射或包含未知映射。'})
            if any(not path_pattern.fullmatch(str(value)) for value in fields.values()):
                raise serializers.ValidationError({'parser_config': 'JSON 字段映射必须是有限点路径。'})
            if config.get('next_path') and not path_pattern.fullmatch(str(config['next_path'])):
                raise serializers.ValidationError({'parser_config': 'JSON next_path 必须是有限点路径。'})
        elif kind == 'html':
            for key in ('list_item', 'title', 'link', 'date'):
                if not isinstance(config.get(key), str) or not config[key].strip():
                    raise serializers.ValidationError({'parser_config': f'HTML 配置缺少 {key}。'})
            for key in ('list_item', 'title', 'link', 'summary', 'date', 'content', 'next'):
                selector = config.get(key)
                if not selector:
                    continue
                if not isinstance(selector, str) or len(selector) > 200:
                    raise serializers.ValidationError({'parser_config': f'{key} 选择器过长或无效。'})
                try:
                    BeautifulSoup('<div></div>', 'html.parser').select(selector)
                except Exception:
                    raise serializers.ValidationError({'parser_config': f'{key} 不是有效 CSS 选择器。'}) from None
        else:
            full_fields = config.get('full_content_fields', [])
            if (not isinstance(full_fields, list) or
                    any(value not in {'description', 'content:encoded', 'atom:content'} for value in full_fields)):
                raise serializers.ValidationError({'parser_config': 'RSS/Atom 正文字段不在允许列表中。'})
        return attrs


class SourceConfigSerializer(serializers.ModelSerializer):
    endpoints = SourceEndpointSerializer(many=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    source_id = serializers.IntegerField(source='source.id', read_only=True)
    maintenance = serializers.SerializerMethodField()
    probe_is_current = serializers.BooleanField(read_only=True)
    approval_is_current = serializers.BooleanField(read_only=True)
    can_enable = serializers.SerializerMethodField()

    class Meta:
        model = SourceConfig
        fields = [
            'source_key', 'source_id', 'publisher_name', 'channel_name', 'category', 'category_name',
            'region', 'language', 'content_kind', 'reading_policy', 'status', 'config_version',
            'summary_allowed', 'feed_full_content_allowed', 'official_html_full_content_allowed',
            'probe_summary', 'probed_config_version', 'probed_at', 'approved_config_version',
            'approved_at', 'unavailable_reason', 'maintenance', 'probe_is_current',
            'approval_is_current', 'can_enable', 'endpoints', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'status', 'config_version', 'probe_summary', 'probed_config_version', 'probed_at',
            'approved_config_version', 'approved_at', 'unavailable_reason', 'created_at', 'updated_at',
        ]

    def get_maintenance(self, obj):
        return 'database'

    def get_can_enable(self, obj):
        return obj.probe_is_current and obj.approval_is_current and obj.status in {'approved', 'enabled'}

    def validate_source_key(self, value):
        from api.services.source_policy import POLICIES
        if self.instance is None and value in POLICIES:
            raise serializers.ValidationError('该 source_key 由代码维护，不能被后台覆盖。')
        return value

    def validate(self, attrs):
        if self.instance is None and not attrs.get('endpoints'):
            raise serializers.ValidationError({'endpoints': '至少需要一个入口。'})
        content_kind = attrs.get('content_kind', getattr(self.instance, 'content_kind', None))
        reading_policy = attrs.get('reading_policy', getattr(self.instance, 'reading_policy', None))
        html_body = attrs.get('official_html_full_content_allowed',
                              getattr(self.instance, 'official_html_full_content_allowed', False))
        if content_kind == 'regulatory_data' and reading_policy != 'regulatory_data':
            raise serializers.ValidationError({'reading_policy': '监管数据必须使用 regulatory_data 读取政策。'})
        if html_body and reading_policy == 'summary_only':
            raise serializers.ValidationError({'official_html_full_content_allowed': '摘要模式不能批准网页正文。'})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        endpoints = validated_data.pop('endpoints')
        user = self.context['request'].user
        primary_url = endpoints[0]['url']
        source, created = Source.objects.get_or_create(
            name=validated_data['channel_name'],
            defaults={
                'url': primary_url, 'region': validated_data.get('region', 'domestic'),
                'country': 'CN' if validated_data.get('region', 'domestic') == 'domestic' else '',
                'language': validated_data.get('language', 'zh'), 'source_type': 'news',
                'description': f"{validated_data['publisher_name']} · {validated_data['channel_name']}",
            },
        )
        if not created and hasattr(source, 'crawler_config'):
            raise serializers.ValidationError({'channel_name': '该频道已经绑定来源配置。'})
        config = SourceConfig.objects.create(source=source, created_by=user, **validated_data)
        SourceEndpoint.objects.bulk_create([SourceEndpoint(source_config=config, **data) for data in endpoints])
        CrawlerTarget.objects.update_or_create(
            spider_name=config.source_key,
            defaults={'display_name': config.channel_name, 'enabled': False},
        )
        return config

    @transaction.atomic
    def update(self, instance, validated_data):
        endpoints = validated_data.pop('endpoints', None)
        current_endpoints = list(instance.endpoints.order_by('priority', 'id').values(
            'kind', 'url', 'allowed_domains', 'priority', 'parser_config', 'conditional_requests',
            'request_interval_seconds', 'max_response_bytes', 'max_pages', 'max_items', 'enabled',
        ))
        endpoint_changed = endpoints is not None and current_endpoints != endpoints
        field_changed = any(getattr(instance, key) != value for key, value in validated_data.items())
        if not endpoint_changed and not field_changed:
            return instance
        for key, value in validated_data.items():
            setattr(instance, key, value)
        instance.config_version += 1
        instance.status = 'draft'
        instance.probe_summary = {}
        instance.probed_config_version = None
        instance.probed_at = None
        instance.approved_config_version = None
        instance.approved_by = None
        instance.approved_at = None
        instance.unavailable_reason = ''
        instance.save()
        if endpoints is not None:
            instance.endpoints.all().delete()
            SourceEndpoint.objects.bulk_create([SourceEndpoint(source_config=instance, **data) for data in endpoints])
        CrawlerTarget.objects.filter(pk=instance.source_key).update(enabled=False, display_name=instance.channel_name)
        if instance.source_id:
            Source.objects.filter(pk=instance.source_id).update(
                name=instance.channel_name, region=instance.region, language=instance.language,
            )
        return instance


class CrawlBatchSerializer(serializers.ModelSerializer):
    runs = CrawlRunSerializer(many=True, read_only=True)

    class Meta:
        model = CrawlBatch
        fields = [
            'id', 'trigger', 'status', 'queued_at', 'started_at', 'finished_at',
            'total', 'succeeded', 'failed', 'cancelled', 'runs',
        ]
