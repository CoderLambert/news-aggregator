from unittest.mock import patch
from urllib.error import HTTPError
import urllib.request

import pytest
from django.utils import timezone

from api.services.research import tools
from api.services.request_budget import BudgetDeferred


def test_search_http_delegates_to_shared_pinned_budgeted_transport():
    request = urllib.request.Request('https://s.jina.ai/synthetic', headers={'Accept': 'application/json'})
    response = object()
    with patch('api.services.safe_http.safe_urlopen', return_value=response) as opened:
        actual = tools._open_search_http(request, timeout=8)
    opened.assert_called_once_with(request, timeout=8)
    assert actual is response


@pytest.mark.parametrize('error', [HTTPError('https://s.jina.ai/synthetic', 429, 'controlled', {}, None),
                                  BudgetDeferred(timezone.now())])
def test_search_limit_and_cooldown_do_not_start_wikipedia_or_ddg_fallback(error):
    with patch.object(tools, '_open_search_http', side_effect=error) as opened, \
         patch.object(tools, '_wikipedia_search') as wikipedia, patch.object(tools, '_duckduckgo_search') as ddg:
        with pytest.raises(type(error)):
            tools._tool_search_web('synthetic local query')
    opened.assert_called_once()
    wikipedia.assert_not_called()
    ddg.assert_not_called()


def test_source_translation_link_helpers_removed():
    from api.services import llm_translator
    assert not hasattr(llm_translator, 'find_chinese_translation_link')
    assert not hasattr(llm_translator, 'fetch_and_verify_chinese_content')
