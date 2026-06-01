from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag

from .site_rules import SiteRule, get_site_rule, normalize_domain


@dataclass
class ExtractedArticle:
    markdown: str
    title: str = ''
    canonical_url: str = ''


NOISE_SELECTORS = [
    'script', 'style', 'noscript', 'svg', 'canvas', 'iframe', 'form',
    'nav', 'footer', 'header', 'aside', '[role="navigation"]',
    '.newsletter', '.subscribe', '.cookie', '.cookies', '.advertisement', '.ad',
    '.related', '.recommended', '.share', '.social', '.comments', '#comments',
    '.share-buttons', '.social-share', '.share-icons', '[data-share]',
    '.share-link', '.social-buttons', '.social-icons', '.share-widget',
]

GENERIC_SELECTORS = [
    'article',
    'main article',
    'main',
    '[role="main"]',
    '.article-content',
    '.entry-content',
    '.post-content',
    '.story-body',
    '.content',
]


def _domain(url: str) -> str:
    return normalize_domain(url)


def _clean_soup(soup: BeautifulSoup, remove_selectors: list[str] | tuple[str, ...] | None = None) -> None:
    selectors = [*NOISE_SELECTORS, *(remove_selectors or [])]
    for selector in selectors:
        for node in soup.select(selector):
            node.decompose()
    for node in soup.find_all(string=lambda s: isinstance(s, str) and not s.strip()):
        node.extract()


def _pick_content_node(soup: BeautifulSoup, url: str) -> Tag:
    rule = get_site_rule(url)
    selectors: list[str] = [*(rule.selectors if rule else ()), *GENERIC_SELECTORS]

    candidates: list[Tag] = []
    for selector in selectors:
        candidates.extend([n for n in soup.select(selector) if isinstance(n, Tag)])
    if not candidates and soup.body:
        candidates = [soup.body]
    if not candidates:
        return soup

    def score(node: Tag) -> int:
        text = node.get_text(' ', strip=True)
        paragraphs = len(node.find_all('p'))
        headings = len(node.find_all(re.compile('^h[1-3]$')))
        links = len(node.find_all('a'))
        return len(text) + paragraphs * 120 + headings * 60 - links * 8

    return max(candidates, key=score)


def _title_from_soup(soup: BeautifulSoup, node: Tag, rule: SiteRule | None = None) -> str:
    selectors = rule.title_selectors if rule else ()
    for selector in selectors:
        title_node = node.select_one(selector) if isinstance(node, Tag) else None
        if not title_node:
            title_node = soup.select_one(selector)
        if title_node:
            text = title_node.get_text(' ', strip=True)
            if text:
                return text
    h1 = node.find('h1') if isinstance(node, Tag) else None
    if h1:
        return h1.get_text(' ', strip=True)
    meta = soup.find('meta', attrs={'property': 'og:title'})
    if meta and meta.get('content'):
        return str(meta['content']).strip()
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    return ''


def _canonical_from_soup(soup: BeautifulSoup, base_url: str) -> str:
    link = soup.find('link', rel=lambda value: value and 'canonical' in value)
    if link and link.get('href'):
        return urljoin(base_url, str(link['href']).strip())
    meta = soup.find('meta', attrs={'property': 'og:url'})
    if meta and meta.get('content'):
        return urljoin(base_url, str(meta['content']).strip())
    return ''


def _is_tracking_pixel(img_url: str, width: str | None, height: str | None) -> bool:
    """检测是否是追踪像素或 spacer GIF"""
    if not img_url:
        return True
    # 检查常见的追踪像素文件名
    url_lower = img_url.lower()
    # 检查文件名是否以追踪像素关键词开头或包含在路径中
    basename = url_lower.split('/')[-1].split('?')[0]  # 获取文件名部分
    tracking_names = ['pixel', 'spacer', 'blank', 'transparent', 'tracking', 'beacon']
    # 检查文件名是否以这些关键词开头（如 pixel.gif, spacer.png）
    name_without_ext = basename.split('.')[0] if '.' in basename else basename
    if name_without_ext in tracking_names:
        return True
    # 检查 1x1 像素尺寸（只在明确设置了尺寸时检查）
    if width is not None and height is not None:
        try:
            w = int(width)
            h = int(height)
            if w == 1 and h == 1:
                return True
            if w <= 0 or h <= 0:
                return True
        except (ValueError, TypeError):
            pass
    return False


def _img_to_markdown(img: Tag, base_url: str) -> str:
    """将 <img> 标签转换为 Markdown 图片格式"""
    src = img.get('src') or img.get('data-src') or img.get('data-original')
    if not src:
        return ''
    
    # 获取尺寸信息用于过滤追踪像素
    width_attr = img.get('width')
    height_attr = img.get('height')
    width = str(width_attr) if width_attr is not None else None
    height = str(height_attr) if height_attr is not None else None
    
    # 过滤追踪像素
    if _is_tracking_pixel(str(src), width, height):
        return ''
    
    # 转换为绝对 URL
    img_url = urljoin(base_url, str(src).strip())
    
    # 获取 alt 文本
    alt = img.get('alt', '')
    if isinstance(alt, str):
        alt = alt.strip()
    else:
        alt = ''
    
    # 获取可选的 title
    title = img.get('title', '')
    if isinstance(title, str):
        title = title.strip()
    else:
        title = ''
    
    # 构建 Markdown 图片语法
    if title:
        return f'![{alt}]({img_url} "{title}")'
    return f'![{alt}]({img_url})'


