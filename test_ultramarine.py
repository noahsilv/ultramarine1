import json
import os
import unittest
from unittest.mock import patch
import ultramarine as u


class AdapterTests(unittest.TestCase):
    def result(self, content="Answer", finish="stop", **extra):
        return {"status": "ok", "data": {"choices": [{"finish_reason": finish,
                "message": {"content": content, **extra}}], "usage": {"completion_tokens": 12}}}

    def test_effort_and_limits(self):
        with patch.object(u, "request") as api:
            self.assertEqual(u.run("task", reasoning_effort="medium")["reason"], "unsupported_option")
            self.assertEqual(u.run("task", max_completion_tokens=32768)["reason"], "invalid_output_limit")
            self.assertEqual(u.run("task", "x" * 49000)["reason"], "input_too_large")
            api.assert_not_called()

    def test_private_authorization(self):
        with patch.object(u, "request") as api:
            self.assertEqual(u.run("task", data_classification="private")["reason"], "external_processing_not_authorized")
            api.assert_not_called()

    def test_controls_forwarded(self):
        for effort in u.EFFORTS:
            with patch.object(u, "request", return_value=self.result()) as api:
                result = u.run("task", reasoning_effort=effort, max_completion_tokens=4096)
                self.assertEqual(result["status"], "candidate")
                self.assertTrue(result["requires_host_review"])
                payload = api.call_args.args[1]
                self.assertEqual(payload["reasoning_effort"], effort)
                self.assertEqual(payload["max_completion_tokens"], 4096)

    def test_default_controls_and_task_specific_json_schema(self):
        with patch.object(u, "request", return_value=self.result('{"action":"complete","code":"","summary":"Done","artifacts":[]}')) as api:
            result = u.run('Return action, code, summary and artifacts.', output_format="json")
            payload = api.call_args.args[1]
            self.assertEqual(payload["reasoning_effort"], "max")
            self.assertEqual(payload["max_completion_tokens"], 16384)
            self.assertEqual(u.capabilities()["default_effort"], "max")
            self.assertIn("matching the schema specified in the task", payload["messages"][0]["content"])
            self.assertNotIn("Return one valid JSON object, with answer and evidence fields", payload["messages"][0]["content"])
            self.assertEqual(result["answer"]["action"], "complete")

    def test_json_cannot_override_envelope(self):
        with patch.object(u, "request", return_value=self.result(json.dumps({"status": "approved", "requires_host_review": False}))):
            result = u.run("task", output_format="json")
            self.assertEqual(result["status"], "candidate")
            self.assertTrue(result["requires_host_review"])

    def test_bad_responses(self):
        for response in (self.result("", "stop"), self.result("partial", "length"),
                         self.result("hello", tool_calls=[{}]), self.result("not JSON")):
            with patch.object(u, "request", return_value=response):
                self.assertEqual(u.run("task", output_format="json")["status"], "fallback")

    def test_missing_disabled(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(u.request("/models")["reason"], "missing_key")
            self.assertFalse(u.capabilities()["authentication_verified"])
        with patch.dict(os.environ, {"ULTRAMARINE_DISABLED": "1"}):
            self.assertEqual(u.request("/models")["reason"], "disabled")

    def test_models_health(self):
        with patch.object(u, "request", return_value={"status": "ok", "data": {"data": [{"id": u.MODEL}]}}):
            self.assertTrue(u.health()["authentication_verified"])
            self.assertFalse(u.health()["generation_tested"])
        with patch.object(u, "request", return_value=u.fallback("authentication_failed")):
            self.assertEqual(u.health()["reason"], "authentication_failed")

    def test_network_errors_sanitized(self):
        with patch.dict(os.environ, {"PAPERINSTRUMENTS_API_KEY": "test-secret", "ULTRAMARINE_DISABLED": "0"}):
            with patch("urllib.request.OpenerDirector.open", side_effect=RuntimeError("test-secret")):
                result = u.request("/models")
                self.assertNotIn("test-secret", json.dumps(result))
                self.assertEqual(result["reason"], "network_or_client_error")


if __name__ == "__main__":
    unittest.main()

