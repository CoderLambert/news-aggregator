"""Content cleaning utilities for fetched articles.

Strips navigation menus, sidebars, footers, and other page chrome from
Jina Reader output, especially for GitHub repo pages.
Also converts inline HTML commonly found in GitHub READMEs to Markdown.
"""

import re
from urllib.parse import urlparse, urljoin


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


def clean_github_content(markdown: str, url: str = '') -> str:
    """Clean Jina-fetched GitHub repo page content.

    Jina Reader captures the ENTIRE GitHub page DOM converted to markdown,
    including navigation menus, search bars, file trees, sidebar widgets,
    footer links, etc. This function extracts only the actual README content.

    Also converts inline HTML (common in GitHub READMEs for layout/badges)
    to Markdown equivalents so they render properly.

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
    readme_start = _find_readme_start(markdown)
    if readme_start >= 0:
        markdown = markdown[readme_start:]

    # Step 3: Remove sidebar sections that appear AFTER the README
    sidebar_start = _find_sidebar_start(markdown)
    if sidebar_start >= 0:
        markdown = markdown[:sidebar_start].rstrip()

    # Step 4: Convert inline HTML to Markdown (common in READMEs)
    markdown = _convert_readme_html(markdown, base_url=url)

    # Step 5: Clean remaining artifacts
    markdown = _clean_artifacts(markdown)

    return markdown.strip()


# ── Inline HTML → Markdown converter for GitHub READMEs ──────────────────

def _convert_readme_html(markdown: str, base_url: str = '') -> str:
    """Convert inline HTML commonly found in GitHub READMEs to Markdown.

    GitHub READMEs often use HTML for layout features not supported by
    standard Markdown (centering, badges, responsive images, etc.).
    Our Markdown renderer doesn't handle raw HTML, so we convert.
    """
    if not markdown or '<' not in markdown:
        return markdown

    # 1. Convert <img> tags to Markdown ![alt](src)
    def _img_to_md(m):
        attrs = m.group(1)
        src_m = re.search(r'''src\s*=\s*["']([^"']*)["']''', attrs)
        alt_m = re.search(r'''alt\s*=\s*["']([^"']*)["']''', attrs)
        src = src_m.group(1) if src_m else ''
        alt = alt_m.group(1) if alt_m else ''
        if not src:
            return ''
        # Resolve relative URLs against the repo base
        if base_url and not src.startswith(('http://', 'https://', '/')):
            try:
                src = urljoin(base_url.rstrip('/') + '/', src)
            except Exception:
                pass
        return f'![{alt}]({src})'

    markdown = re.sub(r'<img\b([^>]*)/?>', _img_to_md, markdown, flags=re.IGNORECASE)

    # 2. Convert <br> and <br/> to Markdown line break
    markdown = re.sub(r'<br\s*/?\s*>', '  \n', markdown, flags=re.IGNORECASE)

    # 3. Convert block-level HTML headings with attributes to Markdown
    markdown = re.sub(
        r'<h([1-6])\b[^>]*>(.*?)</h\1\s*>',
        lambda m: '#' * int(m.group(1)) + ' ' + m.group(2).strip() + '\n',
        markdown,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # 4. Convert inline bold/strong
    markdown = re.sub(r'<b\s*>(.*?)</b\s*>', r'**\1**', markdown, flags=re.IGNORECASE | re.DOTALL)
    markdown = re.sub(r'<strong\s*>(.*?)</strong\s*>', r'**\1**', markdown, flags=re.IGNORECASE | re.DOTALL)

    # 5. Convert inline italic/em
    markdown = re.sub(r'<i\s*>(.*?)</i\s*>', r'*\1*', markdown, flags=re.IGNORECASE | re.DOTALL)
    markdown = re.sub(r'<em\s*>(.*?)</em\s*>', r'*\1*', markdown, flags=re.IGNORECASE | re.DOTALL)

    # 6. Convert <a href="...">text</a> → [text](href)
    def _link_to_md(m):
        href = m.group(2)
        text = m.group(3).strip()
        return f'[{text}]({href})'

    markdown = re.sub(
        r'<a\b[^>]*href=(["\'])(.*?)\1[^>]*>(.*?)</a\s*>',
        _link_to_md,
        markdown,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # 7. Strip block-level layout tags: <div>, </div>, <p>, </p>, <center>, </center>, <span>, </span>
    markdown = re.sub(r'</?(?:div|p|center|span|section|article|tbody|thead|tr)\b[^>]*>\s*\n?', '\n', markdown, flags=re.IGNORECASE)

    # 8. Strip any remaining stray HTML tags outside code blocks
    lines = markdown.split('\n')
    in_code = False
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('```'):
            in_code = not in_code
            cleaned.append(line)
            continue
        if not in_code:
            line = re.sub(r'<[^>]+>', '', line)
        cleaned.append(line)
    markdown = '\n'.join(cleaned)

    # 9. Clean up excessive blank lines
    markdown = re.sub(r'\n{4,}', '\n\n\n', markdown)

    return markdown


def _find_readme_start(markdown: str) -> int:
    """Find where the actual README content begins.

    Strategy: After the file tree and "Repository files navigation",
    look for the first heading that is the actual README title.
    This is typically the repo name (e.g., "## FlClash") or a project title.
    Also handles RST-style headings (text underlined with === or ---).
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

    nav_skip_headings = {
        'repository files navigation',
        'folders and files',
    }

    skip_patterns = [
        'navigation', 'folders and files', 'about', 'topics',
        'resources', 'license', 'stars', 'watchers', 'forks',
        'releases', 'packages', 'contributors', 'languages',
        'footer', 'uh oh!', 'latest commit', 'history',
        'code', 'branch', 'tag', 'commits',
    ]

    # 1. Try to find a markdown heading (# style) that's a real README heading
    heading_re = re.compile(r'^(#{1,3})\s+(.+)$', re.MULTILINE)
    for m in heading_re.finditer(after_nav):
        heading_text = m.group(2).strip()
        heading_lower = heading_text.lower()

        if heading_lower in nav_skip_headings:
            continue
        if any(p in heading_lower for p in skip_patterns):
            continue
        if heading_text.startswith('['):
            continue

        return nav_idx + m.start()

    # 2. Fallback: look for RST-style heading (text followed by === or ---)
    #    Pattern: a non-empty line followed by a line of = or - characters
    rst_re = re.compile(r'^([A-Za-z][^\n]+)\n(={3,}|-{3,})\s*$', re.MULTILINE)
    for m in rst_re.finditer(after_nav):
        heading_text = m.group(1).strip()
        heading_lower = heading_text.lower()

        # Skip nav-like headings
        if heading_lower in nav_skip_headings:
            continue
        if any(p in heading_lower for p in skip_patterns):
            continue

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
        return clean_github_content(markdown, url=url)
    # Future: add cleaners for other sources (ProductHunt, Dev.to, etc.)
    return markdown
