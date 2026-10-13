from unittest.mock import patch
from urllib.error import HTTPError
import urllib.request

import pytest
from django.utils import timezone

from api.services.research import tools
from api.services.article_fetcher.types import FetchResult
from api.services.request_budget import BudgetDeferred


def test_search_http_delegates_to_shared_pinned_budgeted_transport():
    request = urllib.request.Request('https://s.jina.ai/synthetic', headers={'Accept': 'application/json'})
    with patch('api.services.article_fetcher.providers.safe_urlopen', return_value=object()) as opened:
        tools._open_search_http(request, timeout=8)
    opened.assert_called_once_with(request, timeout=8)


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


def test_source_translation_link_uses_reviewed_reader_instead_of_raw_http():
    from api.services.llm_translator import fetch_and_verify_chinese_content
    body = '# 完整中文文章\n\n' + '这是本地测试的完整中文文章内容。' * 20
    with patch('api.services.article_fetcher.providers.TrustedNewsJinaProvider.fetch', return_value=FetchResult(True, 'trusted_news_jina', markdown=body)) as fetch, \
         patch('urllib.request.urlopen') as unsafe:
        assert fetch_and_verify_chinese_content('https://www.leiphone.com/category/ai/synthetic.html') == body
    fetch.assert_called_once()
    unsafe.assert_not_called()


def test_source_translation_link_does_not_continue_fetching_after_reader_control_failure():
    from api.services.llm_translator import fetch_and_verify_chinese_content
    with patch('api.services.article_fetcher.providers.TrustedNewsJinaProvider.fetch', return_value=FetchResult(False, 'trusted_news_jina', error_code='rate_limited')) as fetch:
        assert fetch_and_verify_chinese_content('https://www.leiphone.com/category/ai/synthetic.html') == ''
    fetch.assert_called_once()
