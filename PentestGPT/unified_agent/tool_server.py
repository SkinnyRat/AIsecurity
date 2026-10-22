"""Stdio MCP server that serves a ToolRegistry to both agents.

Launched identically by the Claude Code and Codex backends:

    python -m unified_agent.tool_server pkg.mod:REGISTRY

stdout is reserved for the MCP JSON-RPC protocol; all logging goes to stderr.
"""

from __future__ import annotations

import sys

from mcp.server.fastmcp import FastMCP

from .tools import ToolRegistry, resolve_registry


def build_server(registry: ToolRegistry) -> FastMCP:
    server = FastMCP(registry.server_name)
    for entry in registry.tools:
        server.add_tool(entry.fn, name=entry.name, description=entry.description)
    return server


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(
            "usage: python -m unified_agent.tool_server pkg.mod:REGISTRY",
            file=sys.stderr,
        )
        raise SystemExit(2)
    registry = resolve_registry(argv[0])
    print(
        f"[unified_agent.tool_server] serving {len(registry.tools)} tool(s) "
        f"as server '{registry.server_name}' over stdio",
        file=sys.stderr,
        flush=True,
    )
    build_server(registry).run(transport="stdio")


if __name__ == "__main__":
    main()
