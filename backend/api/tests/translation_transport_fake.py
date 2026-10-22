"""In-memory transport double for durable worker tests (no external Redis).

Lua, independent-process replay and freshness are checked separately against
an explicitly provisioned disposable Redis in test_translation_redis_transport.
"""
from copy import deepcopy
from threading import Lock


def channel_factory(transport):
    states = {}
    lock = Lock()

    class Channel:
        def __init__(self, owner, task, generation):
            self.key = (owner, str(task), generation)

        def mutate(self, op, token='', **body):
            with lock:
                state = states.get(self.key)
                if op == 'init':
                    if state is not None:
                        raise transport.ChannelUnavailable()
                    state = dict(status='running', text='', cursor='1-0', token=str(token), result='null', error_code='')
                    states[self.key] = state
                elif op == 'cancel':
                    if state is None:
                        state = {}; states[self.key] = state
                    state.update(status='cancelled', text='', cursor='2-0', result='null', error_code=body['error_code'])
                elif state is None or state['status'] != 'running' or state['token'] != str(token):
                    raise transport.ChannelUnavailable()
                elif op == 'delta':
                    state['text'] += body['delta']
                elif op == 'terminal':
                    import json
                    state.update(status=body['status'], text='', result=json.dumps(body['result']), error_code=body['error_code'])
                return '1-0'

        def read(self, cursor=''):
            with lock:
                if self.key not in states:
                    raise transport.ChannelUnavailable()
                return dict(snapshot=True, **deepcopy(states[self.key]))

    return Channel
