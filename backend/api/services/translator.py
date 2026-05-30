"""Translation service using deep-translator (Google Translate)."""

import logging
import time
import re

logger = logging.getLogger(__name__)

# Simple in-memory cache to avoid re-translating
_translation_cache = {}
_cache_ttl = 3600  # 1 hour

# Error type constants
ERROR_NETWORK = "network_error"
ERROR_RATE_LIMIT = "rate_limit"
ERROR_TIMEOUT = "timeout"
ERROR_SSL = "ssl_error"
ERROR_UNKNOWN = "unknown"


def _cache_key(text: str, src: str, tgt: str) -> str:
    return f"{src}:{tgt}:{hash(text)}"


def _classify_error(error_str: str) -> str:
    """Classify a translation error into a retryable category."""
    e = error_str.lower()
    if any(kw in e for kw in ["network is unreachable", "connection refused",
                               "no address associated", "network unreachable",
                               "connection aborted", "remote end closed",
                               "remote disconnected"]):
        return ERROR_NETWORK
    if "timed out" in e or "timeout" in e:
        return ERROR_TIMEOUT
    if "ssl" in e or "certificate" in e or "eof" in e:
        return ERROR_SSL
    if "rate" in e or "quota" in e or "429" in e or "too many" in e:
        return ERROR_RATE_LIMIT
    # Anything not matched goes to failed (not unknown)
    return ERROR_UNKNOWN


def translate(text: str, src: str = "en", tgt: str = "zh-CN") -> tuple:
    """Translate text from src language to tgt language.

    Returns:
        tuple: (translated_text: str, error_type: str|None, error_msg: str|None)
        On success: (result, None, None)
        On failure: ("", error_type, error_message)
    """
    if not text or not text.strip():
        return ("", None, None)

    key = _cache_key(text, src, tgt)
    cached = _translation_cache.get(key)
    if cached and cached[1] > time.time():
        return (cached[0], None, None)

    try:
        from deep_translator import GoogleTranslator
        translator = GoogleTranslator(source=src, target=tgt)
        # Google Translate has a ~5000 char limit per request
        # For long content, split into chunks
        if len(text) > 4500:
            result = _translate_chunks(text, src, tgt)
        else:
            result = translator.translate(text)

        _translation_cache[key] = (result, time.time() + _cache_ttl)
        return (result, None, None)
    except Exception as e:
        error_msg = str(e)
        error_type = _classify_error(error_msg)
        logger.warning(f"Translation failed ({src} -> {tgt}): [{error_type}] {error_msg}")
        return ("", error_type, error_msg)


def _translate_chunks(text: str, src: str, tgt: str, chunk_size: int = 4000) -> str:
    """Split long text into chunks and translate each."""
    from deep_translator import GoogleTranslator
    translator = GoogleTranslator(source=src, target=tgt)

    # Split by paragraphs first
    paragraphs = text.split('\n\n')
    chunks = []
    current = ""

    for p in paragraphs:
        if len(current) + len(p) + 2 <= chunk_size:
            current += ('\n\n' + p if current else p)
        else:
            if current:
                chunks.append(current)
            # If single paragraph is too long, split by sentences
            if len(p) > chunk_size:
                sentences = p.replace('. ', '.\n').replace('? ', '?\n').replace('! ', '!\\n')
                parts = sentences.split('\n')
                current = ""
                for s in parts:
                    if len(current) + len(s) + 1 <= chunk_size:
                        current += (' ' + s if current else s)
                    else:
                        if current:
                            chunks.append(current)
                        current = s
            else:
                current = p

    if current:
        chunks.append(current)

    translated_parts = []
    for i, chunk in enumerate(chunks):
        try:
            translated_parts.append(translator.translate(chunk))
        except Exception as e:
            logger.warning(f"Chunk {i} translation failed: {e}")
            translated_parts.append(chunk)
        # Rate limiting
        if i < len(chunks) - 1:
            time.sleep(0.5)

    return '\n\n'.join(translated_parts)


def is_chinese(text: str) -> bool:
    """Simple heuristic: if text contains Chinese characters, it's Chinese."""
    for char in text:
        if '\u4e00' <= char <= '\u9fff':
            return True
    return False


def detect_and_translate(text: str, tgt: str = "zh-CN") -> tuple:
    """Detect if text is non-Chinese and translate to Chinese.

    Returns:
        tuple: (translated_text, error_type, error_msg)
    """
    if not text or not text.strip():
        return ("", None, None)
    if is_chinese(text):
        return (text, None, None)
    return translate(text, src="en", tgt=tgt)
