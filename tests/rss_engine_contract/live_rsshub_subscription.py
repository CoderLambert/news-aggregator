"""Explicit isolated engine acceptance; Twitter fixture is not real Twitter proof."""
import json,os,time,uuid
from pathlib import Path

def main():
 if os.environ.get('RSSHUB_LIVE')!='synthetic-isolated':raise RuntimeError('isolated opt-in required')
 data=Path('/lab')
 if not (data/'synthetic-lab.marker').is_file():raise RuntimeError('synthetic marker required')
 import django;django.setup()
 from django.conf import settings
 from django.core.management import call_command
 from django.contrib.auth import get_user_model
 from django.contrib.auth.models import AnonymousUser
 import miniflux
 from api.models import Category,News,ChannelSubscription
 from api.rss.subscriptions import subscribe
 from api.rss.models import FeedBinding,FeedOperation
 from api.rss.review_models import PublicFeedEntry,PublicFeedCandidate
 from api.rss.recommendations import submit_recommendation,decide_candidate
 from api.rss.review_permissions import change_reviewer
 from api.rss.access import authorized_news,get_stored_article
 from api.services.channel_articles import category_filter
 from api.rss.engine import EngineConfig
 from api.rss.control_worker import ControlWorker
 from api.rss.reconciliation import SyncWorker
 call_command('migrate',verbosity=0)
 root=miniflux.Client('http://engine:8080',username='synthetic_admin',password='synthetic-recovery-admin')
 collector=root.create_user('collector_'+uuid.uuid4().hex[:8],'synthetic-collector',is_admin=False)
 remote=miniflux.Client('http://engine:8080',username=collector['username'],password='synthetic-collector')
 token=remote.create_api_key('isolated rsshub')['token'];instance=str(uuid.uuid4());account=collector['id']
 os.environ['RSS_ENGINE_INSTANCE_UUID']=instance;os.environ['RSS_ENGINE_ACCOUNT_ID']=str(account)
 (data/'token').write_text(token);(data/'token').chmod(0o600)
 auth={'username':'synthetic-gateway','password':'synthetic-gateway-only'}
 (data/'gateway-auth.json').write_text(json.dumps(auth));(data/'gateway-auth.json').chmod(0o600)
 gateway={'enabled':True,'verified':True,'version':1,'origin':'https://fixture.example',
  'routes':['twitter.user','github.issue'],'repositories':[['DIYgod','RSSHub']],
  'capabilities':['twitter.public_only','config:TWITTER_AUTH_TOKEN'],'auth_file':'/lab/gateway-auth.json','auth_required':True}
 settings.RSSHUB_GATEWAY=gateway;settings.PUBLIC_SITE_MODE='full';settings.RSS_FULL_CONTENT_ENABLED=False
 (data/'engine.json').write_text(json.dumps({'instance':instance,'account':account}))
 (data/'gateway.json').write_text(json.dumps(gateway))
 U=get_user_model();a=U.objects.create_user('rss-reader-a',password='synthetic-reader-only');b=U.objects.create_user('rss-reader-b',password='synthetic-reader-only')
 admin=U.objects.create_superuser('rss-admin',password='synthetic-admin-only');reviewer=U.objects.create_user('rss-reviewer',password='synthetic-reviewer-only')
 ai,_=Category.objects.get_or_create(name='人工智能',defaults={'slug':'ai'});Category.objects.get_or_create(name='科技',defaults={'slug':'technology'})
 config=EngineConfig(instance,account,'http://engine:8080',token,read_attempts=1,control_timeout=35,full_content_enabled=False)
 worker=ControlWorker(config,max_attempts=1);sync=SyncWorker(worker,config,incremental_seconds=0,reconcile_seconds=0)
 def until(predicate):
  end=time.monotonic()+90
  while not predicate():
   if time.monotonic()>end:raise AssertionError('isolated workflow timed out')
   worker.tick();sync.tick();time.sleep(.02)
 try:
  _,first=subscribe(a,{'feed_url':'rsshub://twitter/user/elonmusk','category_id':ai.pk},'alias')
  until(lambda:ChannelSubscription.objects.filter(user=a).exists() and News.objects.filter(source_id=first['source_id']).exists())
  news=News.objects.get(source_id=first['source_id'])
  assert not authorized_news(b).filter(pk=news.pk).exists()
  assert category_filter(authorized_news(a),[ai.pk],actor=a).filter(pk=news.pk).exists()
  _,second=subscribe(b,{'feed_url':'https://fixture.example/twitter/user/elonmusk'},'https')
  until(lambda:ChannelSubscription.objects.filter(user=b).exists())
  assert first['source_id']==second['source_id'] and len(remote.get_feeds())==1 and FeedBinding.objects.count()==1
  assert not category_filter(authorized_news(b),[ai.pk],actor=b).filter(pk=news.pk).exists()
  recommendation=submit_recommendation(a,{'source_id':first['source_id'],'name':'Synthetic Twitter RSSHub','category_id':ai.pk,'language':'en','note':'Synthetic timeline, not real Twitter','confirm_public_scope':True},'recommend')
  change_reviewer(admin,reviewer.username,True,None,'grant')
  decide_candidate(reviewer,recommendation['candidate_id'],{'action':'approve','expected_version':recommendation['version'],'reason':''},'approve')
  until(lambda:PublicFeedEntry.objects.exists())
  assert get_stored_article(AnonymousUser(),news.pk).scope=='summary'
  output={'scope':'real isolated Miniflux2.3.3 with authenticated synthetic RSSHub gateway',
   'alias_connected':True,'alias_https_shared_feed_count':len(remote.get_feeds()),'private_before_publication':True,
   'owner_category_isolation':True,'public_review_published':True,'private_body_stays_private':True,
   'real_twitter':'NOT_RUN; no real Twitter credentials or gateway provided','instance':instance,'account':account,
   'source_id':first['source_id'],'category_id':ai.pk,'candidate_id':recommendation['candidate_id']}
  (data/'results.json').write_text(json.dumps(output,ensure_ascii=False,indent=2));print(json.dumps(output,ensure_ascii=False))
 finally:sync.close();worker.close()

if __name__=='__main__':main()
