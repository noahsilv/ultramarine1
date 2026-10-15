import base64
import os
import unittest
from unittest.mock import patch
import agent
from executor.service import command


def completion(message, finish='stop'):
    return {'status': 'ok', 'data': {'choices': [{'message': message, 'finish_reason': finish}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 100}}}


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'ULTRAMARINE_EXECUTOR_URL': 'https://executor.example',
            'ULTRAMARINE_EXECUTOR_TOKEN': 'x' * 32})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_loop_and_artifacts_and_reasoning_history(self):
        tool = {'id': 'call1', 'type': 'function', 'function': {'name': 'python_execute', 'arguments': '{"code":"print(2)"}'}}
        responses = [completion({'content': None, 'reasoning_content': 'internal', 'tool_calls': [tool]}, 'tool_calls'),
                     completion({'content': 'Created output.csv'})]
        files = {'output.csv': base64.b64encode(b'x\n2\n').decode()}
        with patch.object(agent, 'request', side_effect=responses) as request, patch.object(agent, 'execute', return_value={
                'exit_code': 0, 'output': '2', 'files': files}) as execute:
            result = agent.agent_run('Create a CSV')
            self.assertEqual(result['status'], 'candidate')
            self.assertEqual(result['artifacts'], files)
            self.assertTrue(result['requires_host_review'])
            history = request.call_args.args[1]['messages']
            self.assertEqual(history[2]['reasoning_content'], 'internal')
            self.assertEqual(history[3]['tool_call_id'], 'call1')
            self.assertNotIn('internal', str(result))
            execute.assert_called_once()

    def test_disabled_executor_and_authorization(self):
        with patch.dict(os.environ, {'ULTRAMARINE_EXECUTOR_URL': ''}), patch.object(agent, 'request') as req:
            self.assertEqual(agent.agent_run('Test')['reason'], 'executor_unconfigured')
            req.assert_not_called()
        self.assertEqual(agent.agent_run('Test', data_classification='confidential')['status'], 'fallback')

    def test_file_traversal_and_budget(self):
        for name in ('../x', '/etc/passwd', 'a/b', 'a\\b'):
            with self.assertRaises(ValueError):
                agent.validate_files({name: ''})
        with patch.object(agent, 'request') as req:
            self.assertEqual(agent.agent_run('Test', max_cost_usd=0.0000001)['reason'], 'budget_limit')
            req.assert_not_called()

    def test_truncation_never_executes(self):
        with patch.object(agent, 'request', return_value=completion({'tool_calls': [{}]}, 'length')), patch.object(agent, 'execute') as exe:
            self.assertEqual(agent.agent_run('Test')['status'], 'fallback')
            exe.assert_not_called()

    def test_unknown_tool_never_executes(self):
        call = {'id': '1', 'type': 'function', 'function': {'name': 'shell', 'arguments': '{}'}}
        with patch.object(agent, 'request', return_value=completion({'tool_calls': [call]}, 'tool_calls')), patch.object(agent, 'execute') as exe:
            self.assertEqual(agent.agent_run('Test')['reason'], 'unsupported_tool')
            exe.assert_not_called()

    def test_no_retries(self):
        with patch.object(agent, 'request', return_value={'status': 'fallback', 'reason': 'authentication_failed'}) as req:
            self.assertEqual(agent.agent_run('Test')['reason'], 'authentication_failed')
            req.assert_called_once()

    def test_docker_boundary(self):
        with patch.dict(os.environ, {'EXECUTOR_IMAGE': 'sha256:' + 'a' * 64, 'PAPERINSTRUMENTS_API_KEY': 'secret'}):
            args = command('test')
        for flag in ('--network=none', '--read-only', '--cap-drop=ALL', '--pids-limit=64', '--user=65534:65534', '--pull=never'):
            self.assertIn(flag, args)
        self.assertNotIn('secret', str(args))
        self.assertFalse(any(a in ('-v', '--volume', '--privileged', '-e', '--env') for a in args))

    def test_executor_requires_https(self):
        for url in ('http://example.com', 'https://user:pass@example.com', 'https://example.com?key=foo'):
            with patch.dict(os.environ, {'ULTRAMARINE_EXECUTOR_URL': url}):
                self.assertIsNone(agent.executor_config())