def _escape_md(text: str) -> str:
    return text.replace('\u00a0', ' ').strip()


def _node_to_markdown(node: Tag | NavigableString, base_url: str, depth: int = 0) -> str:
    if isinstance(node, NavigableString):
        return _escape_md(str(node))
    if not isinstance(node, Tag):
        return ''

    name = node.name.lower()
    if name in {'script', 'style', 'noscript'}:
        return ''
    if name in {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}:
        level = int(name[1])
        text = _inline_text(node, base_url)
        return f"\n{'#' * level} {text}\n" if text else ''
    if name == 'p':
        text = _inline_text(node, base_url)
        return f"\n{text}\n" if text else ''
    if name == 'blockquote':
        text = _children_markdown(node, base_url, depth).strip()
        if not text:
            return ''
        return '\n' + '\n'.join('> ' + line for line in text.splitlines()) + '\n'
    if name in {'ul', 'ol'}:
        lines = []
        ordered = name == 'ol'
        for i, li in enumerate(node.find_all('li', recursive=False), 1):
            text = _inline_text(li, base_url)
            if text:
                prefix = f'{i}. ' if ordered else '- '
                lines.append(prefix + text)
        return '\n' + '\n'.join(lines) + '\n' if lines else ''
    if name == 'pre':
        code = node.get_text('\n', strip=False).strip('\n')
        return f"\n```\n{code}\n```\n" if code else ''
    if name == 'table':
        return _table_to_markdown(node, base_url)
    if name == 'img':
        img_md = _img_to_markdown(node, base_url)
        return f'\n\n{img_md}\n\n' if img_md else ''
    if name in {'article', 'main', 'section', 'div', 'body'}:
        return _children_markdown(node, base_url, depth)
    return _children_markdown(node, base_url, depth)


def _inline_text(node: Tag, base_url: str) -> str:
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, NavigableString):
            parts.append(str(child))
        elif isinstance(child, Tag):
            name = child.name.lower()
            if name == 'a':
                text = child.get_text(' ', strip=True)
                href = child.get('href')
                if text and href:
                    parts.append(f'[{text}]({urljoin(base_url, str(href))})')
                elif text:
                    parts.append(text)
            elif name in {'strong', 'b'}:
                text = child.get_text(' ', strip=True)
                if text:
                    parts.append(f'**{text}**')
            elif name in {'em', 'i'}:
                text = child.get_text(' ', strip=True)
                if text:
                    parts.append(f'*{text}*')
            elif name == 'code':
                text = child.get_text(' ', strip=True)
                if text:
                    parts.append(f'`{text}`')
            elif name == 'br':
                parts.append('\n')
            elif name == 'img':
                img_md = _img_to_markdown(child, base_url)
                if img_md:
                    parts.append(f'\n\n{img_md}\n\n')
            else:
                parts.append(_inline_text(child, base_url))
    text = ''.join(parts)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return _escape_md(text)


def _children_markdown(node: Tag, base_url: str, depth: int = 0) -> str:
    chunks = [_node_to_markdown(child, base_url, depth + 1) for child in node.children]
    text = '\n'.join(c.strip('\n') for c in chunks if c and c.strip())
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip() + ('\n' if text.strip() else '')


def _table_to_markdown(table: Tag, base_url: str) -> str:
    rows = []
    for tr in table.find_all('tr'):
        cells = [_inline_text(c, base_url).replace('|', '\\|') for c in tr.find_all(['th', 'td'])]
        if cells:
            rows.append(cells)
    if not rows:
        return ''
    width = max(len(r) for r in rows)
    rows = [r + [''] * (width - len(r)) for r in rows]
    out = ['| ' + ' | '.join(rows[0]) + ' |', '| ' + ' | '.join(['---'] * width) + ' |']
    for row in rows[1:]:
        out.append('| ' + ' | '.join(row) + ' |')
    return '\n' + '\n'.join(out) + '\n'


def extract_markdown_from_html(html: str, url: str) -> ExtractedArticle:
    soup = BeautifulSoup(html or '', 'html.parser')
    rule = get_site_rule(url)
    _clean_soup(soup, rule.remove_selectors if rule else None)
    node = _pick_content_node(soup, url)
    title = _title_from_soup(soup, node, rule)
    canonical = _canonical_from_soup(soup, url)
    markdown = _node_to_markdown(node, url).strip()
    markdown = re.sub(r'\n{3,}', '\n\n', markdown).strip()
    return ExtractedArticle(markdown=markdown, title=title, canonical_url=canonical)
