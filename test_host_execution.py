import unittest
from unittest.mock import patch
from host_execution import host_step

class HostStepTests(unittest.TestCase):
    def candidate(self, **changes):
        answer = dict(action="python", code="print(120 / 80)", summary="Calculate", artifacts=[])
        answer.update(changes)
        return dict(status="candidate", answer=answer)

    @patch("host_execution.run")
    def test_proposal_and_feedback(self, run):
        run.return_value = self.candidate()
        result = host_step("Calculate", "stdlib", "previous exit 1", data_classification="synthetic")
        self.assertFalse(result["code_executed"])
        self.assertTrue(result["requires_code_review"])
        self.assertIn("previous exit 1", run.call_args.args[1])
        self.assertEqual(run.call_args.args[6], "synthetic")

    @patch("host_execution.run")
    def test_bad_shapes(self, run):
        for changes in [dict(action="shell"), dict(code=""), dict(artifacts="out"),
                        dict(action="complete", code="print(1)"), dict(extra=True)]:
            run.return_value = self.candidate(**changes)
            self.assertEqual(host_step("test")["reason"], "invalid_host_proposal")

    @patch("host_execution.run")
    def test_complete_is_still_unverified(self, run):
        run.return_value = self.candidate(action="complete", code="")
        self.assertTrue(host_step("test")["host_validation_required"])

    @patch("host_execution.run")
    def test_fallback_no_retry(self, run):
        run.return_value = dict(status="fallback", reason="authentication_failed")
        self.assertEqual(host_step("test")["reason"], "authentication_failed")
        run.assert_called_once()

    @patch("host_execution.run")
    def test_invalid_input_no_request(self, run):
        for args in [("",), ("x", None), ("x", "a" * 40001)]:
            self.assertEqual(host_step(*args)["status"], "fallback")
        run.assert_not_called()

    def test_private_payload_requires_authorization(self):
        self.assertEqual(host_step("test", data_classification="private")["reason"],
                         "external_processing_not_authorized")

    def test_real_adapter_preserves_python_and_complete_contracts(self):
        import json
        for action, code in [("python", "print(1)"), ("complete", "")]:
            proposal = dict(action=action, code=code, summary="Synthetic", artifacts=[])
            response = {"status":"ok", "data":{"choices":[{"finish_reason":"stop", "message":{"content":json.dumps(proposal)}}]}}
            with patch("ultramarine.request", return_value=response) as api:
                result = host_step("Synthetic test", feedback="Host exit 0", data_classification="synthetic")
                self.assertEqual(result["status"], "candidate")
                self.assertEqual(result["answer"], proposal)
                self.assertFalse(result["code_executed"])
                payload = api.call_args.args[1]
                self.assertEqual(payload["reasoning_effort"], "max")
                self.assertEqual(payload["max_completion_tokens"], 16384)
                self.assertIn('action: "python" or "complete"', json.loads(payload["messages"][1]["content"])["task"])

