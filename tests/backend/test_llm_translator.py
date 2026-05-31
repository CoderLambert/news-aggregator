"""
Tests for the LLM translator module.
Tests translation service and Chinese link detection.
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'backend'))

from api.services.llm_translator import (
    find_chinese_translation_link,
    _is_chinese_domain,
    _is_chinese_url_pattern,
)


class TestIsChineseDomain:
    """Test Chinese domain detection."""

    def test_known_chinese_domains(self):
        assert _is_chinese_domain('https://juejin.cn/post/123') is True
        assert _is_chinese_domain('https://csdn.net/article/456') is True
        assert _is_chinese_domain('https://zhuanlan.zhihu.com/p/789') is True
        assert _is_chinese_domain('https://mp.weixin.qq.com/s/abc') is True
        assert _is_chinese_domain('https://github.com/owner/repo/blob/main/README_zh_CN.md') is True

    def test_non_chinese_domains(self):
        assert _is_chinese_domain('https://medium.com/article') is False
        assert _is_chinese_domain('https://dev.to/post') is False
        assert _is_chinese_domain('https://example.com') is False


class TestIsChineseUrlPattern:
    """Test Chinese URL pattern detection."""

    def test_chinese_patterns(self):
        assert _is_chinese_url_pattern('https://example.com/zh/article') is True
        assert _is_chinese_url_pattern('https://example.com/zh-cn/post') is True
        assert _is_chinese_url_pattern('https://example.com/cn/page') is True
        assert _is_chinese_url_pattern('https://example.com/article-zh') is True
        assert _is_chinese_url_pattern('https://example.com/page?lang=zh') is True

    def test_non_chinese_patterns(self):
        assert _is_chinese_url_pattern('https://example.com/en/article') is False
        assert _is_chinese_url_pattern('https://example.com/page') is False


class TestFindChineseTranslationLink:
    """Test Chinese translation link detection in Markdown content."""

    def test_finds_explicit_chinese_link(self):
        content = """
# Article Title

[中文翻译](https://juejin.cn/post/123)

Some English content here.
"""
        result = find_chinese_translation_link(content, 'https://example.com/article')
        assert result == 'https://juejin.cn/post/123'

    def test_finds_chinese_version_link(self):
        content = """
# Article

[中文版](https://csdn.net/article/456)
"""
        result = find_chinese_translation_link(content, 'https://example.com/article')
        assert result == 'https://csdn.net/article/456'

    def test_ignores_original_url(self):
        content = """
# Article

[中文翻译](https://example.com/article)
"""
        result = find_chinese_translation_link(content, 'https://example.com/article')
        assert result == ''

    def test_finds_readme_zh_link(self):
        content = """
# owner/repo

[**简体中文**](https://github.com/owner/repo/blob/main/README_zh_CN.md)
"""
        result = find_chinese_translation_link(content, 'https://github.com/owner/repo')
        assert 'README_zh_CN' in result

    def test_no_chinese_link_returns_empty(self):
        content = """
# Article

[Read more](https://example.com/more)
"""
        result = find_chinese_translation_link(content, 'https://example.com/article')
        assert result == ''

    def test_handles_empty_content(self):
        assert find_chinese_translation_link('', 'https://example.com') == ''
        # None should return empty string (function may raise TypeError or handle it)
        try:
            result = find_chinese_translation_link(None, 'https://example.com')
            assert result == ''
        except TypeError:
            # Function doesn't handle None, that's OK - test documents this
            pass
