import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

@unittest.skipUnless(importlib.util.find_spec('mcp'), 'SDK MCP optionnel absent')
class MCPIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_handshake_tools_and_actual_calls(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from prono.workspace import Workspace
        from prono.demo import seed
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'config').mkdir()
            shutil.copy(ROOT/'config/workspace.toml', root/'config/workspace.toml')
            seed(Workspace(root))
            server = StdioServerParameters(command=sys.executable, args=['-m','prono.cli','--workspace',str(root),'mcp'])
            async with stdio_client(server) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    self.assertEqual({t.name for t in tools.tools}, {'list_fixtures','analyze_match','paper_summary','model_evaluation'})
                    summary = await session.call_tool('paper_summary', {})
                    self.assertFalse(summary.isError)
                    value = json.loads(summary.content[0].text)
                    self.assertEqual(value['mode'], 'paper')
                    result = await session.call_tool('analyze_match', {'event_id':'demo-1'})
                    self.assertFalse(result.isError)
                    self.assertEqual(json.loads(result.content[0].text)['status'], 'analysis_only')
            self.assertFalse((root/'journal').exists())
