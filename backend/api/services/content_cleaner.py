"""Content cleaning utilities for fetched articles.

Strips navigation menus, sidebars, footers, and other page chrome from
Jina Reader output, especially for GitHub repo pages.
"""

import re
from urllib.parse import urlparse


def is_github_repo(url: str) -> bool:
    """Check if URL points to a GitHub repository page (not raw, not gist, not settings)."""
    try:
        parsed = urlparse(url)
        if parsed.netloc not in ('github.com', 'www.github.com'):
            return False
        path = parsed.path.strip('/')
        parts = path.split('/')
        return len(parts) >= 2 and bool(parts[0]) and bool(parts[1])
    except Exception:
        return False


def clean_github_content(markdown: str) -> str:
    """Clean Jina-fetched GitHub repo page content.
    
    Jina Reader captures the ENTIRE GitHub page DOM converted to markdown,
    including navigation menus, search bars, file trees, sidebar widgets,
    footer links, etc. This function extracts only the actual README content.
    
    Structure of Jina GitHub output:
    1. "GitHub - owner/repo: ..." page title
    2. ## Navigation Menu (GitHub header: Platform, Solutions, etc.)
    3. Search bar, Provide feedback, Saved searches
    4. # owner/repo (repo heading)
    5. Branch/Tags info, "Go to file", "Code"
    6. ## Folders and files (file tree TABLE)
    7. ## Repository files navigation
    8. [README] [LICENSE] links + optional README_zh_CN link
    9. ## Actual README heading (repo name or first section)
    10. ... README content ...
    11. ## About / Topics / Resources / License / Stars / ...
    12. ## Releases / Packages / Contributors / Languages
    13. ## Footer
    
    We want only section 9-10 (the README).
    """
    if not markdown:
        return markdown
    
    # Step 1: Remove the initial page title "GitHub - owner/repo: ..."
    markdown = re.sub(
        r'^#\s+GitHub\s*-\s*[\w\-\.]+/[\w\-\.]+\s*:.*?·\s*GitHub\s*\n*',
        '',
        markdown,
        count=1,
    )
    
    # Step 2: Find and remove everything before the README content
    # The README content starts after "Repository files navigation" and optional
    # README/LICENSE links, with the first real heading of the repo
    readme_start = _find_readme_start(markdown)
    if readme_start >= 0:
        markdown = markdown[readme_start:]
    
    # Step 3: Remove sidebar sections that appear AFTER the README
    sidebar_start = _find_sidebar_start(markdown)
    if sidebar_start >= 0:
        markdown = markdown[:sidebar_start].rstrip()
    
    # Step 4: Clean remaining artifacts
    markdown = _clean_artifacts(markdown)
    
    return markdown.strip()


def _find_readme_start(markdown: str) -> int:
    """Find where the actual README content begins.
    
    Strategy: After the file tree and "Repository files navigation",
    look for the first heading that is the actual README title.
    This is typically the repo name (e.g., "## FlClash") or a project title.
    """
    # First, find "## Repository files navigation"
    nav_idx = markdown.find('## Repository files navigation')
    if nav_idx < 0:
        # Fallback: find after "## Folders and files"
        nav_idx = markdown.find('## Folders and files')
        if nav_idx < 0:
            return 0  # Can't find structure, return as-is
    
    # Look for content after the navigation section
    after_nav = markdown[nav_idx:]
    
    # Skip past the navigation links (README, GPL-3.0 license, etc.)
    # These appear as bullet list items or markdown links
    # The actual README heading comes after these
    
    # Find the first heading after nav that's NOT a nav/sidebar heading
    nav_skip_headings = {
        'repository files navigation',
        'folders and files',
    }
    
    # Also skip link-only lines like [README](...) [GPL-3.0 license](...)
    # The real heading comes after these
    
    heading_re = re.compile(r'^(#{1,3})\s+(.+)$', re.MULTILINE)
    for m in heading_re.finditer(after_nav):
        heading_text = m.group(2).strip()
        heading_lower = heading_text.lower()
        
        # Skip nav-related headings
        if heading_lower in nav_skip_headings:
            continue
        
        # Skip headings that are clearly nav elements
        skip_patterns = [
            'navigation', 'folders and files', 'about', 'topics',
            'resources', 'license', 'stars', 'watchers', 'forks',
            'releases', 'packages', 'contributors', 'languages',
            'footer', 'uh oh!',
        ]
        if any(p in heading_lower for p in skip_patterns):
            continue
        
        # Skip headings that are just links like "[Releases 103](...)"
        if heading_text.startswith('['):
            continue
        
        # This looks like a real README heading
        return nav_idx + m.start()
    
    return 0


