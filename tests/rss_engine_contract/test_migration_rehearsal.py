"""T26 runner safety: real failing/timeout containers, and fresh-target gates."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import uuid
import pytest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('t26_docker_helpers',ROOT/'ops/rss/T26/docker_helpers.py')
helpers=importlib.util.module_from_spec(spec); spec.loader.exec_module(helpers)


@pytest.mark.parametrize('destination',['/tmp','/tmp/not-t26','/home/lambert'])
def test_runner_refuses_nonfresh_or_nonallowlisted_output(destination):
    result=subprocess.run([sys.executable,str(ROOT/'ops/rss/T26/run.py'),'--output',destination],capture_output=True,text=True)
    assert result.returncode==2 and 'fresh /tmp/newshub-rss-t26-' in result.stderr


@pytest.mark.rss_live
@pytest.mark.parametrize('kind',['timeout','failed_exit'])
def test_exact_container_cleanup_on_live_failure(kind):
    if os.environ.get('RSS_TEST_ALLOW_LIVE')!='1':
        pytest.skip('explicit isolated live opt-in required')
    endpoint=subprocess.run(['docker','context','inspect','--format','{{.Endpoints.docker.Host}}'],check=True,text=True,capture_output=True).stdout.strip()
    assert endpoint.startswith('unix://') and not os.environ.get('DOCKER_HOST') and not os.environ.get('DOCKER_CONTEXT')
    project='newshub-rss-t26-'+uuid.uuid4().hex[:12]
    name=project+'-cleanup'
    code="print('started',flush=True); import time; time.sleep(30)" if kind=='timeout' else 'raise SystemExit(7)'
    with pytest.raises(subprocess.TimeoutExpired if kind=='timeout' else RuntimeError):
        helpers.isolated_run(['docker','run','--rm','--network','none','--entrypoint','python','python:3.12-slim','-c',code],
            name=name,project=project,timeout=2)
    remaining=subprocess.run(['docker','ps','-aq','--filter','label=org.newshub.rehearsal='+project],check=True,text=True,capture_output=True).stdout.strip()
    assert remaining==''
