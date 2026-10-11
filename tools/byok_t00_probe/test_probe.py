"""Self-tests for the probe's safety evaluators (standard-library unittest only)."""

import unittest

from probe import (
    add_check,
    credential_record_passes,
    eof_integrity_passes,
    missing_provider_fails_closed,
)


def good_record(protocol="chat"):
    return {
        "tenant": "tenant-a",
        "expected_tenant": "tenant-a",
        "provider_key_match": True,
        "provider_auth_scheme": "x-api-key" if protocol == "messages" else "bearer",
        "wrong_provider_header_present": False,
        "project_key_match": False,
        "master_key_match": False,
        "admin_key_match": False,
        "deployment_default_match": False,
    }


class CredentialEvaluatorTests(unittest.TestCase):
    def test_openai_bearer_route_accepts_selected_tenant(self):
        self.assertTrue(credential_record_passes(good_record("chat"), "tenant-a", "chat"))

    def test_messages_x_api_key_route_accepts_selected_tenant(self):
        self.assertTrue(credential_record_passes(good_record("messages"), "tenant-a", "messages"))

    def test_wrong_tenant_is_detected_as_failure(self):
        record = good_record("chat")
        record["tenant"] = "tenant-b"
        record["provider_key_match"] = False
        self.assertFalse(credential_record_passes(record, "tenant-a", "chat"))

    def test_project_key_forwarding_is_detected_as_failure(self):
        record = good_record("chat")
        record["project_key_match"] = True
        self.assertFalse(credential_record_passes(record, "tenant-a", "chat"))

    def test_wrong_provider_auth_scheme_is_detected_as_failure(self):
        record = good_record("chat")
        record["provider_auth_scheme"] = "x-api-key"
        self.assertFalse(credential_record_passes(record, "tenant-a", "chat"))


class TerminalEvaluatorTests(unittest.TestCase):
    def test_missing_terminal_without_downstream_complete_is_safe(self):
        self.assertTrue(eof_integrity_passes("normal_eof_without_protocol_terminal", []))

    def test_wrong_synthetic_stop_for_incomplete_upstream_is_detected(self):
        self.assertFalse(
            eof_integrity_passes("normal_eof_without_protocol_terminal", ["stop"])
        )

    def test_complete_terminal_with_stop_is_allowed(self):
        self.assertTrue(eof_integrity_passes("finish_reason_stop", ["stop"]))


class MissingProviderEvaluatorTests(unittest.TestCase):
    def test_rejection_without_upstream_request_is_fail_closed(self):
        # No particular HTTP status is required for this result.
        self.assertTrue(missing_provider_fails_closed(False, []))

    def test_success_without_provider_key_is_rejected(self):
        self.assertFalse(missing_provider_fails_closed(True, []))

    def test_deployment_default_route_is_not_fail_closed(self):
        self.assertFalse(
            missing_provider_fails_closed(
                False,
                [{"tenant": "deployment-default", "deployment_default_match": True}],
            )
        )


class CheckOutputTests(unittest.TestCase):
    def test_false_evaluation_emits_fail(self):
        checks = []
        add_check(checks, "WRONG_RESULT", False, {"observed": "wrong"})
        self.assertEqual(checks[0]["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
