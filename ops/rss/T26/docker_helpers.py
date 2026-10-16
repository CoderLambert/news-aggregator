"""Bounded local test containers with exact-name, exact-label cleanup on failure."""
import json
import subprocess


def isolated_run(arguments, *, name, project, timeout=180):
    """arguments start with docker run; never clean containers from a prefix."""
    assert arguments[:2]==['docker','run']
    argv=arguments[:2]+['--name',name,'--label','org.newshub.rehearsal='+project]+arguments[2:]
    existing=subprocess.run(['docker','inspect',name],text=True,capture_output=True,timeout=30)
    if existing.returncode==0:
        raise RuntimeError('refusing existing container name')
    try:
        result=subprocess.run(argv,text=True,capture_output=True,timeout=timeout)
        if result.returncode:
            raise RuntimeError(result.stderr[-4000:])
        return result
    finally:
        inspected=subprocess.run(['docker','inspect',name],text=True,capture_output=True,timeout=30)
        if inspected.returncode==0:
            container=json.loads(inspected.stdout)[0]
            if (container['Config'].get('Labels') or {}).get('org.newshub.rehearsal')!=project:
                raise RuntimeError('refusing cleanup outside the exact rehearsal label')
            subprocess.run(['docker','rm','-f',container['Id']],check=True,text=True,capture_output=True,timeout=30)
