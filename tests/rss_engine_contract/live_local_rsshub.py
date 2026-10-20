"""Opt-in real local RSSHub / Miniflux proof with synthetic users and DB only."""
import json,os,time,uuid,ssl,urllib.request,urllib.error
from pathlib import Path

def main():
    if os.environ.get('RSSHUB_LIVE')!='synthetic-isolated':raise RuntimeError('explicit isolated opt-in required')
    data=Path('/lab')
    if not (data/'synthetic-lab.marker').exists():raise RuntimeError('synthetic marker required')
    import django;django.setup()
    from django.conf import settings
    from django.core.management import call_command
    from django.contrib.auth import get_user_model
    import miniflux
    from api.models import Category,News,ChannelSubscription
    from api.rss.subscriptions import subscribe
    from api.rss.engine import EngineConfig
    from api.rss.control_worker import ControlWorker
    from api.rss.reconciliation import SyncWorker
    from api.rss.models import FeedBinding,FeedOperation
    from api.services.channel_articles import category_filter
    from api.rss.access import authorized_news
    call_command('migrate',verbosity=0)
    root=miniflux.Client('http://miniflux:8080',username='synthetic_admin',password='synthetic-proxy-lab-admin')
    collector=root.create_user('collector_'+uuid.uuid4().hex[:8],'synthetic-collector',is_admin=False)
    remote=miniflux.Client('http://miniflux:8080',username=collector['username'],password='synthetic-collector')
    token=remote.create_api_key('isolated local RSSHub')['token'];instance=str(uuid.uuid4());account=collector['id']
    os.environ['RSS_ENGINE_INSTANCE_UUID']=instance;os.environ['RSS_ENGINE_ACCOUNT_ID']=str(account)
    (data/'token').write_text(token);(data/'token').chmod(0o600)
    gateway=json.loads(Path('/work/ops/rss/local/gateway.json').read_text())
    settings.RSSHUB_GATEWAY=gateway;settings.PUBLIC_SITE_MODE='full';settings.RSS_FULL_CONTENT_ENABLED=False
    (data/'engine.json').write_text(json.dumps({'instance':instance,'account':account}));(data/'gateway.json').write_text(json.dumps(gateway))
    U=get_user_model();a=U.objects.create_user('rss-local-reader-a',password='synthetic-reader-only');b=U.objects.create_user('rss-local-reader-b',password='synthetic-reader-only')
    U.objects.create_superuser('rss-local-admin',password='synthetic-admin-only')
    ai,_=Category.objects.get_or_create(name='人工智能',defaults={'slug':'ai'})
    config=EngineConfig(instance,account,'http://miniflux:8080',token,read_attempts=1,control_timeout=35,full_content_enabled=False)
    worker=ControlWorker(config,max_attempts=1);sync=SyncWorker(worker,config,incremental_seconds=0,reconcile_seconds=0)
    def until(predicate):
        end=time.monotonic()+90
        while not predicate():
            if time.monotonic()>end:raise AssertionError('isolated workflow timed out')
            worker.tick();sync.tick();time.sleep(.03)
    try:
        _,first=subscribe(a,{'feed_url':'rsshub://github/issue/DIYgod/RSSHub/open','category_id':ai.pk},'local-alias')
        until(lambda:ChannelSubscription.objects.filter(user=a).exists() and News.objects.filter(source_id=first['source_id']).exists())
        news=News.objects.filter(source_id=first['source_id']).first();binding=FeedBinding.objects.get()
        assert binding.published_since is not None
        assert all(n.publish_time.date()>=binding.published_since for n in News.objects.filter(source_id=first['source_id']))
        assert not authorized_news(b).filter(pk=news.pk).exists()
        assert category_filter(authorized_news(a),[ai.pk],actor=a).filter(pk=news.pk).exists()
        _,second=subscribe(b,{'feed_url':'https://rsshub.newshub.example/github/issue/DIYgod/RSSHub/open'},'local-https')
        until(lambda:ChannelSubscription.objects.filter(user=b).exists())
        assert first['source_id']==second['source_id'] and len(remote.get_feeds())==1
        assert not category_filter(authorized_news(b),[ai.pk],actor=b).filter(pk=news.pk).exists()
        feed=remote.get_feed(binding.engine_feed_id)
        assert feed['proxy_url']=='http://rsshub-proxy:3128' and feed['crawler'] is False
        # The trusted hop cannot be selected by ordinary feeds, and refuses all other destinations.
        negatives={}
        for name,url,options,reason in [
            ('native_private_blocked','http://rsshub:1200/github/issue/DIYgod/RSSHub/open',{},'refusing to access private network host'),
            ('proxy_other_host_blocked','https://example.com/feed',{'proxy_url':'http://rsshub-proxy:3128'},'Forbidden'),
            ('gateway_unapproved_path_blocked','https://rsshub.newshub.example/twitter/user/elonmusk',{'proxy_url':'http://rsshub-proxy:3128'},'403 status code'),
            ('upstream_redirect_blocked','https://rsshub.newshub.example/github/issue/DIYgod/RSSHub/closed',{'proxy_url':'http://rsshub-proxy:3128'},'502 status code'),
        ]:
            try: remote.create_feed(url,**options)
            except miniflux.ServerError as exc:
                assert reason in str(exc),name+": unexpected error (not a verified denial)"
                negatives[name]=True
            else:raise AssertionError(name)
        assert len(remote.get_feeds())==1
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({'https':'http://rsshub-proxy:3128'}),urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile='/tls/ca-bundle.pem')))
        try:opener.open('https://rsshub.newshub.example/github/issue/DIYgod/RSSHub/closed',timeout=10)
        except urllib.error.HTTPError as exc:assert exc.code==502
        else:raise AssertionError('redirect was followed')
        out={'scope':'real RSSHub GitHub + real Miniflux2.3.3; synthetic users/DB','alias_https_single_feed':True,'article_count':News.objects.filter(source_id=first['source_id']).count(),
            'published_since':str(binding.published_since),'personal_category_owner_isolation':True,'feed_only':True,**negatives,'twitter':'SKIPPED at user request','instance':instance,'account':account,'source_id':first['source_id']}
        (data/'results.json').write_text(json.dumps(out,ensure_ascii=False,indent=2));print(json.dumps(out,ensure_ascii=False))
    finally:sync.close();worker.close()
if __name__=='__main__':main()
