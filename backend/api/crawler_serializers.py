from rest_framework import serializers

from api.models import CrawlBatch, CrawlRun, CrawlerSettings, CrawlerTarget


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
        from api.management.commands.crawl import SPIDERS
        return obj.target_id in SPIDERS

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
        return CrawlRunSerializer(run).data

    def get_supported(self, obj):
        from api.services.source_policy import POLICIES
        policy = POLICIES.get(obj.spider_name)
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
        from api.services.source_policy import POLICIES
        policy = POLICIES.get(obj.spider_name)
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


class CrawlBatchSerializer(serializers.ModelSerializer):
    runs = CrawlRunSerializer(many=True, read_only=True)

    class Meta:
        model = CrawlBatch
        fields = [
            'id', 'trigger', 'status', 'queued_at', 'started_at', 'finished_at',
            'total', 'succeeded', 'failed', 'cancelled', 'runs',
        ]
