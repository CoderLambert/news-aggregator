"""AG-02: source-name collisions must not lend another publisher's titles."""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from api.models import Category, ChannelSubscription, News, NewsSourceItem, Source
from api.services.channel_grouping import make_proposal
from api.services.channel_topics import channel_articles, evidence_for, profile_data


@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=False)
class TrustedArticleEvidenceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('ag02-evidence-owner')
        self.impostor = Source.objects.create(
            name='React Blog', url='https://react.dev.attacker.invalid', language='en')
        self.publisher = Source.objects.create(
            name='Unrelated Feed', url='https://independent.example', language='en')
        self.category = Category.objects.create(name='AG02 article', slug='ag02-article')
        ChannelSubscription.objects.create(user=self.user, source=self.impostor)
        for index, title in enumerate((
            'React server components in the browser',
            'TypeScript language services for applications',
            'CSS grid browser rendering improvements',
            'React compiler for components',
        )):
            news = News.objects.create(
                source=self.publisher, category=self.category, title=title,
                url=f'https://independent.example/story/{index}', content='Summary',
                publish_time=timezone.now() - timedelta(minutes=index))
            # Legacy source attribution is real but does not authenticate a
            # new Source row sharing the same display name.
            NewsSourceItem.objects.create(
                news=news, source_key='react_blog', upstream_id=f'ag02-{index}',
                discovery_url=f'https://react.dev/blog/{index}')

    def test_impostor_name_cannot_borrow_titles_or_rule_confidence(self):
        self.assertEqual(profile_data(self.impostor)['origin'], 'unknown')
        self.assertEqual(list(channel_articles(self.impostor)), [])
        self.assertEqual(evidence_for(self.impostor)['titles'], [])
        with patch('socket.socket.connect', side_effect=AssertionError('not an online classifier')):
            proposal = make_proposal(self.user, {
                'source_ids': [self.impostor.pk], 'topic_keys': ['frontend'],
            })
        result = proposal.result[0]
        self.assertEqual(result['topic_keys'], [])
        self.assertEqual(result['origin'], 'unknown')
        self.assertTrue(result['needs_review'])

    def test_verified_publisher_can_use_its_own_versioned_attribution(self):
        self.impostor.url = 'https://react.dev'
        self.impostor.save(update_fields=['url'])
        self.assertEqual(channel_articles(self.impostor).count(), 4)
        self.assertEqual(len(evidence_for(self.impostor)['titles']), 4)
        self.assertEqual(profile_data(self.impostor)['origin'], 'catalog')
        self.assertEqual(profile_data(self.impostor)['topics'], ['frontend'])

    def test_publisher_identity_change_invalidates_earlier_rule_proposal(self):
        self.impostor.url = 'https://react.dev'
        self.impostor.save(update_fields=['url'])
        proposed = make_proposal(self.user, {
            'source_ids': [self.impostor.pk], 'topic_keys': ['frontend'],
        })
        self.impostor.url = 'https://react.dev.attacker.invalid'
        self.impostor.save(update_fields=['url'])
        from api.services.channel_grouping import apply_proposal, GroupingConflict
        with self.assertRaises(GroupingConflict):
            apply_proposal(self.user, proposed.pk, {
                'groups': [{'topic_key': 'frontend', 'source_ids': [self.impostor.pk]}],
            })
