"""One physical request counter and cancellation fence for a whole provider chain."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import time


class ExecutionStopped(Exception):
    def __init__(self, code='superseded'):
        super().__init__(code)
        self.error_code = code
        self.retryable = False
        self.http_status = None
        self.retry_after_at = None
        self.scope_keys = ()


@dataclass
class FetchExecution:
    guard: object = None
    logical_url: str | None = None
    deadline: float = field(default_factory=lambda: time.monotonic() + 60)
    requests_remaining: int = 5
    physical_requests: int = 0

    def check(self):
        if self.guard:
            self.guard()
        if time.monotonic() >= self.deadline:
            raise ExecutionStopped('request_limit')

    def before_send(self):
        self.check()
        self.charge_request()

    def charge_request(self):
        if time.monotonic() >= self.deadline:
            raise ExecutionStopped('request_limit')
        if self.requests_remaining <= 0:
            raise ExecutionStopped('request_limit')
        self.requests_remaining -= 1
        self.physical_requests += 1

    def remaining_seconds(self):
        self.check()
        return max(0.001, self.deadline - time.monotonic())


current_execution = ContextVar('news_fetch_execution', default=None)


@contextmanager
def execution_scope(guard=None):
    existing = current_execution.get()
    if existing is not None:
        existing.check()
        yield existing
        return
    execution = FetchExecution(guard=guard)
    token = current_execution.set(execution)
    try:
        yield execution
    finally:
        current_execution.reset(token)
