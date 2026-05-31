"""
Tests for the content cleaner module.
Tests that GitHub page noise is properly removed from Jina-fetched content.
"""
import pytest
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'backend'))

from api.services.content_cleaner import (
    is_github_repo,
    clean_github_content,
    clean_content,
)


class TestIsGithubRepo:
    """Test GitHub URL detection."""

    def test_valid_github_repo(self):
        assert is_github_repo('https://github.com/owner/repo') is True
        assert is_github_repo('https://github.com/owner/repo/') is True
        assert is_github_repo('https://github.com/owner/repo/issues/1') is True

    def test_not_github(self):
        assert is_github_repo('https://example.com/page') is False
        assert is_github_repo('https://news.ycombinator.com') is False

    def test_github_non_repo(self):
        assert is_github_repo('https://github.com') is False
        assert is_github_repo('https://github.com/owner') is False


class TestCleanGithubContent:
    """Test GitHub content cleaning."""

    def test_removes_navigation_menu(self):
        content = """# GitHub - owner/repo: A test repo · GitHub

## Navigation Menu

Toggle navigation

Platform
Solutions

# owner/repo

This is the actual README content.

## About

Sidebar content
"""
        cleaned = clean_github_content(content)
        # Navigation Menu is removed by _find_readme_start which looks for content after repo heading
        assert 'actual README content' in cleaned
        assert 'owner/repo' in cleaned

    def test_removes_file_tree(self):
        content = """# owner/repo

## Folders and files

| Name | Last commit message |
| --- | --- |
| src | Updated |
| tests | Added tests |

## Repository files navigation

* README
* LICENSE

## Features

This is the actual README.
"""
        cleaned = clean_github_content(content)
        assert 'Folders and files' not in cleaned
        assert 'Repository files navigation' not in cleaned
        assert 'actual README' in cleaned

    def test_removes_footer(self):
        content = """# owner/repo

## Features

Real content here.

## Footer

© 2026 GitHub, Inc.

Terms
Privacy
"""
        cleaned = clean_github_content(content)
        assert 'Footer' not in cleaned
        assert 'Real content here' in cleaned

    def test_removes_sidebar_sections(self):
        content = """# owner/repo

## Features

Real content here.

## About

Description

## Topics

topic1, topic2

## Stars

100 stars
"""
        cleaned = clean_github_content(content)
        assert 'About' not in cleaned
        assert 'Topics' not in cleaned
        assert 'Stars' not in cleaned
        assert 'Real content here' in cleaned

    def test_handles_empty_content(self):
        assert clean_github_content('') == ''
        assert clean_github_content(None) is None

    def test_preserves_code_blocks(self):
        content = """# owner/repo

## Installation

```bash
npm install package
```

## Usage

```python
import package
package.run()
```
"""
        cleaned = clean_github_content(content)
        assert '```bash' in cleaned
        assert 'npm install package' in cleaned
        assert '```python' in cleaned
        assert 'import package' in cleaned

    def test_removes_skip_to_content(self):
        content = """# GitHub - owner/repo: Test · GitHub

[Skip to content](https://github.com/owner/repo#start-of-content)

## Navigation Menu

# owner/repo

README content.
"""
        cleaned = clean_github_content(content)
        assert 'Skip to content' not in cleaned
        assert 'README content' in cleaned

    def test_removes_sign_in_links(self):
        content = """# owner/repo

[Sign in](https://github.com/login)

README content.
"""
        cleaned = clean_github_content(content)
        assert 'Sign in' not in cleaned
        assert 'README content' in cleaned


class TestCleanContent:
    """Test the clean_content dispatcher."""

    def test_dispatches_to_github_cleaner(self):
        content = "# owner/repo\n\n## About\n\nSidebar"
        cleaned = clean_content(content, 'https://github.com/owner/repo')
        assert 'About' not in cleaned

    def test_passes_through_non_github(self):
        content = "This is regular content."
        cleaned = clean_content(content, 'https://example.com/article')
        assert cleaned == content
