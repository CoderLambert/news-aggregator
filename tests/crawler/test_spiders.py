"""
Tests for the crawler spiders.
Tests that spiders correctly parse pages and yield NewsItems.
"""
import pytest
from datetime import datetime


class TestGithubSpider:
    """Test GitHub Trending spider parsing."""

    def test_spider_name(self):
        """Spider should have correct name."""
        from news_crawler.spiders.github_spider import GithubTrendingSpider
        assert GithubTrendingSpider.name == 'github'

    def test_spider_allowed_domains(self):
        """Spider should only allow github.com."""
        from news_crawler.spiders.github_spider import GithubTrendingSpider
        assert 'github.com' in GithubTrendingSpider.allowed_domains

    def test_spider_start_urls(self):
        """Spider should start from trending pages."""
        from news_crawler.spiders.github_spider import GithubTrendingSpider
        urls = GithubTrendingSpider.start_urls
        assert 'https://github.com/trending' in urls
        assert 'https://github.com/trending?since=weekly' in urls


class TestSpiderItemStructure:
    """Test that spider items have correct structure."""

    def test_news_item_fields(self):
        """NewsItem should have all required fields."""
        from news_crawler.items import NewsItem
        item = NewsItem()
        
        required_fields = [
            'title', 'content', 'author', 'publish_time',
            'source_name', 'category_name', 'url', 'cover_image',
        ]
        for field in required_fields:
            assert field in item.fields, f"Missing field: {field}"
