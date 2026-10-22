"""Redis replay regressions; no model requests or live user databases."""
from types import SimpleNamespace
from unittest.mock import patch

from api import ai_translation_views as views


def test_terminal_replay_does_not_poll_database_after_authorization():
    task = SimpleNamespace(user_id=1, pk='synthetic-task', generation=1)
    initial = dict(task_id='synthetic-task', news_id=7, generation=1,
                   status='succeeded', progress='译文', result={'content': '译文'})
    request = SimpleNamespace(user=object(), headers={}, query_params={})
    with patch.object(views.translation, 'get_task', side_effect=[task, AssertionError('DB polling')]) as get, \
            patch.object(views.translation, 'payload', return_value=initial):
        response = views.PrivateTranslationEventsView().get(request, task.pk)
        frames = b''.join(response.streaming_content)
    assert b'event: terminal' in frames
    assert get.call_count == 1

import os
import json
import subprocess
import sys
import uuid

import pytest
from api.services import translation_channel as transport


@pytest.fixture
def channel():
    # Explicit synthetic Redis only; never default to the application's URL.
    from api.tests.translation_transport_fixture import synthetic_redis_client
    redis = synthetic_redis_client()
    if redis is None:
        pytest.skip('requires an explicitly isolated synthetic Redis endpoint')
    with patch.object(transport, 'client', return_value=redis):
        item = transport.Channel(1, uuid.uuid4(), 1)
        yield item
        item.redis.delete(*item.keys)


@pytest.mark.django_db
def test_running_replay_has_no_database_queries_and_no_false_eof_success(channel):
    token='synthetic-run'
    channel.mutate('init', token)
    channel.mutate('delta', token, delta='第一段')
    task = SimpleNamespace(user_id=1, pk=channel.keys[0].split(':')[3], generation=1)
    initial=dict(task_id='synthetic-task', news_id=7, generation=1, status='running', progress='', result=None)
    request=SimpleNamespace(user=object(), headers={'Accept':'text/event-stream'}, query_params={})
    with patch.object(views.translation, 'get_task', side_effect=[task, AssertionError('DB polling')]) as get, \
            patch.object(views.translation, 'payload', return_value=initial), \
            patch.object(transport, 'Channel', return_value=channel):
        response=views.PrivateTranslationEventsView().get(request, task.pk)
        events=iter(response.streaming_content)
        assert b'event: snapshot' in next(events)
        channel.mutate('delta', token, delta='第二段')
        assert b'keepalive' in next(events)
        assert b'event: delta' in next(events)
        response.close()
    assert get.call_count == 1


def test_independent_process_publishes_and_two_observers_receive_same_delta(channel):
    channel.mutate('init', 'synthetic-run')
    cursor=channel.read()['cursor']
    code="""import os,django;django.setup()
from api.services import translation_channel as transport
from api.tests.translation_transport_fixture import synthetic_redis_client
transport.client=lambda: synthetic_redis_client()
c=transport.Channel(1,os.environ['SYNTHETIC_TASK'],1)
c.mutate('delta','synthetic-run',delta='跨进程片段')
"""
    task_id=channel.keys[0].split('{')[1].split('}')[0].split(':')[1]
    env={**os.environ,'SYNTHETIC_TASK':task_id,'TRANSLATION_REDIS_URL':os.environ.get('TEST_TRANSLATION_REDIS_URL', '')}
    result=subprocess.run([sys.executable,'-c',code],env=env,capture_output=True,timeout=15)
    assert result.returncode == 0, result.stderr[-500:]
    first=channel.read(cursor); second=channel.read(cursor)
    assert first==second
    fields=first['events'][0][1]
    body=json.loads(dict(zip(fields[::2],fields[1::2]))['body'])
    assert body['delta']=='跨进程片段'


def test_cancel_rejects_late_worker_and_clears_partial_preview(channel):
    channel.mutate('init','current')
    channel.mutate('delta','current',delta='partial')
    with pytest.raises(transport.ChannelUnavailable):
        channel.mutate('delta','foreign',delta='private')
    channel.mutate('cancel',status='cancelled',result=None,error_code='translation_cancelled')
    with pytest.raises(transport.ChannelUnavailable):
        channel.mutate('delta','current',delta='late')
    state=channel.read()
    assert state['status']=='cancelled' and state['text']==''


def test_stale_control_and_trimmed_cursor_fail_closed_or_recover_snapshot(channel):
    channel.mutate('init','current')
    channel.mutate('delta','current',delta='retained')
    state=channel.read()
    assert channel.read('1-0')['snapshot'] is True
    channel.redis.hset(channel.keys[0],'checked',0)
    with pytest.raises(transport.ChannelUnavailable):
        channel.mutate('delta','current',delta='late')
    with pytest.raises(transport.ChannelUnavailable):
        channel.read(state['cursor'])


def test_foreign_owner_and_generation_cannot_replay_same_task(channel):
    channel.mutate('init','current')
    channel.mutate('delta','current',delta='owner-only')
    task_id=channel.keys[0].split('{')[1].split('}')[0].split(':')[1]
    for owner,generation in ((2,1),(1,2)):
        foreign=transport.Channel(owner,task_id,generation)
        with pytest.raises(transport.ChannelUnavailable):
            foreign.read()


def test_buffered_publisher_stops_and_aborts_when_control_authorization_fails(channel):
    from threading import Event
    aborted=Event()
    def deny():
        raise RuntimeError('synthetic authority revoked')
    publisher=transport.BufferedPublisher(channel,'current',deny,aborted.set)
    with pytest.raises(transport.ChannelUnavailable):
        with publisher:
            publisher.append('preview')
            assert aborted.wait(2)
            publisher.append('late')
    assert publisher.failed.is_set()


def test_redis_loss_never_creates_a_success_event(channel):
    channel.mutate('init','current')
    with patch.object(channel.redis,'eval',side_effect=OSError('synthetic disconnect')):
        with pytest.raises(transport.ChannelUnavailable):
            channel.mutate('delta','current',delta='partial')
    assert channel.read()['status']=='running'


def test_translation_link_signature_allows_reordered_links_but_preserves_targets_and_counts():
    from api.services.ai_private_translation import _markdown_signature
    source='Read [first](https://example.test/one) and [second](https://example.test/two).'
    translated='先看[第二项](https://example.test/two)，再看[第一项](https://example.test/one)。'
    assert _markdown_signature(source) == _markdown_signature(translated)
    for malformed in (
        '[第一项](https://example.test/one)',
        '[第一项](https://example.test/one) [重复](https://example.test/one)',
        '[第一项](https://example.test/one) [篡改](https://other.test/two)',
    ):
        assert _markdown_signature(source) != _markdown_signature(malformed)