def _find_sidebar_start(markdown: str) -> int:
    """Find where the GitHub sidebar content begins (after the README).
    
    The README ends and sidebar widgets begin with sections like:
    - ## About (followed by Topics, Resources, License)
    - ## Stars / ## Watchers / ## Forks
    - ## Releases / ## Packages / ## Contributors
    - ## Languages
    - ## Footer
    """
    sidebar_patterns = [
        r'^## About\s*$',
        r'^## Topics\s*$',
        r'^## Resources\s*$',
        r'^## License\s*$',
        r'^## Uh oh!\s*$',
        r'^## Stars\s*$',
        r'^## Watchers\s*$',
        r'^## Forks\s*$',
        r'^## \[Releases',
        r'^## \[Packages',
        r'^## \[Contributors',
        r'^## Languages\s*$',
        r'^## Footer\s*$',
        r'^### Footer navigation\s*$',
    ]
    
    earliest = len(markdown)
    for pattern in sidebar_patterns:
        m = re.search(pattern, markdown, re.MULTILINE)
        if m and m.start() < earliest:
            earliest = m.start()
    
    return earliest if earliest < len(markdown) else -1


def _clean_artifacts(markdown: str) -> str:
    """Remove remaining page chrome artifacts."""
    # Remove "Skip to content" links
    markdown = re.sub(r'\[Skip to content\]\(.*?\)\s*\n?', '', markdown)
    
    # Remove "Toggle navigation" lines
    markdown = re.sub(r'^Toggle navigation\s*\n', '', markdown, flags=re.MULTILINE)
    
    # Remove "Sign in" links
    markdown = re.sub(r'\[Sign in\]\(.*?\)\s*\n?', '', markdown)
    
    # Remove empty image-only links: [![Image ...](...)](...)
    markdown = re.sub(
        r'\[\!\[Image \d+: ([^\]]*)\]\([^)]+\)\]\([^)]+\)',
        r'![\1]',
        markdown,
    )
    
    # Remove empty links: [](url)
    markdown = re.sub(r'\n\[\]\([^)]+\)\s*\n', '\n', markdown)
    
    # Remove search-related sections
    markdown = re.sub(
        r'# Search code, repositories.*?\n(?=##|#)',
        '',
        markdown,
        flags=re.DOTALL,
    )
    
    # Remove "Provide feedback" section
    markdown = re.sub(
        r'# Provide feedback\n.*?\n(?=##|#)',
        '',
        markdown,
        flags=re.DOTALL,
    )
    
    # Remove "Saved searches" section
    markdown = re.sub(
        r'# Saved searches\n.*?\n(?=##|#)',
        '',
        markdown,
        flags=re.DOTALL,
    )
    
    # Remove "Appearance settings"
    markdown = re.sub(r'^Appearance settings\s*\n', '', markdown, flags=re.MULTILINE)
    
    # Remove "Go to file", "Code", "Open more actions menu" standalone lines
    for kw in ['Go to file', 'Code\n', 'Open more actions menu']:
        markdown = markdown.replace(kw + '\n', '')
    
    # Remove branch/tag count lines like "main", "**4**Branches", "**195**Tags"
    # These appear right after the repo heading
    markdown = re.sub(
        r'\n\*\*\d+\*\*\s*(Branches|Tags)\[',
        '\n',
        markdown,
    )
    
    # Clean up excessive blank lines (more than 2 consecutive)
    markdown = re.sub(r'\n{4,}', '\n\n\n', markdown)
    
    return markdown


def clean_content(markdown: str, url: str) -> str:
    """Clean fetched content based on source URL.
    
    Dispatches to source-specific cleaners.
    """
    if is_github_repo(url):
        return clean_github_content(markdown)
    # Future: add cleaners for other sources (ProductHunt, Dev.to, etc.)
    return markdown
