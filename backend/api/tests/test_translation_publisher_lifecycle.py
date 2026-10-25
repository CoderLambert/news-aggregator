"""Deterministic transport lifecycle races; no DB, Redis or provider needed."""
from threading import Event, Thread
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from api.services import translation_channel as transport
from api.tests.translation_transport_fake import channel_factory


class PublisherLifecycleTests(unittest.TestCase):
    def finish_during_validation(self, *, validation_error=None, validation_seconds=0):
        entered, release, aborted = Event(), Event(), Event()
        clock = [10.0]
        errors = []

        def validate():
            entered.set()
            if not release.wait(5):
                raise AssertionError('test did not release control validation')
            clock[0] += validation_seconds
            if validation_error is not None:
                raise validation_error

        channel = channel_factory(transport)(1, 'synthetic-task', 1)
        publisher = None
        closer = None
        # Freeze only the transport clock, not threading's real wait deadlines.
        # A slow host must not turn this shutdown-race test into an expiry test.
        with patch.object(transport, 'time', SimpleNamespace(monotonic=lambda: clock[0])), \
                patch('django.db.close_old_connections'):
            publisher = transport.BufferedPublisher(channel, 'synthetic-run', validate, aborted.set)

            def finish():
                try:
                    publisher.__exit__(None, None, None)
                except Exception as error:
                    errors.append(error)

            try:
                publisher.__enter__()
                publisher.append('synthetic complete content')
                self.assertTrue(entered.wait(3), 'controller never entered validation')
                closer = Thread(target=finish, daemon=True)
                closer.start()
                self.assertTrue(publisher.stopped.wait(3), 'normal shutdown never requested stop')
                # The race is forced: validation finishes AFTER normal stop.
                release.set()
                closer.join(5)
                self.assertFalse(closer.is_alive(), 'publisher shutdown did not finish')
            finally:
                release.set()
                publisher.stopped.set()
                with publisher.condition:
                    publisher.condition.notify_all()
                for thread in (closer, publisher.publisher, publisher.controller):
                    if thread is not None and thread.ident is not None:
                        thread.join(5)
                        self.assertFalse(thread.is_alive(), 'test leaked a lifecycle thread')
        return publisher, aborted, errors, channel

    def test_normal_shutdown_during_successful_validation_does_not_fail(self):
        publisher, aborted, errors, channel = self.finish_during_validation()
        self.assertEqual(errors, [])
        self.assertFalse(publisher.failed.is_set())
        self.assertFalse(aborted.is_set())
        self.assertEqual(channel.read()['text'], 'synthetic complete content')
        # Transport is still only a draft; the separate fenced DB commit owns success.
        self.assertEqual(channel.read()['status'], 'running')

    def test_revocation_during_shutdown_still_fails_and_aborts(self):
        publisher, aborted, errors, _channel = self.finish_during_validation(
            validation_error=PermissionError('synthetic authority revoked'),
        )
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], transport.ChannelUnavailable)
        self.assertTrue(publisher.failed.is_set())
        self.assertTrue(aborted.is_set())

    def test_validation_deadline_is_not_relaxed_during_shutdown(self):
        publisher, aborted, errors, _channel = self.finish_during_validation(
            validation_seconds=1.01,
        )
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], transport.ChannelUnavailable)
        self.assertTrue(publisher.failed.is_set())
        self.assertTrue(aborted.is_set())

    def test_control_failure_diagnostics_never_log_exception_message(self):
        sensitive = 'sk-synthetic-private-key and private article contents'
        with self.assertLogs('api.services.translation_channel', level='WARNING') as captured:
            publisher, aborted, errors, _channel = self.finish_during_validation(
                validation_error=RuntimeError(sensitive),
            )
        self.assertTrue(publisher.failed.is_set())
        self.assertTrue(aborted.is_set())
        self.assertEqual(len(errors), 1)
        output = '\n'.join(captured.output)
        self.assertIn('RuntimeError', output)
        self.assertNotIn(sensitive, output)
        self.assertNotIn('sk-synthetic-private-key', output)

    def test_stale_authorization_still_fails_closed(self):
        channel = channel_factory(transport)(1, 'synthetic-task', 1)
        with patch.object(transport, 'time', SimpleNamespace(monotonic=lambda: 10.0)):
            publisher = transport.BufferedPublisher(channel, 'synthetic-run', lambda: None, lambda: None)
        with patch.object(transport, 'time', SimpleNamespace(monotonic=lambda: 12.01)):
            with self.assertRaises(transport.ChannelUnavailable):
                publisher.check()
