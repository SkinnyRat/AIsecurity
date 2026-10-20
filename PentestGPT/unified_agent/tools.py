"""One tool definition, two agents.

Tools are plain Python functions registered on a :class:`ToolRegistry`. Both
backends launch the same stdio MCP server subprocess
(``python -m unified_agent.tool_server pkg.mod:REGISTRY``), so the model-visible
tool names are byte-identical in Claude Code and Codex: ``mcp__<server>__<tool>``.

Constraints enforced here (lowest common denominator of both hosts):
- names match ``[a-z][a-z0-9_]*`` (Codex rewrites ``-`` to ``_`` which would
  desync Claude permission strings, so hyphens are banned),
- the fully-qualified name fits in 64 bytes (Codex hard cap),
- the registry lives in an importable module (the server subprocess imports it).
"""

from __future__ import annotations

import importlib
import inspect
import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .types import ToolRegistryError, ToolServerSpec

NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
MAX_FQ_NAME_BYTES = 64


@dataclass(frozen=True)
class ToolEntry:
    fn: Callable[..., Any]
    name: str
    description: str


class ToolRegistry:
    """Collects tool functions; served to both agents via the MCP tool server."""

    def __init__(self, server_name: str = "unified"):
        if not NAME_RE.match(server_name):
            raise ToolRegistryError(
                f"invalid server name {server_name!r}: must match {NAME_RE.pattern}"
            )
        self.server_name = server_name
        self._entries: dict[str, ToolEntry] = {}
        frame = sys._getframe(1)
        self._defining_module: str | None = frame.f_globals.get("__name__")

    @property
    def tools(self) -> list[ToolEntry]:
        return list(self._entries.values())

    def tool(
        self, name: str | None = None, description: str | None = None
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Register a (sync or async) function as a tool on both agents.

        The input schema is derived from type hints by the MCP server; the
        description (here or the docstring's first line) is what both models
        use to decide when to call the tool — make it count.
        """

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            tool_name = name if name is not None else fn.__name__
            if not NAME_RE.match(tool_name or ""):
                raise ToolRegistryError(
                    f"invalid tool name {tool_name!r}: must match {NAME_RE.pattern} "
                    "(lowercase, digits, underscores; no hyphens)"
                )
            fq = f"mcp__{self.server_name}__{tool_name}"
            if len(fq.encode()) > MAX_FQ_NAME_BYTES:
                raise ToolRegistryError(
                    f"fully-qualified tool name {fq!r} exceeds {MAX_FQ_NAME_BYTES} bytes "
                    "(Codex hard limit); shorten the tool or server name"
                )
            if tool_name in self._entries:
                raise ToolRegistryError(f"duplicate tool name {tool_name!r}")
            desc = description
            if desc is None:
                doc = inspect.getdoc(fn) or ""
                desc = doc.strip().splitlines()[0].strip() if doc.strip() else ""
            if not desc:
                raise ToolRegistryError(
                    f"tool {tool_name!r} needs a description (docstring or description=)"
                )
            self._entries[tool_name] = ToolEntry(fn=fn, name=tool_name, description=desc)
            return fn

        return decorator


def resolve_registry(spec: str) -> ToolRegistry:
    """Import a registry from a ``package.module:ATTR`` spec string."""
    module_name, sep, attr = spec.partition(":")
    if not sep or not module_name or not attr:
        raise ToolRegistryError(f"invalid registry spec {spec!r}: expected 'pkg.mod:ATTR'")
    try:
        module = importlib.import_module(module_name)
    except ImportError as e:
        raise ToolRegistryError(f"cannot import module {module_name!r}: {e}") from e
    try:
        registry = getattr(module, attr)
    except AttributeError as e:
        raise ToolRegistryError(f"module {module_name!r} has no attribute {attr!r}") from e
    if not isinstance(registry, ToolRegistry):
        raise ToolRegistryError(f"{spec!r} is not a ToolRegistry (got {type(registry).__name__})")
    return registry


def registry_spec(registry: ToolRegistry) -> str:
    """Derive the ``pkg.mod:ATTR`` spec for a registry instance."""
    module_name = registry._defining_module
    if not module_name or module_name == "__main__":
        raise ToolRegistryError(
            "the tool registry must be defined in an importable module (not __main__) "
            "so the MCP server subprocess can import it; move it into a module or pass "
            "the 'pkg.mod:ATTR' spec string explicitly"
        )
    module = importlib.import_module(module_name)
    for attr, value in vars(module).items():
        if value is registry:
            return f"{module_name}:{attr}"
    raise ToolRegistryError(
        f"registry not found as a top-level attribute of module {module_name!r}"
    )


def _module_root_dir(module_name: str) -> Path:
    """Directory that must be on sys.path so ``module_name`` is importable."""
    module = importlib.import_module(module_name)
    module_file = getattr(module, "__file__", None)
    if module_file is None:  # namespace pkg / builtin: nothing to add
        raise ToolRegistryError(f"module {module_name!r} has no __file__")
    path = Path(module_file).resolve()
    parts = module_name.count(".") + 1
    levels = parts if path.name == "__init__.py" else parts - 1
    return path.parents[levels] if levels > 0 else path.parent


def build_tool_server_spec(
    tools: ToolRegistry | str, extra_env: dict[str, str] | None = None
) -> ToolServerSpec:
    """Build the launch spec both backends use for the shared tool server.

    The env is passed explicitly because Codex does NOT inherit the parent
    environment into MCP server processes (Claude Code does, but we pass the
    same env there too so both servers run identically).
    """
    spec = tools if isinstance(tools, str) else registry_spec(tools)
    registry = resolve_registry(spec)
    if not registry.tools:
        raise ToolRegistryError(f"registry {spec!r} has no tools registered")

    module_name = spec.partition(":")[0]
    unified_agent_root = Path(__file__).resolve().parent.parent
    paths = [str(_module_root_dir(module_name)), str(unified_agent_root)]
    env = dict(extra_env or {})
    if env.get("PYTHONPATH"):
        paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(paths))

    command = [sys.executable, "-m", "unified_agent.tool_server", spec]
    return ToolServerSpec(server_name=registry.server_name, command=command, env=env)
