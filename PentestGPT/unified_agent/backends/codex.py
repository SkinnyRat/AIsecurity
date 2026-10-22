"""Codex backend via the official openai-codex SDK (drives `codex app-server`).

The shared MCP tool server is injected per-client through `-c`-style config
overrides (`mcp_servers.<name>.*`), the documented mechanism mirroring the CLI.
Codex does NOT inherit the parent environment into MCP server processes, so the
ToolServerSpec env (PYTHONPATH etc.) is passed explicitly as a TOML inline table.

Usage note: turn token usage arrives via `thread/tokenUsage/updated`
notifications (the `turn/completed` payload carries no usage), so the
normalizer tracks the latest usage statefully.
"""

from __future__ import annotations

import contextlib
import inspect
import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

from openai_codex import AsyncCodex, CodexConfig, Sandbox

from ..events import (
    AgentEvent,
    AssistantText,
    CommandRun,
    FileChanged,
    RawEvent,
    Reasoning,
    SessionStarted,
    TextDelta,
    ToolCall,
    ToolResult,
    TurnCompleted,
)
from ..types import (
    AgentAuthError,
    AgentRunError,
    RunOptions,
    SandboxPolicy,
    ToolServerSpec,
    UnifiedUsage,
)

SANDBOX_MAP = {
    SandboxPolicy.READ_ONLY: Sandbox.read_only,
    SandboxPolicy.WORKSPACE_WRITE: Sandbox.workspace_write,
    SandboxPolicy.FULL_ACCESS: Sandbox.full_access,
}


def _toml_string(value: str) -> str:
    # A JSON string is a valid TOML basic string (same escaping rules for
    # quotes/backslashes/control chars).
    return json.dumps(value)


def build_config_overrides(spec: ToolServerSpec) -> tuple[str, ...]:
    """`-c key=value` style overrides defining the shared MCP server."""
    key = f"mcp_servers.{spec.server_name}"
    env_table = (
        "{ " + ", ".join(f'"{k}" = {_toml_string(v)}' for k, v in sorted(spec.env.items())) + " }"
    )
    return (
        f"{key}.command={_toml_string(spec.command[0])}",
        f"{key}.args={json.dumps(spec.command[1:])}",  # JSON array == TOML array of strings
        f"{key}.env={env_table}",
        f"{key}.startup_timeout_sec=30",
        f"{key}.tool_timeout_sec=120",
        f"{key}.required=true",
        f'{key}.default_tools_approval_mode="auto"',
    )


def build_turn_kwargs(opts: RunOptions) -> dict[str, Any]:
    """Per-turn kwargs for Thread.turn()/run(): output schema + reasoning effort."""
    kwargs: dict[str, Any] = {"output_schema": opts.output_schema}
    if opts.effort:
        from openai_codex.generated.v2_all import ReasoningEffort

        try:
            kwargs["effort"] = ReasoningEffort(opts.effort)
        except ValueError as e:
            valid = ", ".join(m.value for m in ReasoningEffort)
            raise AgentRunError(f"invalid effort {opts.effort!r} for codex (valid: {valid})") from e
    return kwargs


def build_thread_kwargs(opts: RunOptions) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "cwd": str(opts.workspace),
        "sandbox": SANDBOX_MAP[opts.sandbox],
    }
    if opts.model:
        kwargs["model"] = opts.model
    if opts.instructions:
        kwargs["developer_instructions"] = opts.instructions
    return kwargs


class _TurnState:
    """Mutable accumulator across one turn's notification stream."""

    def __init__(self, opts: RunOptions):
        self.opts = opts
        self.thread_id: str | None = None
        self.session_announced = False
        self.last_agent_text: str | None = None
        self.usage: Any | None = None  # latest ThreadTokenUsage
        self.errors: list[str] = []


def _status_str(status: Any) -> str:
    return str(getattr(status, "value", status))


def _stringify_mcp_result(result: Any) -> str:
    if result is None:
        return ""
    structured = getattr(result, "structured_content", None)
    if structured:
        try:
            return json.dumps(structured)
        except TypeError:
            return str(structured)
    parts = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        parts.append(text if text is not None else str(block))
    return "\n".join(parts)


def _normalize_item(root: Any, state: _TurnState) -> Iterator[AgentEvent]:
    kind = getattr(root, "type", None)
    if kind == "agentMessage":
        text = getattr(root, "text", "") or ""
        state.last_agent_text = text
        yield AssistantText(text=text)
    elif kind == "reasoning":
        chunks = list(getattr(root, "summary", None) or []) or list(
            getattr(root, "content", None) or []
        )
        text = "\n".join(str(c) for c in chunks)
        if text:
            yield Reasoning(text=text)
    elif kind == "commandExecution":
        yield CommandRun(
            command=getattr(root, "command", "") or "",
            exit_code=getattr(root, "exit_code", None),
            output=getattr(root, "aggregated_output", "") or "",
        )
    elif kind == "mcpToolCall":
        server = getattr(root, "server", "") or ""
        tool = getattr(root, "tool", "") or ""
        arguments = getattr(root, "arguments", None)
        if isinstance(arguments, str):
            with contextlib.suppress(json.JSONDecodeError, ValueError):
                arguments = json.loads(arguments)
        call_id = getattr(root, "id", None)
        yield ToolCall(name=f"mcp__{server}__{tool}", input=arguments, call_id=call_id)
        error = getattr(root, "error", None)
        failed = _status_str(getattr(root, "status", "")) != "completed" or error is not None
        output = (
            getattr(error, "message", None) or str(error)
            if error is not None
            else _stringify_mcp_result(getattr(root, "result", None))
        )
        yield ToolResult(call_id=call_id, output=output or "", is_error=failed)
    elif kind == "fileChange":
        for change in getattr(root, "changes", None) or []:
            yield FileChanged(
                path=str(getattr(change, "path", change)),
                kind=str(getattr(change, "kind", "update")),
            )
    else:
        yield RawEvent(backend="codex", kind=f"item:{kind}", data=root)


