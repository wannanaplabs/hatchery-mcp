import asyncio
import importlib
import json
import os
import ssl
import unittest
from unittest.mock import patch, MagicMock
os.environ['HATCHERY_API_KEY'] = 'test-only-key'
server = importlib.import_module('hatchery_mcp.server')

class ContextToolsTest(unittest.TestCase):
    def tearDown(self):
        server._active_session_id = None

    def test_tool_discovery(self):
        tools = asyncio.run(server.mcp.list_tools())
        names = {tool.name for tool in tools}
        self.assertTrue({'get_task_context', 'list_task_comments', 'get_handoffs', 'prepare_handoff', 'accept_handoff', 'cancel_handoff', 'get_task_rules', 'acknowledge_task_context', 'get_development_playbook'} <= names)
        tool = next(t for t in tools if t.name == 'accept_handoff')
        self.assertIn('access_verified', tool.inputSchema['required'])

    def test_context_session_is_remembered(self):
        with patch.object(server, '_make_request', return_value={'session_id': 'session-123'}):
            server.get_context()
        self.assertEqual(server._active_session_id, 'session-123')

    def test_tls_verified_and_timeout_and_session(self):
        server._active_session_id = 'remembered-session'
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{}'
        with patch.object(server.urllib.request, 'urlopen', return_value=response) as call:
            server._make_request('GET', 'tasks/TIP-123/context')
        req = call.call_args.args[0]
        self.assertEqual(req.get_header('X-session-id'), 'remembered-session')
        self.assertEqual(call.call_args.kwargs['timeout'], 30)
        context = call.call_args.kwargs['context']
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)

    def test_accept_does_not_invent_verification_or_retry(self):
        with patch.object(server, '_make_request', return_value={'handoff': {}}) as call:
            server.accept_handoff('TIP-123', 'handoff', 'revision', False)
        self.assertFalse(call.call_args.kwargs['data']['access_verified'])
        self.assertEqual(call.call_count, 1)

    def test_issue_reference_encoded(self):
        with patch.object(server, '_make_request', return_value={}) as call:
            server.get_task_context('../tasks?x=y')
        self.assertEqual(call.call_args.args[1], 'tasks/..%2Ftasks%3Fx%3Dy/context')

if __name__ == '__main__':
    unittest.main()
