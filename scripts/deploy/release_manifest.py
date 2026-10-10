#!/usr/bin/env python3
"""Create and validate non-secret release manifests for immutable images."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
REVISION_LABEL = "org.opencontainers.image.revision"
PRODUCTION_USER = "10001:10001"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
IMAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@-]*$")
DIGEST_RE = re.compile(r"^.+@sha256:[0-9a-f]{64}$")
MIGRATION_APP_RE = re.compile(r"^[A-Za-z0-9_]+$")
MIGRATION_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


class ManifestError(ValueError):
    """Raised when a release image or manifest does not meet the contract."""


def validate_image_reference(image: str, release_sha: str) -> str:
    if not SHA_RE.fullmatch(release_sha):
        raise ManifestError("release SHA must be exactly 40 lowercase hex characters")
    if not IMAGE_RE.fullmatch(image) or any(char in image for char in "\n\r\t"):
        raise ManifestError("image reference contains invalid characters")
    if "@" in image:
        if not DIGEST_RE.fullmatch(image):
            raise ManifestError("image digest must use an exact sha256 digest")
        return image
    tag = image.rsplit(":", 1)[-1]
    if tag == "latest":
        raise ManifestError("mutable latest image references are forbidden")
    if not re.search(rf"(?:^|[-_.]){re.escape(release_sha)}$", tag):
        raise ManifestError("image tag must contain the exact requested release SHA suffix")
    return image


def validate_manifest(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "release_sha",
        "image",
        "migrations",
        "static_sha",
    }:
        raise ManifestError("manifest fields are incomplete or unknown")
    if type(value["schema_version"]) is not int or value["schema_version"] != SCHEMA_VERSION:
        raise ManifestError("unsupported manifest schema version")
    release_sha = value["release_sha"]
    if not isinstance(release_sha, str) or not SHA_RE.fullmatch(release_sha):
        raise ManifestError("manifest release_sha is invalid")
    image = value["image"]
    if not isinstance(image, str):
        raise ManifestError("manifest image is invalid")
    validate_image_reference(image, release_sha)
    static_sha = value["static_sha"]
    if not isinstance(static_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", static_sha):
        raise ManifestError("manifest static_sha is invalid")
    migrations = value["migrations"]
    if not isinstance(migrations, list):
        raise ManifestError("manifest migrations must be a list")
    seen: set[tuple[str, str]] = set()
    for migration in migrations:
        if not isinstance(migration, dict) or set(migration) != {"app", "name"}:
            raise ManifestError("manifest migration entries must contain app and name")
        app, name = migration["app"], migration["name"]
        if not isinstance(app, str) or not MIGRATION_APP_RE.fullmatch(app):
            raise ManifestError("manifest migration app is invalid")
        if not isinstance(name, str) or not MIGRATION_NAME_RE.fullmatch(name):
            raise ManifestError("manifest migration name is invalid")
        pair = (app, name)
        if pair in seen:
            raise ManifestError("manifest migrations contain duplicates")
        seen.add(pair)
    if migrations != sorted(migrations, key=lambda item: (item["app"], item["name"])):
        raise ManifestError("manifest migrations must be sorted")
    return value


def sha256_tree(root: Path) -> str:
    if root.is_symlink() or not root.is_dir():
        raise ManifestError("static root must be a real directory")
    digest = hashlib.sha256()
    files = sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix())
    for path in files:
        if path.is_symlink():
            raise ManifestError("static tree contains a symlink")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ManifestError("static tree contains a non-regular file")
        relative = path.relative_to(root).as_posix().encode("utf-8")
        file_hash = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                file_hash.update(chunk)
        digest.update(relative)
        digest.update(b"\0")
        digest.update(file_hash.digest())
        digest.update(b"\n")
    return digest.hexdigest()


def sha256_exported_release(release_root: Path) -> str:
    """Hash one immutable release and verify its assets are shared hardlinks."""
    if release_root.is_symlink() or not release_root.is_dir():
        raise ManifestError("release directory must be a real directory")
    release_assets = release_root / "assets"
    shared_assets = release_root.parent.parent / "assets"
    if release_assets.is_symlink() or not release_assets.is_dir():
        raise ManifestError("release assets must be a real directory")
    if shared_assets.is_symlink() or not shared_assets.is_dir():
        raise ManifestError("shared assets directory is missing or invalid")

    for path in shared_assets.rglob("*"):
        if path.is_symlink():
            raise ManifestError("shared assets contain a symlink")
        if not path.is_dir() and not path.is_file():
            raise ManifestError("shared assets contain a non-regular file")

    entries: list[tuple[str, Path]] = []
    asset_count = 0
    for path in sorted(release_root.rglob("*"), key=lambda item: item.relative_to(release_root).as_posix()):
        if path.is_symlink():
            raise ManifestError("release contains a symlink")
        relative_path = path.relative_to(release_root)
        if path.is_dir():
            continue
        if not path.is_file():
            raise ManifestError("release contains a non-regular file")
        if relative_path.parts[0] == "assets":
            asset_count += 1
            shared_path = shared_assets.joinpath(*relative_path.parts[1:])
            if shared_path.is_symlink() or not shared_path.is_file():
                raise ManifestError("release asset is missing from shared assets")
            try:
                if not os.path.samefile(path, shared_path):
                    raise ManifestError("release asset is not the matching shared hardlink")
            except OSError:
                raise ManifestError("release asset is not the matching shared hardlink") from None
        entries.append((relative_path.as_posix(), path))

    if not (release_root / "index.html").is_file() or (release_root / "index.html").is_symlink():
        raise ManifestError("release is missing index.html")
    if asset_count == 0:
        raise ManifestError("release assets directory is empty")

    digest = hashlib.sha256()
    for relative, path in sorted(entries, key=lambda item: item[0]):
        file_hash = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                file_hash.update(chunk)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.digest())
        digest.update(b"\n")
    return digest.hexdigest()


def _docker_text(*args: str) -> str:
    try:
        result = subprocess.run(
            ["docker", *args], check=True, capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ManifestError(f"Docker image inspection failed ({type(exc).__name__})") from None
    return result.stdout.strip()


def inspect_production_image(image: str, release_sha: str) -> None:
    validate_image_reference(image, release_sha)
    label = _docker_text(
        "image", "inspect", "--format", f"{{{{ index .Config.Labels \"{REVISION_LABEL}\" }}}}", image
    )
    if not SHA_RE.fullmatch(label) or label != release_sha:
        raise ManifestError("image revision label does not match the requested SHA")
    user = _docker_text("image", "inspect", "--format", "{{.Config.User}}", image)
    if user != PRODUCTION_USER:
        raise ManifestError("image is not the non-root production target")


_IMAGE_QUERY = r"""
import hashlib, json, os
from pathlib import Path
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'newsaggregator.settings')
import django
django.setup()
from django.db.migrations.loader import MigrationLoader
loader = MigrationLoader(None)
migrations = [
    {'app': app, 'name': name}
    for app, name in sorted(loader.disk_migrations)
]
root = Path('/app/frontend/dist')
if root.is_symlink() or not root.is_dir():
    raise SystemExit('image static directory missing')
