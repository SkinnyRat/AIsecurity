import os
from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from tests.fixture_registry import REG
from unified_agent.tool_server import build_server
from unified_agent.tools import build_tool_server_spec

REPO_ROOT = Path(__file__).resolve().parent.parent


async def test_build_server_exposes_registry_tools():
    server = build_server(REG)
    tools = await server.list_tools()
    by_name = {t.name: t for t in tools}
    assert set(by_name) == {"add_numbers", "echo_upper"}
    assert by_name["add_numbers"].description == "Add two numbers and return the sum."
    props = by_name["add_numbers"].inputSchema["properties"]
    assert set(props) == {"a", "b"}


@pytest.mark.slow
async def test_stdio_roundtrip_via_subprocess():
    """The core promise: the same server subprocess both agents launch works over stdio."""
    spec = build_tool_server_spec(REG)
    params = StdioServerParameters(
        command=spec.command[0],
        args=spec.command[1:],
        env={**os.environ, **spec.env},
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        listed = await session.list_tools()
        names = {t.name for t in listed.tools}
        assert names == {"add_numbers", "echo_upper"}

        result = await session.call_tool("add_numbers", {"a": 2, "b": 3})
        text = "".join(c.text for c in result.content if c.type == "text")
        assert "5" in text

        result2 = await session.call_tool("echo_upper", {"text": "hi"})
        text2 = "".join(c.text for c in result2.content if c.type == "text")
        assert "HI" in text2


def test_main_rejects_bad_argv(capsys):
    from unified_agent.tool_server import main

    with pytest.raises(SystemExit):
        main([])
    with pytest.raises(SystemExit):
        main(["a", "b"])
