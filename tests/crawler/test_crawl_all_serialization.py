import json
from types import SimpleNamespace

import pytest
from django.core.management.base import CommandError

from api.management.commands import crawl


def _output(outcome, **extra):
    value = {'outcome': outcome, **extra}
    return 'NEWSHUB_CRAWL_RESULT ' + json.dumps(value) + '\n'


def test_crawl_all_runs_each_source_serially_and_retries_deferred(monkeypatch):
    monkeypatch.setattr(crawl, 'runtime_registry', lambda: {
        key: SimpleNamespace(maintenance='code') for key in ('first', 'second')
    })
    calls = []
    responses = iter([
        SimpleNamespace(returncode=0, stdout=_output('deferred')),
        SimpleNamespace(returncode=0, stdout=_output('updated')),
        SimpleNamespace(returncode=0, stdout=_output('unchanged')),
    ])

    def run(command, **kwargs):
        calls.append(command[-1])
        return next(responses)

    monkeypatch.setattr(crawl.subprocess, 'run', run)
    monkeypatch.setattr(crawl.time, 'sleep', lambda _seconds: None)

    crawl.Command()._crawl_all_serially()

    assert calls == ['first', 'first', 'second']


def test_crawl_all_fails_closed_when_a_source_has_no_success_terminal_state(monkeypatch):
    monkeypatch.setattr(crawl, 'runtime_registry', lambda: {
        'broken': SimpleNamespace(maintenance='code')
    })
    monkeypatch.setattr(crawl.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout=_output('blocked'),
    ))

    with pytest.raises(CommandError, match='broken:blocked:0'):
        crawl.Command()._crawl_all_serially()