digest = hashlib.sha256()
for path in sorted(root.rglob('*'), key=lambda item: item.relative_to(root).as_posix()):
    if path.is_symlink():
        raise SystemExit('image static tree contains a symlink')
    if path.is_dir():
        continue
    if not path.is_file():
        raise SystemExit('image static tree contains a non-regular file')
    file_hash = hashlib.sha256(path.read_bytes()).digest()
    digest.update(path.relative_to(root).as_posix().encode('utf-8'))
    digest.update(b'\0')
    digest.update(file_hash)
    digest.update(b'\n')
print(json.dumps({'migrations': migrations, 'static_sha': digest.hexdigest()}, sort_keys=True))
"""


def describe_image(image: str, release_sha: str) -> dict[str, Any]:
    inspect_production_image(image, release_sha)
    env = [
        "--env",
        "DJANGO_ENV=production",
        "--env",
        "DJANGO_DEBUG=0",
        "--env",
        "DJANGO_SECRET_KEY=NH-PUB-11-manifest-only-synthetic-key-not-a-credential-4f3e2d1c0b",
        "--env",
        "WAITRESS_TRUSTED_PROXY=127.0.0.1",
        "--env",
        "RUN_MAIN=true",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
    ]
    try:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--pull=never",
                "--network",
                "none",
                "--entrypoint",
                "python",
                *env,
                image,
                "-c",
                _IMAGE_QUERY,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ManifestError(f"could not read migration/static metadata from image ({type(exc).__name__})") from None
    try:
        image_data = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        raise ManifestError("image metadata output is not valid JSON") from None
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "release_sha": release_sha,
        "image": image,
        "migrations": image_data.get("migrations"),
        "static_sha": image_data.get("static_sha"),
    }
    return validate_manifest(manifest)


def _write_new_json(path: Path, value: dict[str, Any]) -> None:
    if path.is_symlink():
        raise ManifestError("manifest output must not be a symlink")
    parent = path.parent.resolve(strict=True)
    if not parent.is_dir():
        raise ManifestError("manifest output parent must be a directory")
    destination = parent / path.name
    if destination.exists() or destination.is_symlink():
        raise ManifestError("manifest output already exists; refusing to overwrite")
    fd, temporary_name = tempfile.mkstemp(prefix=".newshub-manifest.", dir=parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, destination)
    except FileExistsError:
        raise ManifestError("manifest output already exists; refusing to overwrite") from None
    finally:
        temporary.unlink(missing_ok=True)


def load_manifest(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ManifestError("manifest path must be a regular file")
    try:
        return validate_manifest(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        raise ManifestError("manifest file is unreadable or invalid JSON") from None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    describe = subparsers.add_parser("describe", help="read manifest metadata from a local image")
    describe.add_argument("--image", required=True)
    describe.add_argument("--sha", required=True)
    describe.add_argument("--output", type=Path)
    validate = subparsers.add_parser("validate", help="strictly validate a manifest JSON file")
    validate.add_argument("--manifest", required=True, type=Path)
    validate.add_argument("--image")
    validate.add_argument("--sha")
    validate_static = subparsers.add_parser("validate-static", help="verify exported static content")
    validate_static.add_argument("--release", required=True, type=Path)
    validate_static.add_argument("--expected-sha", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "describe":
            manifest = describe_image(args.image, args.sha)
            if args.output:
                _write_new_json(args.output, manifest)
            print(json.dumps(manifest, sort_keys=True))
        elif args.command == "validate":
            manifest = load_manifest(args.manifest)
            if args.image is not None or args.sha is not None:
                if not args.image or not args.sha:
                    raise ManifestError("--image and --sha must be provided together")
                validate_image_reference(args.image, args.sha)
                if manifest["image"] != args.image or manifest["release_sha"] != args.sha:
                    raise ManifestError("manifest does not match the requested image/SHA")
                inspect_production_image(args.image, args.sha)
            print(json.dumps(manifest, sort_keys=True))
        else:
            if not re.fullmatch(r"[0-9a-f]{64}", args.expected_sha):
                raise ManifestError("expected static SHA must be 64 lowercase hex characters")
            actual_sha = sha256_exported_release(args.release)
            if actual_sha != args.expected_sha:
                raise ManifestError("exported static content does not match the image manifest")
            print(json.dumps({"static_sha": actual_sha, "status": "valid"}, sort_keys=True))
    except ManifestError as exc:
        print(f"release-manifest: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
