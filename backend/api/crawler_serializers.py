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
    target_name = serializers.CharField(source='target.display_name', read_only=True)
    spider_name = serializers.CharField(source='target.spider_name', read_only=True)
    duration_seconds = serializers.SerializerMethodField()

    class Meta:
        model = CrawlRun
        fields = [
            'id', 'batch', 'spider_name', 'target_name', 'status', 'queued_at',
            'started_at', 'heartbeat_at', 'finished_at', 'duration_seconds',
            'exit_code', 'items', 'responses', 'errors', 'http_statuses',
            'stats', 'safe_error', 'retry_of', 'cancel_requested_at',
        ]

    def get_duration_seconds(self, obj):
        if not obj.started_at:
            return None
        end = obj.finished_at or obj.heartbeat_at
        if not end:
            return None
        return max(0, int((end - obj.started_at).total_seconds()))


class CrawlerTargetSerializer(serializers.ModelSerializer):
    active_run = serializers.SerializerMethodField()

    class Meta:
        model = CrawlerTarget
        fields = [
            'spider_name', 'display_name', 'enabled', 'sort_order', 'last_status',
            'last_started_at', 'last_finished_at', 'last_items', 'last_responses',
            'last_errors', 'last_safe_error', 'active_run',
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


class CrawlBatchSerializer(serializers.ModelSerializer):
    runs = CrawlRunSerializer(many=True, read_only=True)

    class Meta:
        model = CrawlBatch
        fields = [
            'id', 'trigger', 'status', 'queued_at', 'started_at', 'finished_at',
            'total', 'succeeded', 'failed', 'cancelled', 'runs',
        ]
