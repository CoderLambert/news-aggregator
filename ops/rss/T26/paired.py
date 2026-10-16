"""T26 orchestration of T03 recovery for the upgraded T26 synthetic dataset.

No backup/restore implementation lives here: all pair validation, fingerprints,
quiescence, snapshots and restore mutations go through scripts/rss/recovery.py.
"""
import argparse
import base64
import copy
import json
import inspect
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import urllib.request
import uuid

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from scripts.rss import recovery as rss
from docker_helpers import isolated_run


def run(args,*,ok=True):
    value=subprocess.run(args,cwd=ROOT,text=True,capture_output=True,timeout=240)
    if ok and value.returncode:
        raise RuntimeError(value.stderr[-4000:])
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--python',default='/tmp/newshub-rss-coordinator-venv/bin/python')
    args=parser.parse_args()
    assert args.output.is_absolute() and args.output.parent==Path('/tmp') and args.output.name.startswith('newshub-rss-t26-') and not args.output.exists()
    dataset=args.dataset.resolve()
    assert dataset.parent==Path('/tmp') and dataset.name.startswith('newshub-rss-t26-')
    assert (dataset/'SYNTHETIC_ONLY').read_text().strip()=='T26 synthetic, never production'
    candidate=json.loads((dataset/'candidate.json').read_text())
    assert candidate['sealed'] is False and candidate['dataset']=='synthetic'
    import hashlib
    for filename,expected in candidate['artifacts'].items():
        assert Path(filename).name==filename and hashlib.sha256((dataset/filename).read_bytes()).hexdigest()==expected, 'source artifact changed'
    app_image=candidate['runs'][-1]['image']; app_id=candidate['runs'][-1]['image_id']
    assert json.loads(run(['docker','image','inspect',app_image]).stdout)[0]['Id']==app_id
    project='newshub-rss-t26-'+uuid.uuid4().hex[:12]
    def container(argv,suffix,timeout=240):
        return isolated_run(argv,name=project+'-'+suffix,project=project,timeout=timeout)
    static_code='import hashlib; from pathlib import Path\n'+inspect.getsource(rss.release_manifest.sha256_tree)+"\nprint(sha256_tree(Path('/app/frontend/dist')))"
    static_sha=container(['docker','run','--rm','--network','none','--entrypoint','python',app_id,'-c',static_code],'static').stdout.strip()
    docker=rss.Docker()
    app_image='newshub-rss-t26:pair-'+project.rsplit('-',1)[-1]+'-'+candidate['runs'][-1]['app_sha']
    run(['docker','tag',app_id,app_image])
    for resource in ('container','network','volume'):
        assert not run(['docker',resource,'ls','-aq' if resource=='container' else '-q','--filter','label=com.docker.compose.project='+project]).stdout.strip()
    images=json.loads((ROOT/'ops/rss/T00/versions.json').read_text())['images']
    engine_image,pg_image,python_image=[v['tag']+'@'+v['repo_digests'][0].split('@')[1] for v in images]
    evidence={'status':'SYNTHETIC_CANDIDATE_NOT_SEALED','sealed':False,'dataset':'0051-upgraded-T26-synthetic',
        'project':project,'app_image_id':app_id,'app_sha':candidate['runs'][-1]['app_sha']}
    with tempfile.TemporaryDirectory(prefix=project+'-') as temporary:
        path=Path(temporary); dbdir=path/'db'; dbdir.mkdir(); dbpath=dbdir/'synthetic.sqlite3'
        with sqlite3.connect('file:'+str(dataset/'synthetic.sqlite3')+'?mode=ro',uri=True) as src, sqlite3.connect(dbpath) as dst:
            src.backup(dst)
        tls=path/'tls'; tls.mkdir()
        run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-keyout',str(tls/'key.pem'),
             '-out',str(tls/'cert.pem'),'-subj','/CN=publisher.example','-addext','subjectAltName=DNS:publisher.example,DNS:zero.publisher.example'])
        pgurl='postgres://rss_contract:synthetic-t26-only@rss-db/rss_contract?sslmode=disable'
        services={
            'rss-db':{'image':pg_image,'environment':{'POSTGRES_DB':'rss_contract','POSTGRES_USER':'rss_contract',
                'POSTGRES_PASSWORD':'synthetic-t26-only'},'volumes':['rss-pg-data:/var/lib/postgresql/data'],
                'networks':['isolated'],'healthcheck':{'test':['CMD-SHELL','pg_isready -U rss_contract -d rss_contract'],'interval':'1s','retries':60}},
            'fixture':{'image':python_image,'command':['python','/fixture/server.py'],
                'volumes':[str(ROOT/'ops/rss/T09/publisher.py')+':/fixture/server.py:ro',str(tls)+':/fixture/tls:ro'],
                'networks':{'isolated':{'aliases':['publisher.example','zero.publisher.example']}}},
            'miniflux':{'image':engine_image,'depends_on':{'rss-db':{'condition':'service_healthy'}},
                'environment':{'DATABASE_URL':pgurl,'SSL_CERT_FILE':'/fixture-ca.pem','RUN_MIGRATIONS':'1','CREATE_ADMIN':'1','ADMIN_USERNAME':'synthetic_admin',
                    'ADMIN_PASSWORD':'synthetic-t26-admin','FETCHER_ALLOW_PRIVATE_NETWORKS':'1','POLLING_FREQUENCY':'999999','LOG_LEVEL':'error'},
                'ports':['127.0.0.1::8080'],'networks':['isolated'],'volumes':[str(tls/'cert.pem')+':/fixture-ca.pem:ro'],
                'healthcheck':{'test':['CMD','/usr/bin/miniflux','-healthcheck','auto'],'interval':'1s','retries':60}},
            'app':{'image':app_image,'entrypoint':['python','-c'],
                'command':["from wsgiref.simple_server import make_server; from newsaggregator.wsgi import application; make_server('127.0.0.1',9527,application).serve_forever()"],
                'environment':{'RUN_MAIN':'true','DJANGO_DB_PATH':'/var/lib/newshub/db/synthetic.sqlite3',
                    'DJANGO_SECRET_KEY':'synthetic-t26-app-only','DJANGO_SETTINGS_MODULE':'newsaggregator.settings'},
                'volumes':[str(dbdir)+':/var/lib/newshub/db'],'network_mode':'none'},
        }
        composepath=path/'compose.json'; composepath.write_text(json.dumps({'services':services,'volumes':{'rss-pg-data':{}},
            'networks':{'isolated':{'driver':'bridge'}}}))
        compose=['docker','compose','-p',project,'-f',str(composepath)]
        def call(*argv): return run(compose+list(argv)).stdout.strip()
        print('isolated T26 pair project:',project,flush=True)
        try:
            call('up','-d','--wait')
            port=call('port','miniflux','8080'); assert port.startswith('127.0.0.1:')
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            def api(route,data=None,user='synthetic_admin',password='synthetic-t26-admin'):
                auth=base64.b64encode((user+':'+password).encode()).decode()
                request=urllib.request.Request('http://'+port+'/v1/'+route,data=None if data is None else json.dumps(data).encode(),
                    headers={'Authorization':'Basic '+auth,'Content-Type':'application/json'})
                with opener.open(request,timeout=30) as response: return json.load(response)
            account=api('users',{'username':'synthetic_collector','password':'synthetic-t26-collector','is_admin':False})
            feed=api('feeds',{'feed_url':'https://publisher.example:8443/feed','crawler':False},'synthetic_collector','synthetic-t26-collector')
            entries=api('entries?order=id&direction=asc',user='synthetic_collector',password='synthetic-t26-collector')['entries']
            entry=entries[0]
            token=api('api-keys',{'description':'T26 restore reconcile'},'synthetic_collector','synthetic-t26-collector')['token']
            tokenpath=path/'synthetic-token'; tokenpath.write_text(token); tokenpath.chmod(0o600)
            # Fixture identity alignment before the restore point. This is NOT an
            # operational rebind workflow and is not included in upgrade invariants.
            call('stop','app')
            with sqlite3.connect(dbpath) as db:
                binding=db.execute('SELECT id,engine_instance_uuid FROM api_feedbinding').fetchone()
                instance=str(uuid.UUID(binding[1]))
                db.execute('UPDATE api_feedbinding SET account_id=?,engine_feed_id=?,canonical_feed_url=?',(account['id'],feed['feed_id'],'https://publisher.example:8443/feed'))
                db.execute('UPDATE api_engineentrymap SET engine_entry_id=?,source_url=?',(entry['id'],entry['url']))
                row=db.execute('SELECT id,full_content_provenance FROM api_news WHERE body_owner_binding_id IS NOT NULL').fetchone()
                provenance=json.loads(row[1]); provenance.update(engine_entry_id=entry['id'],engine_feed_id=feed['feed_id'],account_id=account['id'])
                db.execute('UPDATE api_news SET url=?,full_content_provenance=? WHERE id=?',(entry['url'],json.dumps(provenance),row[0]))
                migrations=[{'app':a,'name':n} for a,n in db.execute('SELECT app,name FROM django_migrations ORDER BY app,name')]
                counts={table:db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in (
                    'auth_user','api_news','api_channelsubscription','api_channelgroupmember','api_favorite','api_blockednews',
                    'api_readingday','api_newsreadstate','api_chatsession','api_researchsession','api_researchsearchresult',
                    'api_chatgptarticletranslation','api_sharedarticletranslation','api_legacytranslationsnapshot','api_newspreference',
                    'api_channelgroupingconfig','api_channelgroupingoverride','api_channelgroupingproposal','api_subscriptiongroupingstate',
                    'api_channelintakerequest','api_userprovidercredential','api_chatgptsubscriptionselection','api_feedstate')}
            call('start','app')
            pg_id=call('ps','-q','rss-db'); engine_id=call('ps','-q','miniflux'); app_container=call('ps','-q','app')
            pg_schema=int(run(['docker','exec',pg_id,'psql','-U','rss_contract','-d','rss_contract','-Atc','SELECT max(version) FROM schema_version']).stdout)
            manifest={'schema_version':1,'environment':'isolated','project':project,
                'release':{'schema_version':3,'release_sha':evidence['app_sha'],'image':app_image,'static_sha':static_sha,
                    'migrations':migrations,'capabilities':{'full_content_worker':True,'channel_worker':True}},
                'sqlite':{'path':str(dbpath)},'postgres':{'container_id':pg_id,'image':pg_image,'database':'rss_contract','user':'rss_contract','volume':project+'_rss-pg-data'},
                'engine':{'container_id':engine_id,'image':engine_image,'instance_uuid':instance,'account_id':account['id'],
                    'username':'synthetic_collector','schema_version':pg_schema},
                'writers':{'roles':{r:[app_container] if r=='app' else [] for r in rss.ROLES},'host_processes':[],
                    'schedulers':[],'host_inventory_complete':True},'other_containers':{'fixture':call('ps','-q','fixture')},
                'secret_refs':{},'rollback':None}
            manifestpath=path/'manifest.json'
            def operation(action,*arguments,value=None,ok=True):
                manifestpath.write_text(json.dumps(value or manifest))
                return run([args.python,str(ROOT/'scripts/rss/recovery.py'),action,'--environment','isolated',
                    '--manifest',str(manifestpath),'--target-project',project,*map(str,arguments)],ok=ok)
            first=path/'pair-before'
            assert operation('backup','--output',first,'--execute',ok=False).returncode==2
            operation('backup','--output',first,'--execute','--stop-writers')
            original=rss.load_pair(first,manifest)
            # Measured RPO: post-snapshot commits in BOTH DBs must disappear only
            # during this explicit disaster restore, never the app image roundtrip.
            with sqlite3.connect(dbpath) as db: db.execute("UPDATE api_news SET title='post-restore-point synthetic write' WHERE id=?",(row[0],))
            docker.sql(manifest,"UPDATE entries SET title='post-restore-point engine write';")
            prior=path/'pair-prior'; operation('backup','--output',prior,'--execute')
            before=(rss.sqlite_state(dbpath,manifest)['logical_sha256'],rss.pg_state(manifest,docker))
            bad=copy.deepcopy(manifest); bad['engine']['instance_uuid']=str(uuid.uuid4())
            assert operation('restore','--source',first,'--replace','--prior-backup',prior,'--execute',value=bad,ok=False).returncode==2
            assert before==(rss.sqlite_state(dbpath,manifest)['logical_sha256'],rss.pg_state(manifest,docker))
            restored=json.loads(operation('restore','--source',first,'--replace','--prior-backup',prior,'--execute').stdout)
            assert rss.sqlite_state(dbpath,manifest)['logical_sha256']==original['sqlite_logical_sha256']
            assert rss.pg_state(manifest,docker)==original['pg_logical_sha256']
            with sqlite3.connect(dbpath) as db:
                assert not db.execute('PRAGMA foreign_key_check').fetchall()
                for table,count in counts.items(): assert db.execute('SELECT count(*) FROM '+table).fetchone()[0]==count
            # Actual restored full application must read available/public and
            # paused/private data under its current ACL before any writer resume.
            code="""import django; django.setup()
from django.contrib.auth.models import User,AnonymousUser
from django.http import Http404
from api.models import News
from api.rss.access import get_stored_article
public=News.objects.get(body_owner_binding__isnull=False)
assert get_stored_article(AnonymousUser(),public.pk).markdown=='New short stored engine body.'
private=News.objects.get(title='private stored')
assert get_stored_article(User.objects.get(username='synthetic-a'),private.pk).scope=='full'
try:
 get_stored_article(User.objects.get(username='synthetic-b'),private.pk)
 raise AssertionError('restored personal leak')
except Http404: pass
print('restored available/ACL PASS')
"""
            checked=container(['docker','run','--rm','--network','none','--entrypoint','python','-e','RUN_MAIN=true',
                '-e','DJANGO_SETTINGS_MODULE=newsaggregator.settings','-e','DJANGO_DB_PATH=/var/lib/newshub/db/synthetic.sqlite3',
                '--mount','type=bind,source='+str(dbdir)+',target=/var/lib/newshub/db,readonly',app_id,'-c',code],'read-acl')
            assert rss.sqlite_state(dbpath,manifest)['logical_sha256']==original['sqlite_logical_sha256']
            call('up','-d','--wait','miniflux')
            synchronized=container(['docker','run','--rm','--network',project+'_isolated','--entrypoint','python',
                '-e','RUN_MAIN=true','-e','DJANGO_SETTINGS_MODULE=newsaggregator.settings',
                '-e','DJANGO_DB_PATH=/var/lib/newshub/db/synthetic.sqlite3','-e','RSS_ENGINE_INSTANCE_UUID='+instance,
                '-e','RSS_ENGINE_ACCOUNT_ID='+str(account['id']),'-e','RSS_ENGINE_BASE_URL=http://miniflux:8080',
                '-e','RSS_ENGINE_TOKEN_FILE=/run/secrets/t26-token',
                '--mount','type=bind,source='+str(dbdir)+',target=/var/lib/newshub/db',
                '--mount','type=bind,source='+str(tokenpath)+',target=/run/secrets/t26-token,readonly',
                '--mount','type=bind,source='+str(ROOT/'ops/rss/T26/reconcile_restored.py')+',target=/reconcile.py,readonly',
                app_id,'/reconcile.py'],'reconcile')
            call('stop','miniflux')
            evidence['restored_engine_reconciliation']=json.loads(synchronized.stdout)
            evidence.update(schema=migrations,static_sha256=static_sha,release_manifest_sha256=rss.value_digest(manifest['release']),engine_schema=pg_schema,postgres_image=pg_image,engine_image=engine_image,
                relationships=counts,paired_restore='PASS',restored_full_app_acl=checked.stdout.strip(),
                wrong_instance='REFUSED_WITHOUT_WRITES',active_app_writer='REFUSED',
                mapping_sha256=restored['mapping_sha256'],sqlite_logical_sha256=original['sqlite_logical_sha256'],
                pg_logical_sha256=original['pg_logical_sha256'],restore_points=original['restore_points'],
                synthetic_identity_alignment=True,production='NOT_RUN',restored_writers_remain_stopped=True)
        finally:
            call('down','--volumes','--remove-orphans')
        for resource in ('container','network','volume'):
            assert not run(['docker',resource,'ls','-aq' if resource=='container' else '-q','--filter','label=com.docker.compose.project='+project]).stdout.strip()
        assert not run(['docker','ps','-aq','--filter','label=org.newshub.rehearsal='+project]).stdout.strip()
        evidence['resources_removed']=True
    args.output.write_text(json.dumps(evidence,indent=2,sort_keys=True)+'\n')
    print('PASS: T03 paired restore of upgraded T26 data, actual full app ACL, explicit RPO and cleanup')


if __name__=='__main__': main()
