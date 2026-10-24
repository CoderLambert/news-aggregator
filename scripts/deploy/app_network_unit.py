#!/usr/bin/env python3
"""Compose helpers for the app network-namespace unit.

Services that set ``network_mode: service:app`` join the app container's
network namespace. Recreating ``app`` alone leaves those sidecars attached to a
dead netns (loopback gateway → Connection refused). Operator actions that
replace or restart ``app`` must therefore expand to the whole unit.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


SERVICE_NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]*$')
PROJECT_RE = re.compile(r'^newshub-local-[a-z0-9][a-z0-9_-]{0,48}$')
DEFAULT_TARGET = 'app'
GATEWAY_LIVELINESS_URL = 'http://127.0.0.1:4000/health/liveliness'


class AppNetworkUnitError(RuntimeError):
    pass


def shared_network_sidecars(services: dict, target: str = DEFAULT_TARGET) -> list[str]:
    if not isinstance(services, dict):
        raise AppNetworkUnitError('Compose services document must be an object')
    if not SERVICE_NAME_RE.fullmatch(target):
        raise AppNetworkUnitError('unsafe target service name')
    if target not in services:
        raise AppNetworkUnitError(f'target service is missing from Compose config: {target}')
    expected = f'service:{target}'
    names: list[str] = []
    for name in sorted(services):
        if not SERVICE_NAME_RE.fullmatch(name):
            raise AppNetworkUnitError('unsafe service name in Compose config')
        config = services[name]
        if isinstance(config, dict) and config.get('network_mode') == expected:
            names.append(name)
    return names


def recreate_unit(services: dict, target: str = DEFAULT_TARGET) -> list[str]:
    return [target, *shared_network_sidecars(services, target)]


def unit_from_compose_document(document: dict, target: str = DEFAULT_TARGET) -> list[str]:
    if not isinstance(document, dict):
        raise AppNetworkUnitError('Compose config must be an object')
    services = document.get('services')
    return recreate_unit(services if isinstance(services, dict) else {}, target)


def unit_from_compose_json(text: str, target: str = DEFAULT_TARGET) -> list[str]:
    try:
        document = json.loads(text)
    except (TypeError, ValueError) as error:
        raise AppNetworkUnitError('Compose JSON config is invalid') from error
    return unit_from_compose_document(document, target)


def expand_services_for_app_action(requested: list[str], unit: list[str],
                                   *, target: str = DEFAULT_TARGET) -> list[str]:
    """Fail closed when an app action omits part of the network unit.

    - ``[app]`` or any list that includes ``app`` but none of the sidecars expands
      to the full unit (with a caller-visible expansion).
    - A partial sidecar subset with ``app`` raises (do not silently drop members).
    - Requests that do not mention ``app`` are returned unchanged.
    """
    if not unit or unit[0] != target:
        raise AppNetworkUnitError('recreate unit must start with the target service')
    requested_list = list(requested)
    if target not in requested_list:
        return requested_list
    sidecars = unit[1:]
    present = [name for name in sidecars if name in requested_list]
    if present and set(present) != set(sidecars):
        missing = sorted(set(sidecars) - set(present))
        raise AppNetworkUnitError(
            'refusing partial app network unit; missing sidecars: ' + ', '.join(missing)
        )
    # Preserve caller order for non-unit services, but keep unit contiguous.
    others = [name for name in requested_list if name not in unit]
    return list(unit) + others


def load_activation_receipt(runtime_root: Path, project: str) -> dict:
    path = runtime_root / 'last-activation.json'
    if path.is_symlink() or not path.is_file():
        raise AppNetworkUnitError('activation receipt is missing or is a symlink')
    try:
        receipt = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise AppNetworkUnitError('activation receipt is unreadable') from error
    if not isinstance(receipt, dict) or receipt.get('project') != project:
        raise AppNetworkUnitError('activation receipt does not match the requested project')
    return receipt


def _compose_command(*, project: str, compose_files: list[Path], env_file: Path | None,
                     project_directory: Path | None) -> list[str]:
    command = ['docker', 'compose', '-p', project]
    if project_directory is not None:
        command += ['--project-directory', str(project_directory)]
    for path in compose_files:
        command += ['-f', str(path)]
    if env_file is not None:
        command += ['--env-file', str(env_file)]
    return command


def _run(arguments: list[str], *, environment=None, timeout: int = 300) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            arguments, check=True, capture_output=True, text=True,
            env=environment, timeout=timeout,
        )
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or '').strip().splitlines()
        summary = detail[-1] if detail else f'exit {error.returncode}'
        raise AppNetworkUnitError(f'command failed: {summary}') from None
    except subprocess.TimeoutExpired as error:
        raise AppNetworkUnitError('command timed out') from error


def discover_unit_from_compose(*, project: str, compose_files: list[Path],
                               env_file: Path | None, project_directory: Path | None,
                               target: str, environment=None) -> list[str]:
    command = _compose_command(
        project=project, compose_files=compose_files, env_file=env_file,
        project_directory=project_directory,
    ) + ['config', '--format', 'json']
    result = _run(command, environment=environment, timeout=120)
    return unit_from_compose_json(result.stdout, target)


def verify_gateway_liveliness(*, project: str, compose_files: list[Path],
                              env_file: Path | None, project_directory: Path | None,
                              environment=None, timeout: int = 15) -> None:
    command = _compose_command(
        project=project, compose_files=compose_files, env_file=env_file,
        project_directory=project_directory,
    ) + [
        'exec', '-T', DEFAULT_TARGET, 'python', '-c',
        'import urllib.request;'
        f'r=urllib.request.urlopen({GATEWAY_LIVELINESS_URL!r}, timeout=3);'
        'raise SystemExit(0 if getattr(r, "status", 200)==200 else 1)',
    ]
    try:
        _run(command, environment=environment, timeout=timeout)
    except AppNetworkUnitError as error:
        raise AppNetworkUnitError(
            'app network unit self-check failed: gateway liveliness is not 200 from app netns'
        ) from error


def recreate_app_unit(*, project: str, compose_files: list[Path], env_file: Path | None,
                      project_directory: Path | None, wait_timeout: int,
                      execute: bool, environment=None) -> dict[str, object]:
    unit = discover_unit_from_compose(
        project=project, compose_files=compose_files, env_file=env_file,
        project_directory=project_directory, target=DEFAULT_TARGET,
        environment=environment,
    )
    plan = {
        'execute': execute,
        'project': project,
        'unit': unit,
        'action': 'up -d --no-deps --force-recreate --no-build --pull never --wait',
        'gateway_liveliness_url': GATEWAY_LIVELINESS_URL,
    }
    if not execute:
        return plan
    command = _compose_command(
        project=project, compose_files=compose_files, env_file=env_file,
        project_directory=project_directory,
    ) + [
        'up', '-d', '--no-deps', '--force-recreate', '--no-build', '--pull', 'never',
        '--wait', '--wait-timeout', str(wait_timeout), *unit,
    ]
    _run(command, environment=environment, timeout=wait_timeout + 180)
    verify_gateway_liveliness(
        project=project, compose_files=compose_files, env_file=env_file,
        project_directory=project_directory, environment=environment,
    )
    plan['verified_gateway_liveliness'] = True
    return plan


def restart_app_unit(*, project: str, compose_files: list[Path], env_file: Path | None,
                     project_directory: Path | None, execute: bool,
                     environment=None) -> dict[str, object]:
    unit = discover_unit_from_compose(
        project=project, compose_files=compose_files, env_file=env_file,
        project_directory=project_directory, target=DEFAULT_TARGET,
        environment=environment,
    )
    plan = {
        'execute': execute,
        'project': project,
        'unit': unit,
        'action': 'restart',
        'gateway_liveliness_url': GATEWAY_LIVELINESS_URL,
    }
    if not execute:
        return plan
    command = _compose_command(
        project=project, compose_files=compose_files, env_file=env_file,
        project_directory=project_directory,
    ) + ['restart', *unit]
    _run(command, environment=environment, timeout=180)
    verify_gateway_liveliness(
        project=project, compose_files=compose_files, env_file=env_file,
        project_directory=project_directory, environment=environment,
    )
    plan['verified_gateway_liveliness'] = True
    return plan


def _paths_from_receipt(receipt: dict) -> tuple[list[Path], Path | None, Path | None]:
    compose_files = receipt.get('compose_files')
    if not isinstance(compose_files, list) or not compose_files:
        raise AppNetworkUnitError('activation receipt is missing compose_files')
    paths: list[Path] = []
    for item in compose_files:
        path = Path(str(item))
        if path.is_symlink() or not path.is_file():
            raise AppNetworkUnitError(f'compose file from receipt is missing: {path}')
        paths.append(path)
    env_raw = receipt.get('env_file')
    env_file = Path(str(env_raw)) if env_raw else None
    if env_file is not None and (env_file.is_symlink() or not env_file.is_file()):
        raise AppNetworkUnitError('env file from receipt is missing')
    source_raw = receipt.get('source_root')
    project_directory = Path(str(source_raw)) if source_raw else None
    if project_directory is not None and not project_directory.is_dir():
        raise AppNetworkUnitError('source_root from receipt is not a directory')
    return paths, env_file, project_directory


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Operate the local app + network_mode:service:app sidecar unit.',
    )
    parser.add_argument('command', choices=(
        'list-unit', 'recreate-app', 'restart-app', 'expand-services',
    ))
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--project', default='newshub-local-main')
    parser.add_argument('--runtime-root', type=Path)
    parser.add_argument('--compose', action='append', default=[], dest='compose_files')
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--project-directory', type=Path)
    parser.add_argument('--target', default=DEFAULT_TARGET)
    parser.add_argument('--wait-timeout', type=int, default=300)
    parser.add_argument('--from-json', action='store_true',
                        help='Read merged Compose JSON on stdin (list-unit / expand-services).')
    parser.add_argument('--services', nargs='*', default=None,
                        help='Service names for expand-services.')
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    if not re.fullmatch(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,48}$', args.project):
        raise AppNetworkUnitError('project name is unsafe')
    if not 30 <= args.wait_timeout <= 1200:
        raise AppNetworkUnitError('wait timeout must be between 30 and 1200 seconds')

    if args.command in {'list-unit', 'expand-services'} and args.from_json:
        unit = unit_from_compose_json(sys.stdin.read(), args.target)
        if args.command == 'list-unit':
            print('\n'.join(unit))
            return 0
        requested = list(args.services or [])
        expanded = expand_services_for_app_action(requested, unit, target=args.target)
        if expanded != requested and args.target in requested:
            print(
                'app_network_unit: expanding app-only action to unit: '
                + ' '.join(expanded),
                file=sys.stderr,
            )
        print('\n'.join(expanded))
        return 0

    compose_files = [Path(item) for item in args.compose_files]
    env_file = args.env_file
    project_directory = args.project_directory
    if not compose_files:
        runtime_root = (
            args.runtime_root or Path.home() / '.local/share' / args.project
        ).absolute()
        receipt = load_activation_receipt(runtime_root, args.project)
        compose_files, env_file, project_directory = _paths_from_receipt(receipt)

    for path in compose_files:
        if path.is_symlink() or not path.is_file():
            raise AppNetworkUnitError(f'compose file must be a regular file: {path}')
    if env_file is not None and (env_file.is_symlink() or not env_file.is_file()):
        raise AppNetworkUnitError('env file must be a regular file')

    if args.command == 'list-unit':
        unit = discover_unit_from_compose(
            project=args.project, compose_files=compose_files, env_file=env_file,
            project_directory=project_directory, target=args.target,
        )
        print('\n'.join(unit))
        return 0

    if args.command == 'expand-services':
        unit = discover_unit_from_compose(
            project=args.project, compose_files=compose_files, env_file=env_file,
            project_directory=project_directory, target=args.target,
        )
        requested = list(args.services or [])
        expanded = expand_services_for_app_action(requested, unit, target=args.target)
        if expanded != requested and args.target in requested:
            print(
                'app_network_unit: expanding app-only action to unit: '
                + ' '.join(expanded),
                file=sys.stderr,
            )
        print('\n'.join(expanded))
        return 0

    if not PROJECT_RE.fullmatch(args.project):
        raise AppNetworkUnitError('project must be an explicit newshub-local-* name')

    if args.command == 'recreate-app':
        plan = recreate_app_unit(
            project=args.project, compose_files=compose_files, env_file=env_file,
            project_directory=project_directory, wait_timeout=args.wait_timeout,
            execute=args.execute,
        )
    else:
        plan = restart_app_unit(
            project=args.project, compose_files=compose_files, env_file=env_file,
            project_directory=project_directory, execute=args.execute,
        )
    print(json.dumps(plan, sort_keys=True))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except AppNetworkUnitError as error:
        print('app_network_unit: ' + str(error), file=sys.stderr)
        raise SystemExit(2) from None
