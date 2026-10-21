"""Owner-only, read-only business + existing T02 probe usage receipts."""
from django.db.models import Count, Sum
from rest_framework.response import Response
from api.ai_connection_views import ConnectionView, error
from api.ai_model_models import AICallAttempt, AIModelProbeAttempt


def _totals(rows):
    return rows.aggregate(
        calls=Count('id'), input_tokens=Sum('input_tokens'), output_tokens=Sum('output_tokens'),
    )


class AIUsageView(ConnectionView):
    allow_history_reads = True

    def get(self, request):
        if set(request.query_params) - {'lang', 'limit'}:
            return error('invalid_query')
        raw_limit = request.query_params.get('limit', '50')
        if len(raw_limit) > 3 or not raw_limit.isdecimal() or not 1 <= int(raw_limit) <= 100:
            return error('invalid_query')
        limit = int(raw_limit)
        calls = AICallAttempt.objects.filter(user_id=request.user.pk)
        # Reuse T02 receipts rather than inventing historical business sends.
        probes = AIModelProbeAttempt.objects.filter(user_id=request.user.pk).exclude(status='not_sent')
        call_totals, probe_totals = _totals(calls), _totals(probes)
        summary = {}
        for key in ('calls', 'input_tokens', 'output_tokens'):
            a, b = call_totals[key], probe_totals[key]
            summary[key] = None if a is None and b is None else (a or 0) + (b or 0)
        summary['input_tokens_unknown_calls'] = calls.filter(input_tokens__isnull=True).count() + probes.filter(input_tokens__isnull=True).count()
        summary['output_tokens_unknown_calls'] = calls.filter(output_tokens__isnull=True).count() + probes.filter(output_tokens__isnull=True).count()
        results = []
        for row in calls.order_by('-created_at', '-id')[:limit]:
            results.append({
                'id': str(row.pk), 'source': 'business', 'task_kind': row.task_kind,
                'model_id': row.model_id, 'provider_id': row.provider_id,
                'status': 'unknown' if row.status == 'started' else row.status,
                'input_tokens': row.input_tokens, 'output_tokens': row.output_tokens,
                'latency_ms': row.latency_ms, 'created_at': row.created_at.isoformat(),
                'route_metadata': row.route_metadata,
            })
        for row in probes.select_related('connection').order_by('-created_at', '-id')[:limit]:
            results.append({
                'id': str(row.pk), 'source': 'probe', 'task_kind': f'model_probe:{row.probe_kind}',
                'model_id': row.model_id, 'provider_id': row.connection.provider_id,
                'status': 'unknown' if row.status == 'started' else row.status,
                'input_tokens': row.input_tokens, 'output_tokens': row.output_tokens,
                'latency_ms': row.latency_ms, 'created_at': row.created_at.isoformat(),
            })
        results.sort(key=lambda row: (row['created_at'], row['source'], row['id']), reverse=True)
        return Response({'summary': summary, 'attempts': results[:limit], 'has_more': summary['calls'] > limit})
