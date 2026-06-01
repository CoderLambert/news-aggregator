"""Real article full-content fetching orchestration.

This package is the single entry point for turning a news URL into verified
Markdown. It may try multiple real fetch providers, but it must never generate
or persist summaries as `News.full_content`.
"""

from .core import FetchError, FetchResult, fetch_article_markdown

__all__ = ['FetchError', 'FetchResult', 'fetch_article_markdown']
