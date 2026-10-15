"""Actual MCP integration test, installed dependencies required; no API key needed."""
import asyncio
import unittest
from fastmcp import Client
from server import mcp


class MCPTests(unittest.TestCase):
    def test_discovery_and_status(self):
        async def check():
            async with Client(mcp) as client:
                tools = await client.list_tools()
                self.assertEqual({t.name for t in tools}, {
                    "ultramarine_run", "ultramarine_status", "ultramarine_models", "ultramarine_health"})
                result = await client.call_tool("ultramarine_status", {})
                self.assertFalse(result.is_error)
        asyncio.run(check())
