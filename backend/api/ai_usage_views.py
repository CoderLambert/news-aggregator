"""Owner-only, read-only business + existing T02 probe usage receipts."""
from django.db.models import CharField, Count, Sum, Value
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
        if set(request.query_params) - {'lang', 'limit', 'page'}:
            return error('invalid_query')
        raw_limit = request.query_params.get('limit', '50')
        if len(raw_limit) > 3 or not raw_limit.isdecimal() or not 1 <= int(raw_limit) <= 100:
            return error('invalid_query')
        raw_page = request.query_params.get('page', '1')
        if len(raw_page) > 6 or not raw_page.isdecimal() or not 1 <= int(raw_page) <= 100000:
            return error('invalid_query')
        limit, page = int(raw_limit), int(raw_page)
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
        # Page the merged identities in SQL, then read at most one page of
        # owner-scoped receipts. Never fetch every historical receipt to slice it.
        identities = calls.order_by().annotate(source=Value('business', output_field=CharField())).values('id', 'created_at', 'source')
        probe_identities = probes.order_by().annotate(source=Value('probe', output_field=CharField())).values('id', 'created_at', 'source')
        offset = (page - 1) * limit
        selected = list(identities.union(probe_identities, all=True)
                        .order_by('-created_at', '-source', '-id')[offset:offset + limit])
        call_ids = [row['id'] for row in selected if row['source'] == 'business']
        probe_ids = [row['id'] for row in selected if row['source'] == 'probe']
        results = []
        for row in calls.filter(pk__in=call_ids):
            results.append({
                'id': str(row.pk), 'source': 'business', 'task_kind': row.task_kind,
                'model_id': row.model_id, 'provider_id': row.provider_id,
                'status': 'unknown' if row.status == 'started' else row.status,
                'input_tokens': row.input_tokens, 'output_tokens': row.output_tokens,
                'latency_ms': row.latency_ms, 'created_at': row.created_at.isoformat(),
                'route_metadata': row.route_metadata,
            })
        for row in probes.filter(pk__in=probe_ids).select_related('connection'):
            results.append({
                'id': str(row.pk), 'source': 'probe', 'task_kind': f'model_probe:{row.probe_kind}',
                'model_id': row.model_id, 'provider_id': row.connection.provider_id,
                'status': 'unknown' if row.status == 'started' else row.status,
                'input_tokens': row.input_tokens, 'output_tokens': row.output_tokens,
                'latency_ms': row.latency_ms, 'created_at': row.created_at.isoformat(),
            })
        results.sort(key=lambda row: (row['created_at'], row['source'], row['id']), reverse=True)
        return Response({'summary': summary, 'attempts': results[:limit], 'has_more': summary['calls'] > offset + limit,
                         'page': page, 'page_size': limit, 'count': summary['calls'],
                         'page_count': max(1, (summary['calls'] + limit - 1) // limit)})
