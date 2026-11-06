"""Synthetic failure regression tests; no provider calls or project evidence."""
import io
import json
import os
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

import ultramarine as u
from host_execution import host_step


class DiagnosticTests(unittest.TestCase):
    def completion(self, finish="length", content="private rejected text", **message):
        return {"status": "ok", "diagnostics": {"request_id": "req-123", "http_status": 200},
                "data": {"choices": [{"finish_reason": finish,
                    "message": {"content": content, "reasoning_content": "secret reasoning", **message}}],
                    "usage": {"prompt_tokens": 123, "completion_tokens": 16384, "total_tokens": 16507,
                        "completion_tokens_details": {"reasoning_tokens": 16000, "secret": "never return"},
                        "prompt_tokens_details": {"cached_tokens": 10}}}}

    def test_length_fallback_preserves_usage_without_rejected_content(self):
        with patch.object(u, "request", return_value=self.completion()) as api:
            result = u.run("synthetic task", output_format="json")
        self.assertEqual(result["reason"], "incomplete_or_tool_response")
        self.assertEqual(result["finish_reason"], "length")
        self.assertEqual(result["usage"]["completion_tokens_details"], {"reasoning_tokens": 16000})
        self.assertEqual(result["usage"]["prompt_tokens_details"], {"cached_tokens": 10})
        self.assertEqual(result["diagnostics"]["request_id"], "req-123")
        self.assertEqual(result["diagnostics"]["answer_characters"], len("private rejected text"))
        for secret in ("private rejected text", "secret reasoning", "never return"):
            self.assertNotIn(secret, json.dumps(result))
        self.assertNotIn("answer", result)
        api.assert_called_once()

    def test_tool_calls_rejected_and_not_echoed_even_with_stop(self):
        for msg in ({"tool_calls": [{"function": {"arguments": "private args"}}]},
                    {"function_call": {"arguments": "private args"}}):
            with patch.object(u, "request", return_value=self.completion("stop", **msg)):
                result = u.run("synthetic task")
            self.assertEqual(result["status"], "fallback")
            self.assertTrue(result["diagnostics"]["tool_calls_present"])
            self.assertNotIn("private args", json.dumps(result))

    def test_empty_malformed_and_invalid_json_keep_metadata(self):
        cases = [(self.completion("stop", ""), "empty_response"),
                 (self.completion("stop", "not JSON"), "invalid_completion"),
                 (self.completion("stop", "[]"), "invalid_json_object")]
        missing_choice = self.completion()
        missing_choice["data"]["choices"] = []
        cases.append((missing_choice, "invalid_completion"))
        for response, reason in cases:
            with patch.object(u, "request", return_value=response):
                result = u.run("task", output_format="json")
            self.assertEqual(result["reason"], reason)
            self.assertEqual(result["usage"]["total_tokens"], 16507)
            self.assertEqual(result["diagnostics"]["http_status"], 200)

    def test_unknown_metadata_is_not_invented_or_copied(self):
        malformed = {"choices": [{"finish_reason": {"secret": "sensitive"},
                                  "message": {"content": ["sensitive"]}}],
                     "usage": {"prompt_tokens": True, "total_tokens": -1,
                               "completion_tokens": "123", "completion_tokens_details": "sensitive"}}
        m = u.completion_metadata(malformed)
        self.assertEqual(m["finish_reason"], "other")
        self.assertEqual(m["usage"], {})
        self.assertIsNone(m["answer_characters"])
        self.assertNotIn("sensitive", json.dumps(m))
        for data in (None, [], {"choices": None}, {"choices": [None]}, {"usage": "bad"}):
            self.assertIsNone(u.completion_metadata(data)["finish_reason"])

    def test_success_and_invalid_host_proposal_keep_metadata(self):
        with patch.object(u, "request", return_value=self.completion("stop", '{"answer":"ok"}')):
            candidate = u.run("task", output_format="json")
            rejected = host_step("task")
        self.assertEqual(candidate["status"], "candidate")
        self.assertEqual(candidate["finish_reason"], "stop")
        self.assertFalse(candidate["evidence_validated"])
        self.assertEqual(rejected["reason"], "invalid_host_proposal")
        self.assertEqual(rejected["usage"], candidate["usage"])
        self.assertNotIn("answer", rejected)

    def call_request(self, *, raw=b'{}', headers=None, error=None):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.headers = headers or {}
        response.read.return_value = raw
        with patch.dict(os.environ, {"PAPERINSTRUMENTS_API_KEY": "test-secret", "ULTRAMARINE_DISABLED": "0"}):
            with patch("urllib.request.OpenerDirector.open", return_value=response, side_effect=error) as opened:
                result = u.request("/chat/completions", {"synthetic": True})
                opened.assert_called_once()
        return result

    def test_request_headers_and_body_sanitization(self):
        result = self.call_request(headers={"x-request-id": "req_123", "authorization": "test-secret"})
        self.assertEqual(result["diagnostics"]["request_id"], "req_123")
        self.assertEqual(result["diagnostics"]["response_state"], "received")
        self.assertGreaterEqual(result["diagnostics"]["elapsed_ms"], 0)
        self.assertNotIn("test-secret", json.dumps(result))
        for value in ("test-secret", "Bearer test-secret", "x" * 129, "hello\nworld"):
            result = self.call_request(raw=b'not json private', headers={"x-request-id": value})
            self.assertEqual(result["reason"], "invalid_response")
            self.assertIsNone(result["diagnostics"]["request_id"])
            self.assertNotIn("private", json.dumps(result))
        result = self.call_request(raw=b'[]')
        self.assertEqual(result["diagnostics"]["response_state"], "invalid_json_object")
        with patch.object(u, "MAX_RESPONSE_BYTES", 2):
            self.assertEqual(self.call_request(raw=b'123')["reason"], "response_too_large")

    def test_http_errors_preserve_bounded_retry_hints_not_body(self):
        error = urllib.error.HTTPError("https://example.invalid", 429, "test-secret",
                    {"x-request-id": "req-429", "retry-after": "30", "x-should-retry": "false"},
                    io.BytesIO(b'private provider error'))
        result = self.call_request(error=error)
        self.assertEqual(result["reason"], "rate_or_quota_limit")
        self.assertFalse(result["retryable"])
        self.assertEqual(result["diagnostics"]["retry_after_seconds"], 30)
        self.assertEqual(result["diagnostics"]["http_status"], 429)
        self.assertNotIn("test-secret", json.dumps(result))
        self.assertNotIn("private provider error", json.dumps(result))

    def test_timeout_distinguished_without_exception_text(self):
        for error in (TimeoutError("test-secret"), urllib.error.URLError(TimeoutError("test-secret"))):
            result = self.call_request(error=error)
            self.assertEqual(result["reason"], "request_timeout")
            self.assertEqual(result["diagnostics"]["failure_phase"], "awaiting_response")
            self.assertNotIn("test-secret", json.dumps(result))
        result = self.call_request(error=RuntimeError("test-secret"))
        self.assertEqual(result["reason"], "network_or_client_error")
        # The semaphore is still usable after every failure.
        self.assertEqual(self.call_request()["status"], "ok")


if __name__ == "__main__":
    unittest.main()
