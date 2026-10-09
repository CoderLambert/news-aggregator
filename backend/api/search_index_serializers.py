from rest_framework import serializers

from api.models import SearchIndexRun, SearchIndexSettings


class SearchIndexSettingsSerializer(serializers.ModelSerializer):
    worker_online = serializers.BooleanField(read_only=True, default=False)

    class Meta:
        model = SearchIndexSettings
        fields = [
            'enabled', 'interval_seconds', 'batch_size', 'active_collection',
            'model_name', 'schema_version', 'next_run_at', 'worker_heartbeat_at',
            'worker_instance_id', 'worker_online', 'last_success_at', 'updated_at',
        ]
        read_only_fields = [
            'active_collection', 'model_name', 'schema_version', 'next_run_at',
            'worker_heartbeat_at', 'worker_instance_id', 'worker_online',
            'last_success_at', 'updated_at',
        ]

    def validate_interval_seconds(self, value):
        if value < 30 or value > 86400:
            raise serializers.ValidationError('同步间隔必须在 30 秒到 24 小时之间。')
        return value

    def validate_batch_size(self, value):
        if value < 1 or value > 500:
            raise serializers.ValidationError('批大小必须在 1 到 500 之间。')
        return value


class SearchIndexRunSerializer(serializers.ModelSerializer):
    duration_seconds = serializers.SerializerMethodField()

    class Meta:
        model = SearchIndexRun
        fields = [
            'id', 'trigger', 'mode', 'status', 'crawl_batch', 'collection_name',
            'model_name', 'schema_version', 'news_count', 'vector_count_before',
            'vector_count_after', 'missing_count', 'changed_count',
            'orphaned_count', 'upserted_count', 'deleted_count', 'failed_count',
            'safe_error_code', 'safe_error_message', 'queued_at', 'started_at',
            'heartbeat_at', 'finished_at', 'cancel_requested_at', 'duration_seconds',
        ]

    def get_duration_seconds(self, obj):
        if not obj.started_at:
            return None
        end = obj.finished_at or obj.heartbeat_at
        if not end:
            return None
        return max(0, int((end - obj.started_at).total_seconds()))
