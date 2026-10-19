"""Clean Markdown content for TTS speech synthesis.

Strips all structural markup (headers, links, images, code blocks, etc.)
and returns clean, natural-reading plain text suitable for text-to-speech.
Also provides audio caching and voice selection.
"""

import hashlib
import os
import re
import time
import tempfile
from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


EDGE_TTS_MSEDGESERVICES_BASE_URL = 'api.msedgeservices.com/tts/cognitiveservices'

# Cache directory for generated TTS audio files
_DEFAULT_TTS_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'media', 'tts_cache',
)
TTS_CACHE_DIR = _DEFAULT_TTS_CACHE_DIR


def _cache_directory() -> str:
    # Keep the module constant patchable for existing callers and tests while
    # resolving production paths from Django settings at use time.
    if TTS_CACHE_DIR != _DEFAULT_TTS_CACHE_DIR:
        return os.fspath(TTS_CACHE_DIR)
    try:
        return os.fspath(settings.TTS_CACHE_DIR)
    except ImproperlyConfigured:
        return TTS_CACHE_DIR

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
    snapshot: object = None


class TTSContentUnavailable(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def configure_edge_tts_endpoint() -> str:
    """Select one reviewed edge-tts transport endpoint for this process.

    edge-tts keeps its WebSocket endpoint as a module constant rather than a
    constructor option. All production requests use one validated setting, so
    assigning the same value before synthesis is idempotent across Waitress
    threads and never accepts an arbitrary operator-provided URL.
    """
    from edge_tts import communicate, constants

    endpoint = getattr(settings, 'EDGE_TTS_ENDPOINT', 'default')
    if endpoint == 'default':
        return communicate.WSS_URL
    if endpoint != 'msedgeservices':
        raise ImproperlyConfigured('Unsupported EDGE_TTS_ENDPOINT setting.')

    communicate.WSS_URL = (
        f'wss://{EDGE_TTS_MSEDGESERVICES_BASE_URL}/websocket/v1'
        f'?Ocp-Apim-Subscription-Key={constants.TRUSTED_CLIENT_TOKEN}'
    )
    return communicate.WSS_URL


def _cache_key(news_id: int, variant: str) -> str:
    """Generate an opaque key that includes content and translation ownership."""
    raw = f'{news_id}:{variant}'
    return hashlib.sha256(raw.encode()).hexdigest()


def get_cached_audio(news_id: int, variant: str):
    """Return cached MP3 file path if it exists, else None."""
    key = _cache_key(news_id, variant)
    path = os.path.join(_cache_directory(), f'{key}.mp3')
    if os.path.isfile(path) and os.path.getsize(path) > 100:
        return path
    return None


# Hard ceilings: never hold full audio in process memory or synthesize a whole
# chapter in one upstream session. The UI can offer summary mode instead.
MAX_TTS_SPEECH_CHARS = 12000
MAX_TTS_AUDIO_BYTES = 16 * 1024 * 1024


class TTSCacheSink:
    """Writes a private staging file and publishes only a completed MP3."""
    def __init__(self, news_id: int, variant: str):
        cache_dir = _cache_directory()
        os.makedirs(cache_dir, exist_ok=True)
        key = _cache_key(news_id, variant)
        self.destination = os.path.join(cache_dir, f'{key}.mp3')
        self._file = tempfile.NamedTemporaryFile(
            mode='wb', prefix=f'.{key}-', suffix='.part', dir=cache_dir, delete=False)
        self._tmp = self._file.name
        self._size = 0
        self._closed = False

    def append(self, chunk: bytes):
        if self._closed or not isinstance(chunk, bytes):
            raise ValueError('tts_invalid_audio_chunk')
        if self._size + len(chunk) > MAX_TTS_AUDIO_BYTES:
            raise ValueError('tts_audio_too_large')
        self._file.write(chunk)
        self._size += len(chunk)

    def commit(self) -> str:
        if self._closed:
            raise ValueError('tts_cache_already_closed')
        try:
            self._file.flush()
            os.fsync(self._file.fileno())
            self._file.close()
            self._closed = True
            if self._size == 0:
                raise ValueError('tts_empty_audio')
            os.replace(self._tmp, self.destination)
            return self.destination
        except Exception:
            self.abort()
            raise

    def abort(self):
        if not self._closed:
            self._file.close()
            self._closed = True
        try:
            os.unlink(self._tmp)
        except FileNotFoundError:
            pass


def save_to_cache(news_id: int, variant: str, audio_bytes: bytes) -> str:
    """Compatible helper: atomic replacement, bounded bytes, no visible partial file."""
    sink = TTSCacheSink(news_id, variant)
    try:
        sink.append(audio_bytes)
        return sink.commit()
    finally:
        sink.abort()


def build_cache_variant(resolved: ResolvedTTSContent, scope: str, voice: str, speech_text: str) -> str:
    text_digest = hashlib.sha256(speech_text.encode()).hexdigest()
    return ':'.join((resolved.language, scope, voice, resolved.namespace, text_digest))


def resolve_tts_content(news, user, language: str, scope: str, *, translation_result_id=None) -> ResolvedTTSContent:
    """Resolve speech content using the same private translation boundary as detail serialization."""
    if language not in {'zh', 'original'}:
        raise TTSContentUnavailable('unsupported_language', '不支持的朗读语言。')
    if scope not in {'summary', 'full'}:
        raise TTSContentUnavailable('unsupported_scope', '不支持的朗读范围。')
    if translation_result_id is not None and (language != 'zh' or scope != 'full'):
        raise TTSContentUnavailable('translation_result_unavailable', '所选个人译文不可用于当前朗读范围。')

    from api.services.stored_readers import (
        PrivateTranslationNotFound, article_snapshot, current_translation,
        legacy_translation, translation_for_read,
    )
    from api.rss.access import article_sources
    stored = article_snapshot(news, user)
    if scope == 'full' and stored.scope != 'full':
        raise TTSContentUnavailable('source_content_required', '当前仅可读取摘要。')
    source = article_sources(user, news).first()
    source_language = source.language if source else ''
    content = stored.markdown if scope == 'full' else stored.summary
    namespace = f'source:{stored.canonical_hash}:{stored.revision}'
    if translation_result_id is not None and source_language == 'zh':
        raise TTSContentUnavailable('translation_result_unavailable', '当前原文为中文，不能选择中文个人译文。')
    selected_record = None
    if language == 'zh' and source_language != 'zh':
        # Summary/title compatibility columns have no version proof. Never infer it.
        if scope == 'full':
            try:
                record, visibility = translation_for_read(user, stored, translation_result_id)
            except PrivateTranslationNotFound:
                raise TTSContentUnavailable('translation_result_unavailable', '所选个人译文不可用。') from None
        else:
            legacy = legacy_translation(stored.news_id, 'content', stored.summary)
            from types import SimpleNamespace
            record = SimpleNamespace(content=legacy.translated_text) if legacy else None
            visibility = 'legacy-summary'
        if record is None:
            raise TTSContentUnavailable('translation_required', '当前版本暂无已匹配的中文译文。')
        selected_record = record
        content = record.content
        if getattr(record, 'api_connection_id', None) is not None and getattr(record, 'task_id', None) is not None:
            namespace = f'byok:{user.pk}:result:{record.pk}:task:{record.task_id}'
        else:
            namespace = f'{visibility}:{getattr(user, "pk", "anonymous")}:{getattr(record, "connection_id", "shared")}:{stored.canonical_hash}'
    if not content.strip():
        raise TTSContentUnavailable('source_content_required', '所选范围暂无原文内容。')
    translated_title = legacy_translation(stored.news_id, 'title', stored.title) if language == 'zh' else None
    title = translated_title.translated_text if translated_title else stored.title
    if translation_result_id is not None and selected_record is not None and not selected_record.current_match:
        # Never pair a saved translation with the current title. Use its frozen
        # source title, or omit the title if an older task has no frozen title.
        title = getattr(selected_record, 'source_title', '') or ''
    return ResolvedTTSContent(language='zh' if source_language == 'zh' else language,
        title=title, content=content, namespace=namespace, snapshot=stored)


# How many seconds a cached file can go untouched before considered expired.
TTS_CACHE_MAX_AGE = 3 * 24 * 3600  # 3 days


def clean_expired_cache(max_age: int = TTS_CACHE_MAX_AGE) -> tuple[int, int]:
    """Remove cached TTS files not accessed (atime) or modified (mtime) in max_age seconds.

    Returns (removed_count, freed_bytes) so callers can log the result.
    """
    cache_directory = _cache_directory()
    if not os.path.isdir(cache_directory):
        return 0, 0

    cutoff = time.time() - max_age
    removed = 0
    freed = 0

    for name in os.listdir(cache_directory):
        if not name.endswith('.mp3') and not (name.startswith('.') and name.endswith('.part')):
            continue
        path = os.path.join(cache_directory, name)
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
