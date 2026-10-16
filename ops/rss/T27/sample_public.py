"""Bounded public sampling via real private-network-guarded Miniflux, never a crawler fallback."""
import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[3]
FEEDS = [
    ('native', 'Julia Evans', 'https://jvns.ca/atom.xml', 2),
    ('native', 'WebKit', 'https://webkit.org/feed/', 2),
    ('summary_blog', 'Martin Fowler', 'https://martinfowler.com/feed.atom', 2),
    ('summary_blog', 'Uber Engineering', 'https://www.uber.com/blog/engineering/rss/', 2),
    ('dev', 'DEV Community', 'https://dev.to/feed', 2),
    ('hn', 'Hacker News', 'https://news.ycombinator.com/rss', 5),
]

def run(args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=180, **kwargs)

def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--supplement-github', action='store_true')
    parser.add_argument('--manual-repeat', action='store_true')
    parser.add_argument('--retain-bodies', type=Path); args = parser.parse_args()
    assert not (args.supplement_github and args.manual_repeat)
    if args.manual_repeat:
        assert args.retain_bodies and str(args.retain_bodies).startswith('/tmp/newshub-rss-t27-quality-')
        args.retain_bodies.mkdir(mode=0o700, parents=False, exist_ok=False)
    selected_feeds = [('summary_blog', 'GitHub Blog', 'https://github.blog/feed/', 1)] if args.supplement_github else FEEDS
    repeat_urls = {'Julia Evans':'https://jvns.ca/blog/2024/11/18/how-to-import-a-javascript-library/', 'Martin Fowler':'https://martinfowler.com/articles/orchestrator-tax.html'}
    if args.manual_repeat:
        selected_feeds = [(kind,name,url,1) for kind,name,url,_ in FEEDS if name in repeat_urls]
    endpoint = (None if os.environ.get('DOCKER_CONTEXT') else os.environ.get('DOCKER_HOST')) or run(['docker','context','inspect','--format','{{.Endpoints.docker.Host}}']).stdout.strip()
    assert endpoint.startswith('unix://')
    project='newshub-rss-t27-public-'+uuid.uuid4().hex[:10]
    for kind in ('container','network','volume'):
        command=['docker','ps','-aq'] if kind=='container' else ['docker',kind,'ls','-q']
        assert not run(command+['--filter','label=com.docker.compose.project='+project]).stdout.strip()
    with tempfile.TemporaryDirectory(prefix=project+'-') as folder:
        state=Path(folder);state.chmod(0o700)
        overlay={'services':{'guarded':{'environment':{'HTTP_CLIENT_TIMEOUT':'10'},'healthcheck':{'test':['CMD','/usr/bin/miniflux','-healthcheck','auto'],'interval':'1s','timeout':'5s','retries':60}}}}
        path=state/'overlay.json';path.write_text(json.dumps(overlay))
        compose=['docker','compose','-p',project,'-f',str(ROOT/'ops/rss/T00/compose.yaml'),'-f',str(path)]
        def call(*args):return run(compose+list(args)).stdout.strip()
        evidence={'project':project,'feeds':[],'private_network_guard':True,'sample_limits':({'native':1,'summary_blog':1} if args.manual_repeat else {'summary_blog':1} if args.supplement_github else {'native':4,'summary_blog':4,'dev':2,'hn':5}),'tested_sha':run(['git','rev-parse','HEAD'],cwd=ROOT).stdout.strip()}
        try:
            call('up','-d','--wait','guarded')
            address=call('port','guarded','8080');assert address.startswith('127.0.0.1:')
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            def api(path,data,user,password):
                request=urllib.request.Request('http://'+address+'/v1/'+path,data=json.dumps(data).encode(),headers={'Content-Type':'application/json','Authorization':'Basic '+base64.b64encode((user+':'+password).encode()).decode()})
                with opener.open(request,timeout=30) as response:return json.load(response)
            user=api('users',{'username':'t27_samples','password':'synthetic-public-samples','is_admin':False},'t00_admin','synthetic-t00-admin');assert user['id']==2
            token=api('api-keys',{'description':'isolated bounded public samples'},'t27_samples','synthetic-public-samples')['token']
            import sys
            sys.path.insert(0,str(ROOT/'backend'))
            from api.rss.engine import EngineAdapter,EngineConfig,EngineError
            from api.rss.content import convert_html
            from bs4 import BeautifulSoup
            from urllib.parse import urlsplit
            config=EngineConfig(str(uuid.uuid4()),2,'http://'+address,token,control_timeout=20,read_timeout=10,read_attempts=1,full_content_enabled=True)
            adapter=EngineAdapter(config)
            for kind,name,url,limit in selected_feeds:
                row={'class':kind,'name':name,'feed_url':url,'sample_limit':limit,'entries':[],'mode':'feed','full_content_gate_enabled':True}
                started=time.monotonic()
                print('sampling',name,flush=True)
                try:
                    previous=adapter.read_upper_bound()
                    feed=adapter.create_feed(url,desired_mode='feed',disabled=False)
                    row['feed_id']=str(feed.id);row['feed_elapsed_seconds']=round(time.monotonic()-started,3)
                    upper=adapter.read_upper_bound()
                    entries=adapter.list_entries(previous,upper,limit=100)
                    entries=[entry for entry in entries if entry.feed_id==feed.id]
                    row['observed_feed_entries']=len(entries)
                    def subtype(entry):
                        host=urlsplit(entry.url).hostname or ''
                        if host in {'github.com','www.github.com'}:return 'github'
                        if host in {'youtube.com','www.youtube.com','youtu.be','vimeo.com'}:return 'video'
                        if host=='news.ycombinator.com':return 'self_post'
                        return 'article'
                    selected=[]
                    if kind=='hn':
                        for subtype_name in ['article','github','video','self_post']:
                            match=next((entry for entry in entries if subtype(entry)==subtype_name),None)
                            if match:selected.append(match)
                        row['subtypes_missing']=[name for name in ['article','github','video','self_post'] if not any(subtype(entry)==name for entry in selected)]
                    elif args.manual_repeat:selected=[entry for entry in entries if entry.url==repeat_urls[name]][:1]
                    else:selected=entries[:limit]
                    for entry in selected[:limit]:
                        item={'id':str(entry.id),'url':entry.url,'title':entry.title,'published_at':entry.published_at,'scope':'feed_content','subtype':subtype(entry),'manual_completeness':'not_confirmed'}
                        raw=entry.content
                        before=convert_html(raw,base_url=entry.url)
                        item.update(feed_html_chars=len(raw),feed_markdown_chars=len(before.markdown),feed_canonical_hash=before.canonical_hash)
                        if kind!='native' and item['subtype']=='article':
                            started=time.monotonic()
                            try:
                                entry=adapter.refetch_entry(entry.id)
                                item['extraction_elapsed_seconds']=round(time.monotonic()-started,3)
                                item['scope']='engine_extracted_unknown'
                            except EngineError as error:
                                item['extraction_error']=error.code
                                item['extraction_elapsed_seconds']=round(time.monotonic()-started,3)
                        converted=convert_html(entry.content,base_url=entry.url)
                        soup=BeautifulSoup(entry.content,'html.parser')
                        item.update(markdown_chars=len(converted.markdown),canonical_hash=converted.canonical_hash,nonempty_readable=bool(converted.markdown.strip()),
                            pre_blocks=len(soup.find_all('pre')),tables=len(soup.find_all('table')),images=len(soup.find_all('img')),
                            heading_count=len(soup.find_all(['h1','h2','h3','h4'])))
                        if args.manual_repeat:
                            slug = 'julia' if name=='Julia Evans' else 'fowler'
                            retained = args.retain_bodies / (slug+'-engine.html')
                            retained.write_text(entry.content); retained.chmod(0o600)
                            (args.retain_bodies / (slug+'-engine.md')).write_text(converted.markdown)
                            item['retained_body_file'] = retained.name
                        row['entries'].append(item)
                    row['status']='sampled' if row['entries'] else 'no_entries'
                except Exception as error:
                    row.update(status='failed',error=getattr(error,'code',type(error).__name__),elapsed_seconds=round(time.monotonic()-started,3))
                evidence['feeds'].append(row)
                args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
            adapter.close()
        finally:
            call('down','--volumes','--remove-orphans');assert not call('ps','-aq')
            for resource in ('network','volume'):
                assert not run(['docker',resource,'ls','-q','--filter','label=com.docker.compose.project='+project]).stdout.strip()
            evidence['resources_removed']=True
            args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'project':project,'statuses':{row['name']:row['status'] for row in evidence['feeds']},'resources_removed':True}))
if __name__=='__main__':main()
