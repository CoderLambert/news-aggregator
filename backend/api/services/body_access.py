"""Grantable reader access, independent of publisher contracts and site switches."""
from contextlib import contextmanager
from contextvars import ContextVar

PERMISSION = 'api.view_article_body'
privileged_fetch = ContextVar('privileged_article_fetch', default=False)

def can_view_article_body(user):
    return bool(user and user.is_authenticated and user.is_active and user.has_perm(PERMISSION))

def authorized_fetch(news):
    return can_view_article_body(getattr(news, 'full_content_requested_by', None))

@contextmanager
def body_fetch_scope(news):
    token = privileged_fetch.set(authorized_fetch(news))
    try:
        yield
    finally:
        privileged_fetch.reset(token)
