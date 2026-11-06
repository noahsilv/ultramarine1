"""Actual MCP integration test, installed dependencies required; no API key needed."""
import asyncio
import unittest
from unittest.mock import patch
from fastmcp import Client
from server import mcp


class MCPTests(unittest.TestCase):
    def test_discovery_and_status(self):
        async def check():
            async with Client(mcp) as client:
                tools = await client.list_tools()
                self.assertEqual({t.name for t in tools}, {
                    "ultramarine_run", "ultramarine_status", "ultramarine_models", "ultramarine_health", "ultramarine_host_step"})
                result = await client.call_tool("ultramarine_status", {})
                self.assertFalse(result.is_error)
        asyncio.run(check())

    def test_completion_diagnostics_survive_mcp(self):
        async def check():
            response = {"status": "ok", "diagnostics": {"request_id": "req-smoke"},
                "data": {"choices": [{"finish_reason": "length", "message": {"content": "private partial"}}],
                         "usage": {"completion_tokens": 16384}}}
            with patch("ultramarine.request", return_value=response) as upstream:
                async with Client(mcp) as client:
                    result = await client.call_tool("ultramarine_run", {"task": "Synthetic test"})
                    self.assertFalse(result.is_error)
                    self.assertEqual(result.data["finish_reason"], "length")
                    self.assertEqual(result.data["usage"]["completion_tokens"], 16384)
                    self.assertEqual(result.data["diagnostics"]["request_id"], "req-smoke")
                    self.assertNotIn("answer", result.data)
                upstream.assert_called_once()
        asyncio.run(check())
