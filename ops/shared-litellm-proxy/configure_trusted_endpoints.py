"""Offline, atomic generation of the administrator-approved LiteLLM routes."""
import argparse
import os
from pathlib import Path
import sys
import tempfile

import yaml

# The container mounts this same pure contract beside the callback. A checkout
# can use its original source directly, without copying backend packages.
contract_directory = Path(__file__).resolve().parent.parent.parent / 'backend/api/services'
if contract_directory.is_dir():
    sys.path.insert(0, str(contract_directory))

from ai_endpoint_profiles import load_endpoint_profiles
from trusted_routes import build_proxy_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--base', required=True)
    parser.add_argument('--output', required=True)
    arguments = parser.parse_args()
    temporary = None
    try:
        base, manifest, output = map(Path, (arguments.base, arguments.manifest, arguments.output))
        if output.is_symlink() or output.resolve() in (base.resolve(), manifest.resolve()):
            raise ValueError
        profiles = load_endpoint_profiles(str(manifest))
        raw = base.read_text(encoding='utf-8')
        if len(raw) > 1024 * 1024:
            raise ValueError
        config = yaml.safe_load(raw)
        if type(config) is not dict:
            raise ValueError
        generated = build_proxy_config(config, profiles)
        output.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix='.newshub-routes-', dir=output.parent)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            yaml.safe_dump(generated, handle, sort_keys=False, allow_unicode=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
        temporary = None
        return 0
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError):
        print('trusted endpoint configuration rejected', file=sys.stderr)
        return 64
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


if __name__ == '__main__':
    raise SystemExit(main())
