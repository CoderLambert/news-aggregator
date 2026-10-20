"""Opt-in real isolated engine acceptance; only synthetic accounts and fixtures."""
import json
import os
from pathlib import Path
import time
import uuid


def main():
    if os.environ.get('RSS_REVIEW_LIVE')!='synthetic-isolated': raise RuntimeError('isolated opt-in required')
    data=Path(os.environ['RSS_REVIEW_LAB_DATA'])
    if not (data/'synthetic-lab.marker').is_file(): raise RuntimeError('synthetic data marker required')
    import django
    django.setup()
    from django.conf import settings
    from django.core.management import call_command
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import AnonymousUser
    from django.http import Http404
    import miniflux
    from api.models import Category, News, ChannelSubscription
    from api.rss.subscriptions import subscribe
    from api.rss.review_permissions import change_reviewer
    from api.rss.recommendations import submit_recommendation,decide_candidate
    from api.rss.public_membership import process_approved_candidates
    from api.rss.review_models import PublicFeedCandidate, PublicFeedEntry
    from api.rss.models import FeedOperation
    from api.rss.access import get_stored_article,authorized_news
    from api.rss.control_worker import ControlWorker
    from api.rss.reconciliation import SyncWorker
    from api.rss.engine import EngineConfig
    settings.PUBLIC_SITE_MODE='full'; settings.RSS_FULL_CONTENT_ENABLED=False
    call_command('migrate',verbosity=0)
    root=miniflux.Client('http://engine:8080',username='synthetic_admin',password='synthetic-recovery-admin')
    collector=root.create_user('collector_'+uuid.uuid4().hex[:8],'synthetic-collector',is_admin=False)
    remote=miniflux.Client('http://engine:8080',username=collector['username'],password='synthetic-collector')
    token=remote.create_api_key('isolated review')['token']
    instance=str(uuid.uuid4()); account=collector['id']
    os.environ['RSS_ENGINE_INSTANCE_UUID']=instance; os.environ['RSS_ENGINE_ACCOUNT_ID']=str(account)
    (data/'token').write_text(token); (data/'token').chmod(0o600)
    (data/'engine.json').write_text(json.dumps({'instance':instance,'account':account}))
    User=get_user_model()
    a=User.objects.create_user('rss-reader-a',password='synthetic-reader-only')
    b=User.objects.create_user('rss-reader-b',password='synthetic-reader-only')
    admin=User.objects.create_superuser('rss-admin',password='synthetic-admin-only')
    reviewer=User.objects.create_user('rss-reviewer',password='synthetic-reviewer-only')
    category=Category.objects.create(name='Synthetic review',slug='synthetic-review')
    config=EngineConfig(instance,account,'http://engine:8080',token,read_attempts=1,control_timeout=10,full_content_enabled=False)
    worker=ControlWorker(config,max_attempts=1); sync=SyncWorker(worker,config,incremental_seconds=0,reconcile_seconds=0)
    def until(predicate):
        deadline=time.monotonic()+60
        while not predicate():
            if time.monotonic()>deadline: raise AssertionError('isolated workflow timed out')
            worker.tick(); sync.tick(); time.sleep(.02)
    try:
        status,result=subscribe(a,{'feed_url':'https://fixture.example/self-service'},'personal')
        assert status==202
        until(lambda:ChannelSubscription.objects.filter(user=a).exists() and News.objects.filter(source_id=result['source_id']).exists())
        news=News.objects.filter(source_id=result['source_id']).first()
        assert len(remote.get_feeds())==1
        assert get_stored_article(a,news.pk).markdown
        for viewer in [b,AnonymousUser()]:
            assert not authorized_news(viewer).filter(pk=news.pk).exists()
            try: get_stored_article(viewer,news.pk)
            except Http404: pass
            else: raise AssertionError('personal article leaked')
        recommendation=submit_recommendation(a,{'source_id':result['source_id'],'name':'Synthetic shared feed','category_id':category.pk,'language':'en','note':'Synthetic public recommendation','confirm_public_scope':True},'recommend')
        change_reviewer(admin,reviewer.username,True,None,'grant')
        decision=decide_candidate(reviewer,recommendation['candidate_id'],{'action':'approve','expected_version':recommendation['version'],'reason':''},'approve')
        process_approved_candidates()
        until(lambda:PublicFeedEntry.objects.exists())
        candidate=PublicFeedCandidate.objects.get(pk=recommendation['candidate_id'])
        assert candidate.state=='published' and len(remote.get_feeds())==1
        assert authorized_news(b).filter(pk=news.pk).exists()
        assert get_stored_article(b,news.pk).scope=='summary'
        bad_status,bad=subscribe(b,{'feed_url':'https://fixture.example/invalid'},'invalid')
        assert bad_status==202
        until(lambda:FeedOperation.objects.filter(pk=bad['operation_id'],state='failed').exists())
        failed=FeedOperation.objects.get(pk=bad['operation_id'])
        assert failed.safe_result['code']=='feed_parse_failed' and failed.execution_phase=='final_response'
        assert not ChannelSubscription.objects.filter(user=b).exists()
        output={'scope':'real isolated Miniflux 2.3.3','personal_connected':True,'private_before_publication':True,
            'public_review_published':True,'shared_engine_feed_count':len(remote.get_feeds()),'public_members':PublicFeedEntry.objects.count(),
            'private_body_stays_private':True,'invalid_feed_error':failed.safe_result['code'],'instance':instance,'account':account,
            'candidate_id':str(candidate.pk),'public_source_id':candidate.public_source_id,'approval_version':decision['version']}
        (data/'results.json').write_text(json.dumps(output,ensure_ascii=False,indent=2))
        print(json.dumps(output,ensure_ascii=False))
    finally:
        sync.close(); worker.close()


if __name__=='__main__': main()
