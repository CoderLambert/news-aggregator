from types import SimpleNamespace
import pytest
from api.services import ai_usage


def test_usage_counts_actual_create_once_and_preserves_unknown(monkeypatch):
    receipts = []
    class FakeReceipt:
        def __init__(self, *args):
            receipts.append(self)
            self.status = 'started'
        def finish(self, status, usage=None):
            if self.status == 'started':
                self.status, self.usage = status, usage
    monkeypatch.setattr(ai_usage, '_Receipt', FakeReceipt)
    selection = SimpleNamespace(user_id=1, task_kind='article_qa', connection=SimpleNamespace(user_id=1))
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop')], usage=None)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    result = ai_usage.complete_with_usage(client, selection, 'article_qa', model='synthetic')
    assert len(calls) == len(receipts) == 1
    assert receipts[0].status == 'succeeded' and receipts[0].usage is None
    assert result.usage is None
    assert ai_usage._tokens(None) is None and ai_usage._tokens(True) is None
    assert ai_usage._tokens(0) == 0
    with pytest.raises(ValueError):
        ai_usage.complete_with_usage(client, selection, 'deep_research', model='synthetic')
    assert len(calls) == 1


def test_usage_stream_disconnect_does_not_invent_completion():
    finished = []
    class Receipt:
        def finish(self, status, usage=None):
            finished.append((status, usage))
    class Stream:
        def __iter__(self):
            yield SimpleNamespace(choices=[SimpleNamespace(finish_reason=None)], usage=None)
        def close(self):
            pass
    observed = ai_usage._ObservedStream(Stream(), Receipt())
    list(observed)
    assert finished == [('unknown', None)]
