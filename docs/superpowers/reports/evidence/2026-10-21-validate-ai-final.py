"""Final evidence gate: reject stale runtime, missing requirements or non-PASS claims."""
from pathlib import Path
import hashlib
import json
import re
import subprocess

root = Path.cwd()
base = root / 'docs/superpowers/reports/evidence'
summary = json.loads((base / '2026-10-21-ai-final-gates.json').read_text())
blob = subprocess.check_output(['git','ls-tree','-r','HEAD','backend/api','backend/newsaggregator',
    'frontend/src','frontend/package-lock.json','ops/shared-litellm-proxy','tools/byok_t00_probe'])
assert hashlib.sha256(blob).hexdigest() == summary['runtime_source_tree_sha256']
assert len(summary['commands']) == 4 and all(r['exit'] == 0 for r in summary['commands'])
assert summary['backend']['passed'] + summary['backend']['skipped'] == summary['backend']['collected']
for name, count in [('ai-proxy-final',295),('ai-trusted-proxy-final',38)]:
    value = json.loads((base / ('2026-10-21-'+name+'.json')).read_text())
    assert value['failed'] == 0 and value['passed'] == count
live = json.loads((base / '2026-10-21-ai-ollama-live.json').read_text())
assert live['cleanup_complete'] and live['candidate'] == summary['code_candidate']
assert len(live['checks']) == 9 and all(row['status'] == 'PASS' for row in live['checks'])
archive = base / summary['archive']['path']
assert hashlib.sha256(archive.read_bytes()).hexdigest() == summary['archive']['sha256']
report = (root / 'docs/superpowers/reports/2026-10-21-newshub-unified-ai-access-v1.md').read_text()
ids = set(re.findall(r'^\| ([FSR]\d{2}) \|',report,re.M))
expected = {f'{group}{i:02}' for group, end in [('F',9),('S',8),('R',8)] for i in range(1,end+1)}
assert ids == expected
assert '- [ ]' not in (root / 'docs/superpowers/plans/2026-10-21-newshub-unified-ai-access-v1.md').read_text()
for target in re.findall(r'\]\(([^)]+)\)',report):
    if not target.startswith(('https:','http:','#')):
        assert (root/'docs/superpowers/reports'/target).exists(), target
print(json.dumps({'status':'PASS','requirements':len(ids),'backend_passed':summary['backend']['passed'],
    'backend_skipped':summary['backend']['skipped'],'frontend_passed':summary['frontend']['passed'],
    'ollama_checks':len(live['checks']),'runtime_unchanged':True}))
