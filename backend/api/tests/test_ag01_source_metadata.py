"""AG-01: public source evidence must be versioned, trusted and side-effect free."""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import Source, ChannelGroup, ChannelGroupMember, ChannelSubscription
from api.rss.models import SourcePublication
from api.smart_channel_models import SourceTopicProfile, ChannelGroupingConfig
from api.services.channel_grouping import process_subscription
from api.services.channel_topics import (
    PROFILE_EVIDENCE_VERSION, TAXONOMY_VERSION, base_profile, profile_data, refresh_profiles,
)


@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=False)
class SourceMetadataContractTests(TestCase):
    def setUp(self):
        self.source, _ = Source.objects.get_or_create(
            name='React Blog', defaults={'url': 'https://react.dev', 'language': 'en'},
        )
        self.source.url = 'https://react.dev'
        self.source.language = 'en'
        self.source.description = ''
        self.source.save(update_fields=['url', 'language', 'description'])
        self.owner = get_user_model().objects.create_user('ag01-owner')
        self.other = get_user_model().objects.create_user('ag01-other')

    def _manual(self):
        return SourceTopicProfile.objects.update_or_create(
            source=self.source, defaults={
                'about': 'Verified by an editor', 'topics': ['frontend'],
                'origin': 'manual', 'evidence_hash': base_profile(self.source)['evidence_hash'],
            },
        )[0]

    def test_publisher_name_alone_never_confers_trusted_topics(self):
        trusted = profile_data(self.source)
        self.assertEqual(trusted['topics'], ['frontend'])
        self.assertFalse(trusted['needs_review'])
        self.assertEqual(trusted['metadata_status'], 'trusted')
        self.assertEqual(trusted['evidence_version'], PROFILE_EVIDENCE_VERSION)
        self.assertEqual(trusted['taxonomy_version'], TAXONOMY_VERSION)

        original = trusted['evidence_hash']
        self.source.url = 'https://react.dev.attacker.invalid'
        self.source.save(update_fields=['url'])
        untrusted = profile_data(self.source)
        self.assertEqual(untrusted['topics'], [])
        self.assertTrue(untrusted['needs_review'])
        self.assertEqual(untrusted['origin'], 'unknown')
        self.assertNotEqual(original, untrusted['evidence_hash'])
        self.assertFalse(SourceTopicProfile.objects.exists())

    def test_publisher_metadata_and_directory_revisions_invalidate_evidence(self):
        previous = base_profile(self.source)['evidence_hash']
        self.source.language = 'zh'
        self.source.save(update_fields=['language'])
        after_language = base_profile(self.source)['evidence_hash']
        self.assertNotEqual(previous, after_language)
        publication, _ = SourcePublication.objects.get_or_create(source=self.source)
        publication.display_name = 'A new editorial name'
        publication.save(update_fields=['display_name'])
        self.source.refresh_from_db()
        self.assertNotEqual(after_language, base_profile(self.source)['evidence_hash'])

    def test_stale_manual_topics_are_retained_but_not_auto_applied(self):
        profile = self._manual()
        group = ChannelGroup.objects.create(user=self.owner, name='My frontend')
        subscription = ChannelSubscription.objects.create(user=self.owner, source=self.source)
        ChannelGroupingConfig.objects.create(user=self.owner, mode='auto',
            bindings={'frontend': group.pk}, active_since=timezone.now() - timedelta(days=1))
        self.source.language = 'zh'
        self.source.save(update_fields=['language'])
        stale = profile_data(self.source)
        self.assertEqual(stale['topics'], ['frontend'])
        self.assertEqual(stale['origin'], 'manual')
        self.assertEqual(stale['metadata_status'], 'stale_manual')
        self.assertTrue(stale['needs_review'])
        process_subscription(subscription.pk)
        self.assertFalse(ChannelGroupMember.objects.filter(group=group, subscription=subscription).exists())
        profile.refresh_from_db()
        self.assertEqual(profile.revision, 1)

        admin = get_user_model().objects.create_superuser('ag01-admin', 'ag01@example.test', 'password')
        client = APIClient()
        client.force_authenticate(user=admin)
        response = client.patch(f'/api/smart-channels/sources/{self.source.pk}/',
            {'topics': ['frontend'], 'description': 'Verified by an editor'}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        profile.refresh_from_db()
        self.assertEqual(profile.revision, 2)
        self.assertEqual(profile.evidence_hash, base_profile(self.source)['evidence_hash'])
        self.assertFalse(profile_data(self.source)['needs_review'])

    def test_refresh_is_idempotent_and_recomputes_changed_identity(self):
        refresh_profiles(limit=10000)
        profile = SourceTopicProfile.objects.get(source=self.source)
        initial_hash, revision = profile.evidence_hash, profile.revision
        refresh_profiles(limit=10000)
        profile.refresh_from_db()
        self.assertEqual((profile.evidence_hash, profile.revision), (initial_hash, revision))
        self.source.description = 'Editorial scope updated'
        self.source.save(update_fields=['description'])
        refresh_profiles(limit=10000)
        profile.refresh_from_db()
        self.assertNotEqual(profile.evidence_hash, initial_hash)
        self.assertEqual(profile.revision, revision + 1)
        refresh_profiles(limit=10000)
        profile.refresh_from_db()
        self.assertEqual(profile.revision, revision + 1)

    def test_public_profile_change_does_not_touch_personal_group_memberships(self):
        self._manual()
        first = ChannelSubscription.objects.create(user=self.owner, source=self.source)
        second = ChannelSubscription.objects.create(user=self.other, source=self.source)
        group = ChannelGroup.objects.create(user=self.owner, name='Manual assignment')
        ChannelGroupMember.objects.create(group=group, subscription=first)
        old = profile_data(self.source)['evidence_hash']
        self.source.url = 'https://example.invalid/new-publisher'
        self.source.save(update_fields=['url'])
        self.assertNotEqual(old, profile_data(self.source)['evidence_hash'])
        self.assertEqual(list(group.subscriptions.all()), [first])
        self.assertEqual(ChannelSubscription.objects.filter(source=self.source).count(), 2)
        self.assertFalse(ChannelGroupMember.objects.filter(subscription=second).exists())

    def test_catalog_get_has_no_model_network_or_profile_writes(self):
        from api.tests.rss.legacy_fixtures import public_legacy
        public_legacy(self.source)
        client = APIClient()
        with (
            patch('api.services.channel_ai.personal_clients_for_user',
                  side_effect=AssertionError('GET invoked model')),
            patch('socket.socket.connect', side_effect=AssertionError('GET invoked network')),
        ):
            response = client.get('/api/smart-channels/catalog/')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(SourceTopicProfile.objects.count(), 0)
        self.assertIn('evidence_version', response.data['sources'][0])

    def test_schema_requires_no_parallel_metadata_table(self):
        call_command('makemigrations', 'api', check=True, dry_run=True, verbosity=0)
