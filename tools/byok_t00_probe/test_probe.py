"""Self-tests for the probe's safety evaluators (standard-library unittest only)."""

import json
import unittest
from unittest.mock import patch

from probe import (
    EXPECTED_IMAGES,
    add_check,
    container_image_evidence,
    credential_record_passes,
    dispatch_synthetic_tool,
    eof_integrity_passes,
    missing_provider_fails_closed,
    responses_foreign_id_normalization_passes,
    _stream_expectation,
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


class ContainerImageEvidenceTests(unittest.TestCase):
    def _run_fixture(self, mismatch=False):
        services = list(EXPECTED_IMAGES)
        containers = {}
        ids = []
        for service in services:
            container_id = "container-" + service
            image_id = "sha256:config-id-db" if service == "db" else "sha256:config-id-litellm"
            ids.append(container_id)
            containers[container_id] = (
                image_id,
                EXPECTED_IMAGES[service],
            )

        def fake_compose(_project, *args, **_kwargs):
            if args[:2] == ("ps", "-q"):
                return "\n".join(ids)
            raise AssertionError("unexpected compose call")

        runtime_ids = {
            image_id: service
            for service, (image_id, _config_image) in (
                (name, containers["container-" + name]) for name in services
            )
        }

        def fake_docker(args, **_kwargs):
            if args[0] == "inspect":
                rows = []
                for container_id in args[3:]:
                    image_id, config_image = containers[container_id]
                    service = container_id.removeprefix("container-")
                    rows.append(
                        f"{container_id}|{image_id}|{config_image}|{service}"
                    )
                return "\n".join(rows)

            if args[:2] == ["image", "inspect"]:
                reference = args[-1]
                if reference in runtime_ids:
                    service = runtime_ids[reference]
                    image_id = reference
                    repo_digests = []
                else:
                    service = next(
                        name for name, pinned in EXPECTED_IMAGES.items()
                        if pinned == reference
                    )
                    image_id = containers["container-" + service][0]
                    if mismatch and service == "db":
                        image_id = "sha256:different-image-id"
                    repo_digests = [reference]
                return image_id + "|" + json.dumps(repo_digests)

            raise AssertionError("unexpected Docker command")

        with patch("probe.compose", side_effect=fake_compose), patch(
            "probe.docker", side_effect=fake_docker
        ):
            return container_image_evidence("t00-unit-project")

    def test_records_container_and_image_inspect_evidence(self):
        evidence, passed = self._run_fixture()
        self.assertTrue(passed)
        db = evidence["db"]
        self.assertEqual(db["container_image_id"], "sha256:config-id-db")
        self.assertEqual(db["runtime_image_inspect_id"], "sha256:config-id-db")
        self.assertEqual(db["fixed_reference_resolved_image_id"], "sha256:config-id-db")
        self.assertEqual(db["container_config_image"], EXPECTED_IMAGES["db"])
        self.assertEqual(db["runtime_repo_digests"], [])
        self.assertEqual(db["fixed_reference_repo_digests"], [EXPECTED_IMAGES["db"]])
        self.assertNotEqual(db["container_image_id"], EXPECTED_IMAGES["db"].rsplit("@", 1)[-1])

    def test_fixed_reference_must_resolve_to_runtime_image_id(self):
        evidence, passed = self._run_fixture(mismatch=True)
        self.assertFalse(passed)
        self.assertFalse(evidence["db"]["fixed_reference_resolves_to_runtime_id"])
        # The manifest digest and config/image ID are different kinds of identifier.
        self.assertNotEqual(
            evidence["db"]["container_image_id"],
            EXPECTED_IMAGES["db"].rsplit("@", 1)[-1],
        )


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


class NativeStreamingEvaluatorTests(unittest.TestCase):
    def test_responses_failed_event_is_a_surfaced_sse_error(self):
        self.assertTrue(_stream_expectation("responses", "SSE_ERROR", {
            "success": True,
            "event_types": ["response.created", "response.failed"],
            "terminals": [],
        }))

    def test_incomplete_response_is_not_a_complete_terminal(self):
        self.assertTrue(_stream_expectation("responses", "INCOMPLETE", {
            "success": True,
            "event_types": ["response.created", "response.incomplete"],
            "terminals": ["incomplete"],
        }))

    def test_cancel_requires_close_disconnect_and_resource_release(self):
        outcome = {
            "success": True,
            "outcome": "cancelled",
            "stream_complete": False,
            "event_count": 1,
            "canceled_after_first_event": True,
            "terminals": [],
            "client_response_closed": True,
            "upstream_disconnect_within_observation_window": True,
            "upstream_producer_exited_within_observation_window": True,
            "active_upstream_producers_at_observation_end": 0,
            "proxy_liveness_http_2xx_after_cancel": True,
            "upstream_stream_body_finished": False,
        }
        self.assertTrue(_stream_expectation("messages", "CANCEL", outcome))
        outcome["event_count"] = 2
        self.assertFalse(_stream_expectation("messages", "CANCEL", outcome))

    def test_cancel_fails_when_upstream_keeps_running_or_returns_complete(self):
        self.assertFalse(_stream_expectation("messages", "CANCEL", {
            "success": True,
            "outcome": "cancelled",
            "stream_complete": True,
            "event_count": 1,
            "canceled_after_first_event": True,
            "terminals": [],
            "client_response_closed": True,
            "upstream_disconnect_within_observation_window": False,
            "upstream_producer_exited_within_observation_window": False,
            "active_upstream_producers_at_observation_end": 1,
            "proxy_liveness_http_2xx_after_cancel": True,
            "upstream_stream_body_finished": True,
        }))


class ResponsesForeignIdNormalizationTests(unittest.TestCase):
    def test_foreign_item_id_may_normalize_but_call_association_must_survive(self):
        facts = {
            f"responses_r{round_index}_{suffix}": True
            for round_index in (1, 2)
            for suffix in (
                "reasoning_id_preserved",
                "reasoning_summary_preserved",
                "encrypted_continuation_preserved",
                "reasoning_keyset_preserved",
                "non_id_function_call_fields_preserved",
                "foreign_item_id_normalized",
                "foreign_call_id_and_tool_association_preserved",
                "tool_result_preserved",
            )
        }
        self.assertTrue(responses_foreign_id_normalization_passes(facts))
        facts["responses_r2_tool_result_preserved"] = False
        self.assertFalse(responses_foreign_id_normalization_passes(facts))


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


class ToolDispatchGateTests(unittest.TestCase):
    def test_allowlisted_complete_arguments_use_only_local_stub(self):
        self.assertEqual(
            dispatch_synthetic_tool("lookup_weather", '{"city":"synthetic-city"}'),
            ("dispatched", "synthetic-weather"),
        )

    def test_partial_json_is_rejected_before_dispatch(self):
        self.assertEqual(
            dispatch_synthetic_tool("lookup_weather", '{"city":'),
            ("partial_json", None),
        )

    def test_invalid_json_is_rejected_before_dispatch(self):
        self.assertEqual(
            dispatch_synthetic_tool("lookup_weather", "{not-json}"),
            ("invalid_json", None),
        )

    def test_non_allowlisted_tool_is_rejected_before_dispatch(self):
        self.assertEqual(
            dispatch_synthetic_tool("delete_everything", '{"confirm":true}'),
            ("not_allowlisted", None),
        )

    def test_messages_tool_input_must_be_a_valid_object(self):
        self.assertEqual(
            dispatch_synthetic_tool("lookup_weather", ["not", "an", "object"]),
            ("invalid_argument_shape", None),
        )


if __name__ == "__main__":
    unittest.main()