def _usage_from_state(state: _TurnState) -> UnifiedUsage:
    total = getattr(state.usage, "total", None)
    if total is None:
        return UnifiedUsage()
    return UnifiedUsage(
        input_tokens=getattr(total, "input_tokens", 0) or 0,
        cached_input_tokens=getattr(total, "cached_input_tokens", 0) or 0,
        output_tokens=getattr(total, "output_tokens", 0) or 0,
        reasoning_output_tokens=getattr(total, "reasoning_output_tokens", 0) or 0,
    )


def normalize_notification(method: str, payload: Any, state: _TurnState) -> Iterator[AgentEvent]:
    if method == "thread/started":
        thread = getattr(payload, "thread", None)
        thread_id = getattr(thread, "id", None)
        if thread_id:
            state.thread_id = thread_id
        if not state.session_announced and state.thread_id:
            state.session_announced = True
            yield SessionStarted(session_id=state.thread_id)

    elif method == "item/completed":
        item = getattr(payload, "item", None)
        root = getattr(item, "root", item)
        if root is not None:
            yield from _normalize_item(root, state)

    elif method == "item/agentMessage/delta":
        if state.opts.stream_text:
            yield TextDelta(text=getattr(payload, "delta", "") or "")

    elif method == "thread/tokenUsage/updated":
        state.usage = getattr(payload, "token_usage", None)

    elif method == "error":
        error = getattr(payload, "error", None)
        message = getattr(error, "message", None) or str(error)
        state.errors.append(message)
        yield RawEvent(backend="codex", kind="error", data=message)

    elif method == "turn/completed":
        turn = getattr(payload, "turn", None)
        status = _status_str(getattr(turn, "status", ""))
        success = status == "completed"
        turn_error = getattr(turn, "error", None)
        error_parts = []
        if turn_error is not None:
            error_parts.append(getattr(turn_error, "message", None) or str(turn_error))
        error_parts.extend(state.errors)
        structured = None
        if state.opts.output_schema and state.last_agent_text:
            try:
                structured = json.loads(state.last_agent_text)
            except (json.JSONDecodeError, ValueError):
                structured = None
        duration = getattr(turn, "duration_ms", None)
        yield TurnCompleted(
            success=success,
            final_text=state.last_agent_text,
            usage=_usage_from_state(state),
            cost_usd=None,  # Codex reports tokens only
            session_id=state.thread_id,
            duration_ms=duration,
            structured_output=structured,
            stop_reason=status,
            error=None if success else ("; ".join(p for p in error_parts if p) or status),
        )

    elif method in ("turn/started", "item/started", "item/updated"):
        pass  # uninteresting transitions; item/completed carries the substance

    else:
        yield RawEvent(backend="codex", kind=method, data=payload)


def _looks_like_auth_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(s in text for s in ("auth", "login", "unauthorized", "api key", "logged out"))


class CodexBackend:
    name = "codex"

    async def stream(self, prompt: str, opts: RunOptions) -> AsyncIterator[AgentEvent]:
        overrides = build_config_overrides(opts.tool_server) if opts.tool_server else ()
        config = CodexConfig(config_overrides=tuple(overrides), cwd=str(opts.workspace))
        state = _TurnState(opts)
        try:
            async with AsyncCodex(config) as codex:
                if opts.resume:
                    thread = await codex.thread_resume(opts.resume, **build_thread_kwargs(opts))
                else:
                    thread = await codex.thread_start(**build_thread_kwargs(opts))
                state.thread_id = getattr(thread, "id", None)
                if state.thread_id and not state.session_announced:
                    state.session_announced = True
                    yield SessionStarted(session_id=state.thread_id)

                handle = thread.turn(prompt, **build_turn_kwargs(opts))
                if inspect.isawaitable(handle):
                    handle = await handle
                async for note in handle.stream():
                    method = getattr(note, "method", "")
                    payload = getattr(note, "payload", None)
                    for event in normalize_notification(method, payload, state):
                        yield event
        except (AgentRunError, AgentAuthError):
            raise
        except Exception as e:  # JSON-RPC / transport errors from the SDK
            if _looks_like_auth_error(e):
                raise AgentAuthError(f"Codex is not authenticated (run `codex login`): {e}") from e
            raise AgentRunError(f"Codex run failed: {type(e).__name__}: {e}") from e
