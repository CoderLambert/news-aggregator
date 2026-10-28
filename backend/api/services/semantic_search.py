"""Single effective semantic-search switch; no database or model initialization."""
from django.conf import settings


class SemanticSearchDisabled(RuntimeError):
    def __init__(self):
        super().__init__('semantic_search_disabled')


def semantic_search_enabled():
    return (
        getattr(settings, 'SEMANTIC_SEARCH_ENABLED', False) is True
        and settings.PUBLIC_SITE_MODE == 'full'
        and settings.PUBLIC_AI_ENABLED
    )


def require_semantic_search():
    if not semantic_search_enabled():
        raise SemanticSearchDisabled()
