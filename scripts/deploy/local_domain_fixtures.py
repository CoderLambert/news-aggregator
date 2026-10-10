#!/usr/bin/env python3
"""Private fixture material for the isolated G2 local-domain smoke.

This module runs on the host to create a mode-0600 credential bundle.  Its
``emit-program`` command writes a fixed Django fixture program to stdout; the
smoke pipes that program to ``docker compose exec -i app python -`` so no
password, invitation, cookie, or test body appears in a process argument.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import sys
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
PROJECT_PATTERN = re.compile(r"^newshub-local-g2-[0-9]+-[0-9a-f]{16}$")
USERNAME_PATTERN = re.compile(r"^nhsmoke_[a-z0-9_]{3,64}$")


def _password() -> str:
    return f"Nh!{secrets.token_urlsafe(32)}9z"


def _person(run_id: str, role: str) -> dict[str, str]:
    username = f"nhsmoke_{role}_{run_id}"
    return {
        "username": username,
        "email": f"{role}-{run_id}@example.invalid",
        "password": _password(),
    }


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or path.exists():
        raise ValueError("fixture output must be a new regular file")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            fd = -1
            json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
    finally:
        if fd >= 0:
            os.close(fd)


def create_bundle(path: Path) -> dict[str, Any]:
    run_id = secrets.token_hex(6)
    users = {
        role: _person(run_id, role)
        for role in ("a", "b", "admin", "rate")
    }
    invitations = {
        role: {
            "token": secrets.token_urlsafe(32),
            "email": users[role]["email"],
        }
        for role in ("a", "b")
    }
    invitations.update({
        "wrong_email": {
            "token": secrets.token_urlsafe(32),
            "email": f"bound-{run_id}@example.invalid",
        },
        "expired": {
            "token": secrets.token_urlsafe(32),
            "email": f"expired-{run_id}@example.invalid",
        },
        "weak": {
            "token": secrets.token_urlsafe(32),
            "email": f"weak-{run_id}@example.invalid",
        },
    })
    negative = {
        "wrong_email": {
            "username": f"nhsmoke_wrong_email_{run_id}",
            "email": f"mismatch-{run_id}@example.invalid",
            "password": _password(),
        },
        "expired": {
            "username": f"nhsmoke_expired_{run_id}",
            "email": invitations["expired"]["email"],
            "password": _password(),
        },
        "weak": {
            "username": f"nhsmoke_weak_{run_id}",
            "email": invitations["weak"]["email"],
            "password": "password",
        },
        "reused": {
            "username": f"nhsmoke_reused_{run_id}",
            "email": users["a"]["email"],
            "password": _password(),
        },
        "missing": {
            "username": f"nhsmoke_missing_{run_id}",
            "email": f"missing-{run_id}@example.invalid",
            "password": _password(),
        },
    }
    registration_probes = [
        {
            "username": f"nhsmoke_probe_{run_id}_{ip_index}_{attempt}",
            "email": f"probe-{run_id}-{ip_index}-{attempt}@example.invalid",
            "password": _password(),
        }
        for ip_index in range(5)
        for attempt in range(4)
    ]
    bundle: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "users": users,
        "invitations": invitations,
        "negative_registrations": negative,
        "registration_probes": registration_probes,
        "news": {
            "title": f"NewshubLocalDomainG2Fixture-{run_id}",
            "category": f"NewsHub Local G2 {run_id}",
            "source": f"NewsHub Local G2 Fixture {run_id}",
        },
    }
    validate_bundle(bundle)
    _write_private_json(path, bundle)
    return bundle


def validate_bundle(bundle: object) -> dict[str, Any]:
    if not isinstance(bundle, dict) or bundle.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported fixture bundle")
    run_id = bundle.get("run_id")
    if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{12}", run_id):
        raise ValueError("invalid fixture run identifier")
    users = bundle.get("users")
    if not isinstance(users, dict) or set(users) != {"a", "b", "admin", "rate"}:
        raise ValueError("invalid fixture users")
    for role, person in users.items():
        if not isinstance(person, dict) or set(person) != {"username", "email", "password"}:
            raise ValueError("invalid fixture user record")
        if not isinstance(person["username"], str) or not USERNAME_PATTERN.fullmatch(person["username"]):
            raise ValueError("fixture username is not smoke-owned")
        if not person["username"].endswith(run_id):
            raise ValueError("fixture username does not match the run")
        if not isinstance(person["email"], str) or not person["email"].endswith("@example.invalid"):
            raise ValueError("fixture email must be synthetic")
        if not isinstance(person["password"], str) or len(person["password"]) < 32:
            raise ValueError("fixture password is too short")
    invitations = bundle.get("invitations")
    if not isinstance(invitations, dict) or set(invitations) != {
        "a", "b", "wrong_email", "expired", "weak",
    }:
        raise ValueError("invalid fixture invitations")
    for invitation in invitations.values():
        if not isinstance(invitation, dict) or set(invitation) != {"token", "email"}:
            raise ValueError("invalid invitation record")
        if not isinstance(invitation["token"], str) or len(invitation["token"]) < 32:
            raise ValueError("invitation token is too short")
        if not isinstance(invitation["email"], str) or not invitation["email"].endswith("@example.invalid"):
            raise ValueError("invitation email must be synthetic")
    negatives = bundle.get("negative_registrations")
    if not isinstance(negatives, dict) or set(negatives) != {
        "wrong_email", "expired", "weak", "reused", "missing",
    }:
        raise ValueError("invalid negative registration fixtures")
    for value in negatives.values():
        if not isinstance(value, dict) or set(value) != {"username", "email", "password"}:
            raise ValueError("invalid negative registration record")
        if not isinstance(value["username"], str) or not value["username"].startswith("nhsmoke_"):
            raise ValueError("negative fixture username is not smoke-owned")
        if not isinstance(value["email"], str) or not value["email"].endswith("@example.invalid"):
            raise ValueError("negative fixture email must be synthetic")
        if not isinstance(value["password"], str):
            raise ValueError("invalid negative fixture password")
    probes = bundle.get("registration_probes")
    if not isinstance(probes, list) or len(probes) != 20:
        raise ValueError("registration probes must cover five IPs with four extra attempts")
    for person in probes:
        if not isinstance(person, dict) or set(person) != {"username", "email", "password"}:
            raise ValueError("invalid registration probe")
        if not person["username"].startswith("nhsmoke_") or not person["email"].endswith("@example.invalid"):
            raise ValueError("registration probe is not synthetic")
        if not isinstance(person["password"], str) or len(person["password"]) < 32:
            raise ValueError("registration probe password is too short")
    news = bundle.get("news")
    if not isinstance(news, dict) or set(news) != {"title", "category", "source"}:
        raise ValueError("invalid news fixture")
    if not all(isinstance(value, str) and value.endswith(run_id) for value in news.values()):
        raise ValueError("news fixture does not match the run")
    return bundle


def load_bundle(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise ValueError("fixture bundle must not be a symlink")
    info = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError("fixture bundle must be a regular mode-0600 file")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise ValueError("fixture bundle must be owned by the smoke user")
    return validate_bundle(json.loads(path.read_text(encoding="utf-8")))


APP_PROGRAM = r'''
import hashlib, json, os, re, sys
from pathlib import Path

def refuse():
    raise SystemExit("local-domain fixture precondition failed")

env = os.environ
project = env.get("NEWSHUB_LOCAL_DOMAIN_PROJECT", "")
if not re.fullmatch(r"newshub-local-g2-[0-9]+-[0-9a-f]{16}", project): refuse()
if env.get("NEWSHUB_LOCAL_DOMAIN_FIXTURE_CONFIRMATION") != project: refuse()
if env.get("NEWSHUB_LOCAL_DOMAIN_STAGE") != "g2": refuse()
if env.get("DJANGO_ENV") != "production" or env.get("DJANGO_DEBUG") != "0": refuse()
if env.get("PUBLIC_SITE_MODE") != "full" or env.get("PUBLIC_SIGNUP_ENABLED") != "1": refuse()
if env.get("PUBLIC_AI_ENABLED") != "0" or env.get("CHATGPT_PLAN_USAGE_ENABLED") != "0": refuse()
if env.get("CHATGPT_AUTH_MODE") != "disabled": refuse()
if env.get("CRAWLER_SCHEDULER_ENABLED") != "0" or env.get("CRAWL_RUN_ON_START") != "0": refuse()
if env.get("SEARCH_INDEX_ENABLED") != "0" or env.get("RUN_MAIN") != "true": refuse()
if os.getuid() != 10001: refuse()
db_path = Path(env.get("DJANGO_DB_PATH", ""))
db_root = Path("/var/lib/newshub/db")
if not db_path.is_absolute() or ".." in db_path.parts or not db_path.is_relative_to(db_root): refuse()
if db_path == db_root or db_path.name != "db.sqlite3": refuse()
revision = env.get("NEWSHUB_LOCAL_DOMAIN_REVISION", "")
image = env.get("NEWSHUB_LOCAL_DOMAIN_IMAGE", "")
if not re.fullmatch(r"[0-9a-f]{40}", revision) or not image.endswith(revision): refuse()

import django
django.setup()
from django.conf import settings
if settings.DJANGO_ENV != "production" or settings.DEBUG: refuse()
if settings.PUBLIC_SITE_MODE != "full" or not settings.PUBLIC_SIGNUP_ENABLED: refuse()
if settings.PUBLIC_AI_ENABLED or settings.CHATGPT_PLAN_USAGE_ENABLED: refuse()
if settings.CHATGPT_AUTH_MODE != "disabled": refuse()
if Path(settings.DATABASES["default"]["NAME"]) != db_path: refuse()

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from datetime import timedelta
from api.models import Category, ChatSession, Favorite, News, ResearchSession, SignupInvite, Source
from api.services.account_security import _bucket_key, _window_start

bundle = _FIXTURE_BUNDLE
run_id = bundle["run_id"]
User = get_user_model()

def user_for(role):
    person = bundle["users"][role]
    return User.objects.get(username=person["username"])

def record_token(invite, *, expires_at, email=None):
    SignupInvite.objects.create(
        token_digest=hashlib.sha256(invite["token"].encode("utf-8")).hexdigest(),
        email=email or invite["email"],
        expires_at=expires_at,
    )

def active_window_count(kind, identity, seconds):
    start, _retry_after = _window_start(timezone.now(), seconds)
    key = _bucket_key(kind, identity)
    row = __import__("api.models", fromlist=["AuthRateBucket"]).AuthRateBucket.objects.filter(
        key=key, window_start=start,
    ).values_list("count", flat=True).first()
    return int(row or 0)

phase = _FIXTURE_PHASE
with transaction.atomic():
    if phase == "seed":
        if User.objects.exists(): refuse()
        category = Category.objects.create(
            name=bundle["news"]["category"], slug="newshub-local-g2-" + run_id,
        )
        source = Source.objects.create(
            name=bundle["news"]["source"], url="https://fixture.invalid/" + run_id,
        )
        news = News.objects.create(
            title=bundle["news"]["title"], content="Synthetic G2 account ownership fixture.",
            full_content="## Synthetic G2 fixture\n\nOnly local test data.",
            full_content_fetch_status="success", publish_time=timezone.now(),
            source=source, category=category,
            url="https://fixture.invalid/newshub-local-g2-" + run_id,
        )
        admin = User.objects.create_superuser(
            username=bundle["users"]["admin"]["username"],
            email=bundle["users"]["admin"]["email"],
            password=bundle["users"]["admin"]["password"],
        )
        rate = User.objects.create_user(
            username=bundle["users"]["rate"]["username"],
            email=bundle["users"]["rate"]["email"],
            password=bundle["users"]["rate"]["password"],
        )
        if not admin.is_active or not admin.is_superuser or rate.is_superuser: refuse()
        now = timezone.now()
        record_token(bundle["invitations"]["a"], expires_at=now + timedelta(hours=1))
        record_token(bundle["invitations"]["b"], expires_at=now + timedelta(hours=1))
        record_token(bundle["invitations"]["wrong_email"], expires_at=now + timedelta(hours=1))
        record_token(bundle["invitations"]["expired"], expires_at=now - timedelta(minutes=1))
        record_token(bundle["invitations"]["weak"], expires_at=now + timedelta(hours=1))
        result = {"ok": True, "news_id": news.pk, "users_seeded": 2}
    elif phase == "attach-owner":
        expected = {
            person["username"] for person in bundle["users"].values()
        }
        actual = set(User.objects.values_list("username", flat=True))
        if actual != expected or any(not name.startswith("nhsmoke_") for name in actual): refuse()
        user_a = user_for("a")
        user_b = user_for("b")
        news = News.objects.get(title=bundle["news"]["title"])
        favorite = Favorite.objects.create(user=user_a, news=news, type="bookmark")
        marker = "nhsmoke-private-chat-" + run_id
        chat = ChatSession.objects.create(
            user=user_a, news=news,
            messages=[{"role": "user", "content": marker}],
        )
        research_marker = "nhsmoke-private-research-" + run_id
        research = ResearchSession.objects.create(
            user=user_a, title="Synthetic private research " + run_id,
            messages=[{"role": "assistant", "content": research_marker}],
        )
        if user_b.favorites.exists() or user_b.news_chat_sessions.exists() or user_b.research_sessions.exists(): refuse()
        result = {
            "ok": True, "news_id": news.pk, "favorite_id": favorite.pk,
            "chat_id": chat.pk, "research_id": str(research.pk),
            "chat_marker": marker, "research_marker": research_marker,
        }
    elif phase == "deactivate-admin":
        admin = user_for("admin")
        if not admin.is_superuser or not admin.username.startswith("nhsmoke_"): refuse()
        admin.is_active = False
        admin.save(update_fields=["is_active"])
        result = {"ok": True, "admin_active": False}
    elif phase == "audit":
        expected = {person["username"] for person in bundle["users"].values()}
        expected.update(item["username"] for item in bundle["negative_registrations"].values())
        # Negative usernames must never be created.
        actual = set(User.objects.values_list("username", flat=True))
        core = {person["username"] for person in bundle["users"].values()}
        if actual != core or not all(name.startswith("nhsmoke_") for name in actual): refuse()
        for role in ("a", "b"):
            invite = SignupInvite.objects.get(
                token_digest=hashlib.sha256(bundle["invitations"][role]["token"].encode("utf-8")).hexdigest(),
            )
            if invite.consumed_by_id != user_for(role).pk or invite.consumed_at is None: refuse()
        for role in ("wrong_email", "expired", "weak"):
            invite = SignupInvite.objects.get(
                token_digest=hashlib.sha256(bundle["invitations"][role]["token"].encode("utf-8")).hexdigest(),
            )
            if invite.consumed_at is not None or invite.consumed_by_id is not None: refuse()
        result = {"ok": True, "synthetic_user_count": len(actual), "negative_users_created": 0}
    elif phase == "login-rate-count":
        username = bundle["users"]["rate"]["username"].casefold()
        count = active_window_count("login_ip_username", "127.0.0.70\0" + username, 600)
        result = {"ok": True, "count": count}
    elif phase == "registration-rate-counts":
        from api.services.account_security import normalize_remote_addr
        from api.models import AuthRateBucket
        start, _retry_after = _window_start(timezone.now(), 3600)
        ips = ["127.0.0.61", "127.0.0.62", "127.0.0.63", "127.0.0.64", "127.0.0.65"]
        counts = []
        for address in ips:
            key = _bucket_key("register_ip", normalize_remote_addr(address))
            row = AuthRateBucket.objects.filter(key=key, window_start=start).values_list("count", flat=True).first()
            counts.append(int(row or 0))
        global_key = _bucket_key("register_global", "global")
        global_row = AuthRateBucket.objects.filter(key=global_key, window_start=start).values_list("count", flat=True).first()
        result = {"ok": True, "per_ip_counts": counts, "global_count": int(global_row or 0)}
    else:
        refuse()

sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
'''


def render_app_program(bundle: dict[str, Any], phase: str) -> str:
    validated = validate_bundle(bundle)
    allowed = {
        "seed", "attach-owner", "deactivate-admin", "audit",
        "login-rate-count", "registration-rate-counts",
    }
    if phase not in allowed:
        raise ValueError("unsupported fixture phase")
    literal = repr(json.dumps(validated, sort_keys=True, separators=(",", ":")))
    prefix = (
        "import json\n"
        f"_FIXTURE_BUNDLE = json.loads({literal})\n"
        f"_FIXTURE_PHASE = {phase!r}\n"
    )
    return prefix + APP_PROGRAM


def _command_create(args: argparse.Namespace) -> int:
    create_bundle(args.output)
    print(json.dumps({"created": True, "mode": "0600"}))
    return 0


def _command_emit(args: argparse.Namespace) -> int:
    bundle = load_bundle(args.bundle)
    sys.stdout.write(render_app_program(bundle, args.phase))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--output", required=True, type=Path)
    create.set_defaults(handler=_command_create)
    emit = commands.add_parser("emit-program")
    emit.add_argument("--bundle", required=True, type=Path)
    emit.add_argument("--phase", required=True)
    emit.set_defaults(handler=_command_emit)
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"local-domain fixtures: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
