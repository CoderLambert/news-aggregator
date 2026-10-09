"""Clean Markdown content for TTS speech synthesis.

Strips all structural markup (headers, links, images, code blocks, etc.)
and returns clean, natural-reading plain text suitable for text-to-speech.
Also provides audio caching and voice selection.
"""

import hashlib
import os
import re
import time
from dataclasses import dataclass

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


@dataclass(frozen=True)
class ResolvedTTSContent:
    language: str
    title: str
    content: str
    namespace: str


class TTSContentUnavailable(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _cache_key(news_id: int, variant: str) -> str:
    """Generate an opaque key that includes content and translation ownership."""
    raw = f'{news_id}:{variant}'
    return hashlib.sha256(raw.encode()).hexdigest()


def get_cached_audio(news_id: int, variant: str):
    """Return cached MP3 file path if it exists, else None."""
    key = _cache_key(news_id, variant)
    path = os.path.join(TTS_CACHE_DIR, f'{key}.mp3')
    if os.path.isfile(path) and os.path.getsize(path) > 100:
        return path
    return None


def save_to_cache(news_id: int, variant: str, audio_bytes: bytes) -> str:
    """Save audio bytes to cache and return the file path."""
    os.makedirs(TTS_CACHE_DIR, exist_ok=True)
    key = _cache_key(news_id, variant)
    path = os.path.join(TTS_CACHE_DIR, f'{key}.mp3')
    with open(path, 'wb') as f:
        f.write(audio_bytes)
    return path


def build_cache_variant(resolved: ResolvedTTSContent, scope: str, voice: str, speech_text: str) -> str:
    text_digest = hashlib.sha256(speech_text.encode()).hexdigest()
    return ':'.join((resolved.language, scope, voice, resolved.namespace, text_digest))


def resolve_tts_content(news, user, language: str, scope: str) -> ResolvedTTSContent:
    """Resolve speech content using the same private translation boundary as detail serialization."""
    if language not in {'zh', 'original'}:
        raise TTSContentUnavailable('unsupported_language', '不支持的朗读语言。')
    if scope not in {'summary', 'full'}:
        raise TTSContentUnavailable('unsupported_scope', '不支持的朗读范围。')

    source_language = getattr(news.source, 'language', '')
    if language == 'original' or source_language == 'zh':
        content = news.full_content if scope == 'full' else news.content
        if not content:
            raise TTSContentUnavailable('source_content_required', '所选范围暂无原文内容。')
        return ResolvedTTSContent(
            language='zh' if source_language == 'zh' else 'original',
            title=news.title,
            content=content,
            namespace='source',
        )

    if scope == 'summary':
        content = news.content_zh
        if not content:
            raise TTSContentUnavailable('translation_required', '当前文章暂无中文摘要。')
        return ResolvedTTSContent(
            language='zh', title=news.title_zh, content=content, namespace='shared-summary',
        )

    if not news.full_content:
        raise TTSContentUnavailable('source_content_required', '请先获取完整原文，再翻译并朗读。')

    from api.models import ChatGPTArticleTranslation
    from api.services.chatgpt_subscription import active_connection_for_user, source_hash

    connection = active_connection_for_user(user)
    if connection is not None:
        translation = ChatGPTArticleTranslation.objects.filter(
            user=user,
            connection=connection,
            news=news,
            source_hash=source_hash(news.full_content),
        ).first()
        if translation is not None and translation.content:
            return ResolvedTTSContent(
                language='zh',
                title=news.title_zh,
                content=translation.content,
                namespace=f'subscription:{user.pk}:{connection.pk}',
            )

    from api.services.shared_translations import get_shared_translation
    shared = get_shared_translation(news)
    if shared is not None:
        return ResolvedTTSContent(
            language='zh', title=news.title_zh, content=shared.content,
            namespace='shared-full',
        )

    if connection is not None or not news.full_content_zh:
        raise TTSContentUnavailable('translation_required', '请先翻译全文，再播放中文语音。')
    return ResolvedTTSContent(
        language='zh', title=news.title_zh, content=news.full_content_zh, namespace='shared-full',
    )


# How many seconds a cached file can go untouched before considered expired.
TTS_CACHE_MAX_AGE = 3 * 24 * 3600  # 3 days


def clean_expired_cache(max_age: int = TTS_CACHE_MAX_AGE) -> tuple[int, int]:
    """Remove cached TTS files not accessed (atime) or modified (mtime) in max_age seconds.

    Returns (removed_count, freed_bytes) so callers can log the result.
    """
    if not os.path.isdir(TTS_CACHE_DIR):
        return 0, 0

    cutoff = time.time() - max_age
    removed = 0
    freed = 0

    for name in os.listdir(TTS_CACHE_DIR):
        if not name.endswith('.mp3'):
            continue
        path = os.path.join(TTS_CACHE_DIR, name)
        try:
            stat = os.stat(path)
            # Use whichever is more recent: last access or last modification
            last_touched = max(stat.st_atime, stat.st_mtime)
            if last_touched < cutoff:
                size = stat.st_size
                os.remove(path)
                removed += 1
                freed += size
        except OSError:
            continue

    return removed, freed


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
