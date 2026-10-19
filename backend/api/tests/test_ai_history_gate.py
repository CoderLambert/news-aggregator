"""No-DB checks for explicit owner-history opt-in and terminal source fences."""
from types import SimpleNamespace as N
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate

from api.ai_connection_views import ConnectionView
from api.ai_translation_views import TranslationView
from api.ai_usage_views import AIUsageView
from api.services import ai_private_translation as translation


@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=False, AI_BYOK_ENABLED=False)
class AIHistoryGateTests(SimpleTestCase):
    def response(self, base, method='get', *, authenticated=True):
        class Probe(base):
            def get(self, request):
                return Response(status=204)

            post = get

        request = getattr(APIRequestFactory(), method)('/synthetic-history/')
        if authenticated:
            force_authenticate(request, user=N(pk=7, is_authenticated=True, is_active=True))
        return Probe.as_view()(request)

    def test_only_explicit_history_get_views_bypass_disabled_byok(self):
        for base in (TranslationView, AIUsageView):
            with self.subTest(view=base):
                response = self.response(base)
                self.assertEqual(response.status_code, 204)
                self.assertEqual(response['Cache-Control'], 'private, no-store')
                self.assertEqual(self.response(base, 'post').status_code, 403)
                self.assertEqual(self.response(base, authenticated=False).status_code, 403)
        self.assertEqual(self.response(ConnectionView).status_code, 403)

    def test_public_read_only_site_keeps_its_original_gate(self):
        with override_settings(PUBLIC_SITE_MODE='read_only'):
            self.assertEqual(self.response(TranslationView).status_code, 403)
            self.assertEqual(self.response(AIUsageView).status_code, 403)

    def task(self, status='succeeded'):
        stored = N(news_id=1, title='Synthetic', summary='', scope='full', revision=1,
                   canonical_hash='synthetic-hash', provenance={}, policy_versions={}, markdown='body')
        task = N(status=status, user=N(is_active=True), user_id=7, news=N(),
                 api_connection_id='synthetic', api_connection=N(user_id=7),
                 execution_snapshot={'article': translation._identity(stored), 'markdown': 'body'})
        return task, stored

    def test_terminal_history_keeps_owner_and_source_fences_when_ai_is_off(self):
        for status in ('succeeded', 'failed', 'cancelled', 'interrupted'):
            with self.subTest(status=status):
                task, stored = self.task(status)
                with patch.object(translation, 'article_snapshot', return_value=stored), \
                     patch.object(translation, 'require_current'):
                    self.assertIs(translation._readable(task), task)
                    task.api_connection.user_id = 8
                    with self.assertRaises(translation.TranslationError):
                        translation._readable(task)
                    task.api_connection.user_id = 7
                    stored.revision = 2
                    with self.assertRaises(translation.TranslationError):
                        translation._readable(task)

    def test_active_task_still_requires_enabled_execution(self):
        task, _stored = self.task('running')
        with self.assertRaises(translation.TranslationError):
            translation._readable(task)
