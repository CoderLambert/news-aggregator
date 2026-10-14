"""Temporary, branch-scoped source assembly and isolated targeted tests.

No arbitrary network, production commands or user credentials. Remove this
workbench before the final integration PR; only reviewed source and tests remain.
"""
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {'backend', 'crawler', 'frontend', 'tests', 'scripts', 'docs'}
STATE = ROOT / '.a09-workbench/state.json'


class Plan:
    def __init__(self):
        self.pending = {}

    def path(self, name):
        p = Path(name)
        if p.is_absolute() or '..' in p.parts or p.parts[0] not in ALLOWED:
            raise ValueError(f'Unapproved source path: {name}')
        if any(part == '.env' or part.startswith('.env.') for part in p.parts):
            raise ValueError('Environment files are outside this task')
        target = ROOT / p
        if target.is_symlink():
            raise ValueError('Symlinks are outside this task')
        return target

    def read(self, name):
        return self.pending.get(name, self.path(name).read_text(encoding='utf-8'))

    def replace(self, name, before, after):
        current = self.read(name)
        if current.count(before) != 1:
            raise ValueError(f'{name}: expected one exact source anchor, got {current.count(before)}')
        self.pending[name] = current.replace(before, after, 1)

    def region(self, name, start, end, replacement):
        current = self.read(name)
        if current.count(start) != 1 or current.count(end) != 1:
            raise ValueError(f'{name}: ambiguous region anchors')
        a, b = current.index(start), current.index(end)
        if a >= b:
            raise ValueError(f'{name}: invalid region')
        self.pending[name] = current[:a] + replacement + current[b:]

    def write(self, name, content):
        path = self.path(name)
        if path.exists() and path.read_text(encoding='utf-8') != content:
            raise ValueError(f'{name}: refusing to overwrite an existing file')
        self.pending[name] = content

    def flush(self):
        # Validate every changed Python file before any source file is replaced.
        for name, content in self.pending.items():
            if name.endswith('.py'):
                compile(content, name, 'exec')
        for name, content in self.pending.items():
            target = self.path(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding='utf-8')
            print(f'APPLIED {name}', flush=True)


def main():
    os.chdir(ROOT)
    mode = sys.argv[1]
    config = json.loads((ROOT / '.a09-workbench/run.json').read_text())
    if mode == 'apply':
        if (os.environ.get('GITHUB_REPOSITORY') != 'CoderLambert/news-aggregator'
                or os.environ.get('GITHUB_REF') != 'refs/heads/work/a09-remaining-development'):
            raise SystemExit('This temporary editor only operates on its approved integration branch')
        subprocess.run(['git', 'merge-base', '--is-ancestor', '0dc445a77b12ec45b8a97d42f75e0df62e1b72d9', 'HEAD'], check=True)
        state = json.loads(STATE.read_text()) if STATE.exists() else {}
        plan = Plan()
        for name in config['batches']:
            if not name.startswith('batch') or '/' in name or not name.endswith('.py'):
                raise ValueError('Invalid batch filename')
            path = ROOT / '.a09-workbench' / name
            signature = hashlib.sha256(path.read_bytes()).hexdigest()
            if name in state:
                if state[name] != signature:
                    raise ValueError('Previously applied batch changed; append a new correction batch')
                continue
            runpy.run_path(str(path), init_globals={'P': plan})
            state[name] = signature
        plan.flush()
        STATE.write_text(json.dumps(state, indent=2, sort_keys=True) + '\n')
    elif mode == 'backend':
        subprocess.run([sys.executable, '-m', 'pytest', '-q', *config['backend']], check=True)
    elif mode == 'frontend':
        if config.get('frontend'):
            subprocess.run(['npm', 'run', 'test:run', '--', *config['frontend']], cwd=ROOT / 'frontend', check=True)
    else:
        raise ValueError('Unknown workbench mode')


if __name__ == '__main__':
    main()
