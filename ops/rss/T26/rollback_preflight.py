"""Document the real local named-volume access gate without bypassing quiescence."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import uuid
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from scripts.rss import recovery as rss


def run(args):
    return subprocess.run(args,check=True,text=True,capture_output=True,timeout=30).stdout.strip()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not args.output.is_absolute() or args.output.parent!=Path('/tmp') or not args.output.name.startswith('newshub-rss-t26-') or args.output.exists():
        parser.error('fresh /tmp/newshub-rss-t26-* output required')
    rss.Docker()
    project='newshub-rss-t26-'+uuid.uuid4().hex[:12]
    volume=project+'_db-data'; helper=None
    # Check rather than take over the application's fixed production port.
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1',9527)); free=True
        except OSError:
            free=False
    assert not run(['docker','volume','ls','-q','--filter','name=^'+volume+'$'])
    run(['docker','volume','create','--label','com.docker.compose.project='+project,volume])
    try:
        source=json.loads(run(['docker','volume','inspect',volume]))[0]['Mountpoint']
        try:
            rss.sqlite_target(Path(source)/'db.sqlite3')
            target='accessible'
        except (rss.RecoveryError,PermissionError) as error:
            target=type(error).__name__+': '+str(error)
        helper=run(['docker','run','-d','--name',project+'-helper','--label','org.newshub.rehearsal='+project,
            '--network','none','--mount','type=volume,source='+volume+',target='+source+',readonly',
            '--entrypoint','sleep','python:3.12-slim','infinity'])
        mounted=run(['docker','ps','-q','--no-trunc','--filter','volume='+volume]).splitlines()
        assert mounted==[helper]
        evidence={'status':'BLOCKED' if target!='accessible' else 'READY_FOR_TARGET_SETUP',
            'wrapper_chain_executed':False,'sealed':False,'uid':os.getuid(),'port_9527_free_at_check':free,
            'project':project,'explicit_volume':volume,'inspected_source':source,
            'actual_recovery_sqlite_target_check':target,
            'actual_docker_running_volume_users':[helper],
            'quiesce_implication':'helper is an active volume user; unchanged T03/rollback.sh must refuse it',
            'required_condition':'Authorized host runner able to read the named-volume Source without an active container mounting it',
            'host_permissions_changed':False,'sudo_or_nsenter_used':False}
    finally:
        if helper: run(['docker','rm','-f',helper])
        run(['docker','volume','rm',volume])
    evidence['resources_removed']=True
    args.output.write_text(json.dumps(evidence,indent=2,sort_keys=True)+'\n')
    print(evidence['status']+': explicit named-volume access/quiesce preflight only')


if __name__=='__main__': main()
