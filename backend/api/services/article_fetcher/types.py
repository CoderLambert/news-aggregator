from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class FetchResult:
    ok: bool
    provider: str
    url: str = ''
    title: str = ''
    canonical_url: str = ''
    markdown: str = ''
    quality_score: float = 0.0
    error: str = ''
    metadata: dict = field(default_factory=dict)
    # Task 7: quality report fields (backward compatible defaults)
    validation_reasons: list[str] = field(default_factory=list)
    content_length: int = 0
    extractor: str = ''


class ArticleProvider(Protocol):
    name: str

    def fetch(self, url: str, expected_title: str | None = None, summary: str | None = None) -> FetchResult:
        ...


class FetchError(Exception):
    def __init__(self, message: str, failures: list[FetchResult] | None = None):
        super().__init__(message)
        self.failures = failures or []
