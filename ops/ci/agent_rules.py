#!/usr/bin/env python3
"""Offline structure checks for NewsHub-owned Agent instructions, not an LLM eval.

Uses only the standard library so the frontend preflight needs no Python deps.
SKILL metadata deliberately uses a tiny YAML-compatible authoring subset:
plain slug `name` plus a JSON-quoted, one-line `description`. This is NOT a
YAML parser or Codex discovery emulator; broader formats need an explicit review.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
RULE_PATHS = (
    'AGENTS.md', 'backend/AGENTS.md', 'frontend/AGENTS.md',
    'backend/api/rss/AGENTS.md', 'ops/ci/AGENTS.md',
    'tests/AGENTS.md', 'scripts/deploy/AGENTS.md',
)
SKILL_NAMES = (
    'newshub-impact-analysis', 'newshub-verify', 'newshub-pr-handoff',
)
# Project budgets leave room for the user's own instructions. They are NOT
# Codex's configured limits and don't measure actual token use.
ROOT_LIMIT = 6 * 1024
MODULE_LIMIT = 4 * 1024
SKILL_LIMIT = 4 * 1024
CHAIN_LIMIT = 16 * 1024
LOCAL_LINK = re.compile(r'\[[^\]\n]+\]\(([^)\s]+)\)')
SLUG = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*\Z')


def read_document(path: Path, root: Path, limit: int) -> str:
    """Read a bounded regular UTF-8 file without following a repo escape."""
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('document must be a regular file inside the repository')
    if not path.is_file():
        raise ValueError('missing document')
    if not 0 < path.stat().st_size <= limit:
        raise ValueError(f'document exceeds {limit} bytes or is empty')
    text = path.read_bytes().decode('utf-8')
    if '\x00' in text or '\r' in text or text.startswith('\ufeff'):
        raise ValueError('use plain UTF-8, LF, no NUL/BOM')
    if not text.endswith('\n'):
        raise ValueError('document must end with a newline')
    return text


def skill_metadata(text: str, expected_name: str) -> str:
    """Validate the approved two-field YAML-compatible subset; return body."""
    lines = text.splitlines()
    if not lines or lines[0] != '---':
        raise ValueError('missing SKILL frontmatter')
    try:
        end = lines.index('---', 1)
    except ValueError as exc:
        raise ValueError('unclosed SKILL frontmatter') from exc
    fields = {}
    for line in lines[1:end]:
        key, sep, value = line.partition(':')
        if not sep or key not in {'name', 'description'} or key in fields:
            raise ValueError('metadata must contain unique name and description only')
        fields[key] = value.strip()
    if fields.keys() != {'name', 'description'}:
        raise ValueError('name and description are required')
    if not SLUG.fullmatch(fields['name']) or fields['name'] != expected_name:
        raise ValueError('name must match the skill directory slug')
    try:
        description = json.loads(fields['description'])
    except (ValueError, TypeError) as exc:
        raise ValueError('description must be one JSON-quoted YAML string') from exc
    if not isinstance(description, str) or not 1 <= len(description) <= 320 or '\n' in description:
        raise ValueError('description must be a short nonempty single-line string')
    return '\n'.join(lines[end + 1:])


def validate_markdown(text: str, path: Path, root: Path) -> None:
    """Check fences and local file links; no network or host files are read."""
    if not text.lstrip().startswith('# '):
        raise ValueError('document needs a top-level heading')
    fence = None
    visible = []
    for line in text.splitlines():
        match = re.match(r'^\s*(`{3,}|~{3,})(.*)$', line)
        if match:
            marker, suffix = match.groups()
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence) and not suffix.strip():
                fence = None
            continue
        if fence is None:
            visible.append(line)
    if fence:
        raise ValueError('unclosed Markdown fence')
    for link in LOCAL_LINK.findall('\n'.join(visible)):
        parsed = urlsplit(link)
        if parsed.scheme in {'https', 'http', 'mailto'} or link.startswith('#'):
            continue
        if parsed.scheme or parsed.netloc or parsed.path.startswith('/'):
            raise ValueError(f'unsupported link: {link}')
        target = (path.parent / unquote(parsed.path)).resolve()
        if not target.is_relative_to(root.resolve()) or not target.is_file():
            raise ValueError(f'broken or escaping local link: {link}')


def check_repository(root: Path = ROOT) -> list[str]:
    errors = []
    sizes = {}
    owned = [(p, ROOT_LIMIT if p == 'AGENTS.md' else MODULE_LIMIT, None) for p in RULE_PATHS]
    owned += [(f'.agents/skills/{n}/SKILL.md', SKILL_LIMIT, n) for n in SKILL_NAMES]
    for relative, limit, name in owned:
        try:
            text = read_document(root / relative, root, limit)
            body = skill_metadata(text, name) if name else text
            validate_markdown(body, root / relative, root)
            sizes[relative] = len(text.encode('utf-8'))
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append(f'{relative}: {exc}')
    for relative in RULE_PATHS:
        ancestors = (root / relative).parent.parents
        total = sizes.get(relative, 0) + sum(
            sizes.get(str((parent / 'AGENTS.md').relative_to(root)), 0)
            for parent in ancestors if parent == root or parent.is_relative_to(root)
        )
        if total > CHAIN_LIMIT:
            errors.append(f'{relative}: repository ancestor chain exceeds {CHAIN_LIMIT} bytes')
    return errors


def main() -> int:
    errors = check_repository()
    for error in errors:
        print(error, file=sys.stderr)
    if not errors:
        print(f'Agent structure PASS: {len(RULE_PATHS)} rule files, {len(SKILL_NAMES)} skills; not a Codex behavior evaluation')
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
