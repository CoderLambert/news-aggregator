"""Clean Markdown content for TTS speech synthesis.

Strips all structural markup (headers, links, images, code blocks, etc.)
and returns clean, natural-reading plain text suitable for text-to-speech.
Also provides audio caching and voice selection.
"""

import hashlib
import os
import re

# Cache directory for generated TTS audio files
TTS_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'media', 'tts_cache',
)

# Available voices for user selection
VOICE_OPTIONS = {
    'yunyang': {
        'id': 'zh-CN-YunyangNeural',
        'label': '云扬',
        'desc': '新闻男声',
        'lang': 'zh',
    },
    'xiaoxiao': {
        'id': 'zh-CN-XiaoxiaoNeural',
        'label': '晓晓',
        'desc': '亲切女声',
        'lang': 'zh',
    },
    'yunxi': {
        'id': 'zh-CN-YunxiNeural',
        'label': '云希',
        'desc': '青年男声',
        'lang': 'zh',
    },
    'guy': {
        'id': 'en-US-GuyNeural',
        'label': 'Guy',
        'desc': 'News Anchor',
        'lang': 'en',
    },
}


def _cache_key(news_id: int, display_mode: str, voice: str) -> str:
    """Generate a deterministic cache key for a TTS request."""
    raw = f'{news_id}:{display_mode}:{voice}'
    return hashlib.md5(raw.encode()).hexdigest()


def get_cached_audio(news_id: int, display_mode: str, voice: str):
    """Return cached MP3 file path if it exists, else None."""
    key = _cache_key(news_id, display_mode, voice)
    path = os.path.join(TTS_CACHE_DIR, f'{key}.mp3')
    if os.path.isfile(path) and os.path.getsize(path) > 100:
        return path
    return None


def save_to_cache(news_id: int, display_mode: str, voice: str, audio_bytes: bytes) -> str:
    """Save audio bytes to cache and return the file path."""
    os.makedirs(TTS_CACHE_DIR, exist_ok=True)
    key = _cache_key(news_id, display_mode, voice)
    path = os.path.join(TTS_CACHE_DIR, f'{key}.mp3')
    with open(path, 'wb') as f:
        f.write(audio_bytes)
    return path


def clean_for_tts(markdown_text: str) -> str:
    """Convert Markdown to clean plain text for TTS.

    Processing order matters — remove block elements first, then inline.
    """
    if not markdown_text:
        return ''

    text = markdown_text

    # 1. Remove fenced code blocks (```...```) entirely
    text = re.sub(r'```[\s\S]*?```', '', text)

    # 2. Remove inline code (`...`)
    text = re.sub(r'`([^`]+)`', r'\1', text)

    # 3. Remove images ![alt](url)
    text = re.sub(r'!\[([^\]]*)\]\([^\)]+\)', r'\1', text)

    # 4. Convert links [text](url) → text
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)

    # 5. Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)

    # 6. Remove Mermaid/diagram blocks (```mermaid ... ```)
    #    Already handled by step 1, but catch any remaining ::: blocks
    text = re.sub(r':::[\s\S]*?:::', '', text)

    # 7. Convert headers (# ...) — keep text, add period
    text = re.sub(r'^#{1,6}\s+(.+)$', r'\1。', text, flags=re.MULTILINE)

    # 8. Remove bold (**text** or __text__) and italic (*text* or _text_)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'__(.+?)__', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'_(.+?)_', r'\1', text)

    # 9. Remove horizontal rules (---, ***, ___)
    text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)

    # 10. Remove blockquotes (> text)
    text = re.sub(r'^>\s*', '', text, flags=re.MULTILINE)

    # 11. Remove list markers (- , * , 1. , etc.) — keep content
    text = re.sub(r'^[\s]*[-*+]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^[\s]*\d+\.\s+', '', text, flags=re.MULTILINE)

    # 12. Remove table separators (|---|---|)
    text = re.sub(r'^\|[\s\-:|]+\|$', '', text, flags=re.MULTILINE)

    # 13. Clean up excessive whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)

    # 14. Strip leading/trailing whitespace per line
    lines = [line.strip() for line in text.split('\n')]
    text = '\n'.join(lines)

    # 15. Add period after lines that end without punctuation (for natural TTS pausing)
    text = re.sub(r'([^\.\!\?\。\！\？\n])\n', r'\1。\n', text)

    return text.strip()


def pick_tts_voice(source_language: str, display_mode: str, has_zh: bool,
                   voice_pref: str = '') -> str:
    """Pick the best Edge TTS voice for the given article.

    Args:
        source_language: 'en' or 'zh'
        display_mode: 'zh', 'original', or 'bilingual'
        has_zh: whether Chinese translation is available
        voice_pref: user voice preference key (e.g. 'xiaoxiao', 'yunxi')

    Returns a voice short name like 'zh-CN-XiaoxiaoNeural'.
    """
    use_chinese = has_zh and display_mode != 'original'

    if source_language == 'zh' or use_chinese:
        # User preference
        if voice_pref and voice_pref in VOICE_OPTIONS:
            v = VOICE_OPTIONS[voice_pref]
            if v['lang'] == 'zh':
                return v['id']
        # Default: YunyangNeural — 男声新闻播报风格
        return 'zh-CN-YunyangNeural'

    # English — user preference
    if voice_pref and voice_pref in VOICE_OPTIONS:
        v = VOICE_OPTIONS[voice_pref]
        if v['lang'] == 'en':
            return v['id']
    return 'en-US-GuyNeural'
