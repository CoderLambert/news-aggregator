"""Build/run local full-app synthetic compatibility candidates, never seal them."""
import argparse
from email.parser import BytesParser
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import shutil
import tempfile
import uuid

ROOT=Path(__file__).resolve().parents[3]


def command(args, *, timeout=180):
    result=subprocess.run(args,cwd=ROOT,text=True,capture_output=True,timeout=timeout)
    if result.returncode:
        raise RuntimeError('command failed: '+repr(args)+'\n'+result.stdout+'\n'+result.stderr)
    return result.stdout


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True,help='fresh path directly under /tmp')
    parser.add_argument('--dependency-site',type=Path,default=Path('/tmp/newshub-rss-coordinator-venv/lib/python3.12/site-packages'),help='read-only installed pinned listparser/defusedxml source')
    parser.add_argument('--full-app-base',default='news-aggregator:local')
    parser.add_argument('--rss-dep-base',default='newshub-rss-t09:isolated-check')
    parser.add_argument('--candidate',help='existing local newshub-rss-t26:* full app image')
    parser.add_argument('--rollback-candidate',help='optional separately-built compatible local newshub-rss-t26:* image')
    args=parser.parse_args()
    output=args.output.absolute()
    if output.parent!=Path('/tmp') or output.exists() or not output.name.startswith('newshub-rss-t26-'):
        parser.error('requires a fresh /tmp/newshub-rss-t26-* directory')
    endpoint=command(['docker','context','inspect','--format','{{.Endpoints.docker.Host}}']).strip()
    if os.environ.get('DOCKER_HOST') or os.environ.get('DOCKER_CONTEXT') or not endpoint.startswith('unix://'):
        parser.error('requires default local Unix Docker context, no overrides')
    sha=command(['git','rev-parse','HEAD']).strip()
    command(['git','diff','--exit-code','HEAD','--','backend','crawler'])
    project='newshub-rss-t26-'+uuid.uuid4().hex[:12]
    image=args.candidate or 'newshub-rss-t26:candidate-'+project.rsplit('-',1)[-1]+'-'+sha
    rollback=args.rollback_candidate or image
    for value in (image,rollback):
        if not re.fullmatch(r'newshub-rss-t26:[A-Za-z0-9_.-]+',value):
            parser.error('only explicit local T26 candidate tags accepted')
    bases={tag:json.loads(command(['docker','image','inspect',tag]))[0] for tag in (args.full_app_base,args.rss_dep_base)}
    if not args.candidate:
        print('building full application candidate',image,flush=True)
        with tempfile.TemporaryDirectory(prefix='newshub-rss-t26-deps-') as extra:
            site=args.dependency_site.resolve(strict=True)
            locked=(ROOT/'backend/requirements.txt').read_text().splitlines()
            for name,version in (('listparser','0.20'),('defusedxml','0.7.1')):
                if name+'=='+version not in locked:
                    parser.error('candidate dependency is not pinned in backend requirements')
                metadata=BytesParser().parsebytes((site/(name+'-'+version+'.dist-info')/'METADATA').read_bytes())
                if metadata['Name'].lower()!=name or metadata['Version']!=version:
                    parser.error('dependency-site metadata does not match required pin')
            for package in ('listparser','listparser-0.20.dist-info','defusedxml','defusedxml-0.7.1.dist-info'):
                shutil.copytree(site/package,Path(extra)/package,ignore=shutil.ignore_patterns('__pycache__'))
            command(['docker','build','--network=none','--pull=false','-f','ops/rss/T26/Dockerfile.candidate',
                '--build-context','rss-extra='+extra,'--build-arg','FULL_APP_BASE='+args.full_app_base,
                '--build-arg','RSS_DEP_BASE='+args.rss_dep_base,'--build-arg','RELEASE_SHA='+sha,'-t',image,'.'],timeout=600)
    for tag,value in bases.items():
        assert json.loads(command(['docker','image','inspect',tag]))[0]['Id']==value['Id'], 'base tag changed during build'
    inspections={tag:json.loads(command(['docker','image','inspect',tag]))[0] for tag in {image,rollback}}
    for value in inspections.values():
        assert value['Config']['Labels']['org.newshub.rehearsal']=='synthetic-candidate-unsealed'
        assert re.fullmatch('[a-f0-9]{40}',value['Config']['Labels']['org.opencontainers.image.revision'])
    output.mkdir(mode=0o700)
    (output/'SYNTHETIC_ONLY').write_text('T26 synthetic, never production\n')
    runs=[]
    stages=[(image,'seed','seed'),(image,'upgrade','upgrade'),(image,'exercise','exercise'),
        (image,'verify','current'),(rollback,'verify','rollback'),(image,'verify','forward')]
    for index,(tag,stage,label) in enumerate(stages):
        name=project+'-'+str(index)
        appsha=inspections[tag]['Config']['Labels']['org.opencontainers.image.revision']
        argv=['docker','run','--rm','--name',name,'--label','org.newshub.rehearsal='+project,
            '--user',str(os.getuid())+':'+str(os.getgid()),'--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
            '--tmpfs','/tmp:rw,nosuid,nodev,size=256m','--mount','type=bind,source='+str(output)+',target=/evidence',
            '-e','DJANGO_DB_PATH=/evidence/synthetic.sqlite3','-e','REHEARSAL_APP_SHA='+appsha,
            '-e','REHEARSAL_STAGE='+label,'-e','DJANGO_SECRET_KEY=synthetic-t26-only-not-production',
            '--mount','type=bind,source='+str(ROOT/'ops/rss/T26/probe.py')+',target=/rehearsal/probe.py,readonly',
            '--entrypoint','python',tag,'/rehearsal/probe.py',stage]
        print('running',label,flush=True)
        try:
            text=command(argv,timeout=240)
        except Exception as error:
            (output/(label+'.failure.log')).write_text(str(error)+'\n')
            raise
        finally:
            inspected=subprocess.run(['docker','inspect',name],text=True,capture_output=True,timeout=30)
            if inspected.returncode==0:
                container=json.loads(inspected.stdout)[0]
                if (container['Config'].get('Labels') or {}).get('org.newshub.rehearsal')!=project:
                    raise RuntimeError('refusing cleanup of a container outside this exact project')
                command(['docker','rm','-f',container['Id']],timeout=30)
        (output/(label+'.log')).write_text(text)
        runs.append({'stage':label,'image':tag,'image_id':inspections[tag]['Id'],'app_sha':appsha,'stdout':text.strip()})
    assert not command(['docker','ps','-aq','--filter','label=org.newshub.rehearsal='+project]).strip()
    schema=json.loads((output/'forward.json').read_text())['schema']
    files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.iterdir()) if p.is_file()}
    evidence={'status':'SYNTHETIC_CANDIDATE_NOT_SEALED','sealed':False,'dataset':'synthetic',
        'tool_checkout_sha':sha,'app_sha':inspections[image]['Config']['Labels']['org.opencontainers.image.revision'],'dependency_site':str(args.dependency_site),'extra_dependency_pins':{'listparser':'0.20','defusedxml':'0.7.1'},'harness_sha256':hashlib.sha256((ROOT/'ops/rss/T26/probe.py').read_bytes()).hexdigest(),'schema':schema,'project':project,'runs':runs,'artifacts':files,
        'build_bases':{tag:{'id':v['Id'],'repo_digests':v.get('RepoDigests',[]),'revision':(v['Config'].get('Labels') or {}).get('org.opencontainers.image.revision')} for tag,v in bases.items()} if not args.candidate else {},
        'images':{tag:{'id':v['Id'],'repo_digests':v.get('RepoDigests',[]),'revision':v['Config']['Labels']['org.opencontainers.image.revision'],
            'size_bytes':v['Size']} for tag,v in inspections.items()},
        'isolation':{'network':'none','published_ports':[],'volumes':[],'bind_allowlist':[str(output),str(ROOT/'ops/rss/T26/probe.py')],
            'containers_removed':True,'real_provider_calls':False},
        'limitations':['No authorized production backup copy; production compatibility NOT sealed.',
            'Source switch policy receipts are synthetic; real sync and paired restore are separate evidence.',
            'Cached full-app dependency/frontend base is reused; this is not a release Dockerfile rebuild.',
            'Same-schema rollback candidate may be identical code; distinct target must be recorded when supplied.']}
    (output/'candidate.json').write_text(json.dumps(evidence,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'status':evidence['status'],'candidate':str(output/'candidate.json')}),flush=True)


if __name__=='__main__':
    main()
