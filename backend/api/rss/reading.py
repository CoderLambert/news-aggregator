"""Personal read state. Reading analytics and engine flags are independent."""
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from api.rss.http import RssAPIView, RssConflict
from api.rss.reading_models import NewsReadState


def _article(user, news_id):
    from api.rss.access import authorized_news
    return get_object_or_404(authorized_news(user), pk=news_id)


def read_state(user, news_id):
    _article(user, news_id)
    state = NewsReadState.objects.filter(user=user, news_id=news_id).first()
    return {'is_read': state.is_read, 'version': state.version} if state else {'is_read': False, 'version': 0}


@transaction.atomic
def set_read_state(user, news_id, *, is_read, expected_version=None):
    if type(is_read) is not bool or (expected_version is not None and (
            type(expected_version) is not int or not 0 <= expected_version < 2**63 - 1)):
        raise ValidationError('is_read 须为布尔值，expected_version 须为非负整数。')
    # SQLite write reservation precedes all ACL/version reads. Two tabs cannot
    # both accept the same expected version, including an absent state (v0).
    get_user_model().objects.filter(pk=user.pk).update(last_login=F('last_login'))
    _article(user, news_id)
    state = NewsReadState.objects.filter(user=user, news_id=news_id).first()
    version = state.version if state else 0
    if expected_version is not None and version != expected_version:
        raise RssConflict()
    if state is None:
        state = NewsReadState.objects.create(user=user, news_id=news_id, is_read=is_read)
    elif state.is_read != is_read:
        state.is_read = is_read
        state.version += 1
        state.save(update_fields=['is_read', 'version', 'updated_at'])
    return {'is_read': state.is_read, 'version': state.version}


class NewsReadStateView(RssAPIView):
    def get(self, request, pk):
        return Response(read_state(request.user, pk))

    def patch(self, request, pk):
        if not isinstance(request.data, dict) or set(request.data) - {'is_read', 'expected_version'}:
            raise ValidationError('请求字段无效。')
        return Response(set_read_state(request.user, pk, is_read=request.data.get('is_read'),
                                       expected_version=request.data.get('expected_version')))
