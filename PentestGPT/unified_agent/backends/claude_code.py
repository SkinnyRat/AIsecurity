"""Claude Code backend via claude-agent-sdk (bundles the Claude Code CLI).

Sandbox policy is mapped onto Claude Code's permission system. Claude Code has
no OS sandbox by default, so READ_ONLY removes write/shell tools entirely
(`dontAsk` denies anything not allow-listed), while Codex can still execute
commands inside its read-only OS sandbox — the honest asymmetry documented in
the README.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    CLINotFoundError,
    ProcessError,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)

from ..events import (
    AgentEvent,
    AssistantText,
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
    BackendUnavailableError,
    RunOptions,
    SandboxPolicy,
    ToolServerError,
    UnifiedUsage,
)

READ_TOOLS = ["Read", "Glob", "Grep"]
WRITE_TOOLS = ["Write", "Edit", "NotebookEdit"]
EXEC_TOOLS = ["Bash"]

# statuses the init message may report for an MCP server that is not usable
_BAD_MCP_STATUSES = {"failed", "needs-auth", "needs_auth", "error"}


def build_options(opts: RunOptions) -> ClaudeAgentOptions:
    allowed: list[str]
    disallowed: list[str] = []
    if opts.sandbox is SandboxPolicy.READ_ONLY:
        permission_mode = "dontAsk"  # deny anything not allow-listed, never prompt
        allowed = list(READ_TOOLS)
        disallowed = WRITE_TOOLS + EXEC_TOOLS
    elif opts.sandbox is SandboxPolicy.WORKSPACE_WRITE:
        permission_mode = "acceptEdits"
        allowed = READ_TOOLS + WRITE_TOOLS + EXEC_TOOLS
    else:  # FULL_ACCESS
        permission_mode = "bypassPermissions"
        allowed = READ_TOOLS + WRITE_TOOLS + EXEC_TOOLS

    mcp_servers: dict = {}
    if opts.tool_server is not None:
        spec = opts.tool_server
        mcp_servers[spec.server_name] = {
            "type": "stdio",
            "command": spec.command[0],
            "args": spec.command[1:],
            "env": dict(spec.env),
        }
        allowed.append(f"mcp__{spec.server_name}__*")

    return ClaudeAgentOptions(
        cwd=str(opts.workspace),
        model=opts.model,
        permission_mode=permission_mode,
        allowed_tools=allowed,
        disallowed_tools=disallowed,
        mcp_servers=mcp_servers,
        # Hermetic: only project-level settings/skills/CLAUDE.md from the
        # workspace; no user/local config bleeding into runs.
        setting_sources=["project"],
        # Always run with Claude Code's native system prompt: passing None
        # strips it entirely — including the working-directory env context —
        # which makes the model write files outside the workspace. This
        # mirrors Codex, where developer_instructions append to (never
        # replace) the base prompt.
        system_prompt=(
            {"type": "preset", "preset": "claude_code", "append": opts.instructions}
            if opts.instructions
            else {"type": "preset", "preset": "claude_code"}
        ),
        output_format=(
            {"type": "json_schema", "schema": opts.output_schema} if opts.output_schema else None
        ),
        effort=opts.effort,
        resume=opts.resume,
        max_turns=opts.max_turns,
        env=dict(opts.extra_env),
        include_partial_messages=opts.stream_text,
    )


def _stringify_block_content(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for item in content:
        if isinstance(item, dict):
            parts.append(str(item.get("text", item)))
        else:
            parts.append(str(item))
    return "\n".join(parts)


def normalize_message(message, opts: RunOptions) -> Iterator[AgentEvent]:
    if isinstance(message, SystemMessage):
        if message.subtype == "init":
            data = message.data or {}
            if opts.tool_server is not None:
                for server in data.get("mcp_servers", []):
                    if (
                        server.get("name") == opts.tool_server.server_name
                        and server.get("status") in _BAD_MCP_STATUSES
                    ):
                        raise ToolServerError(
                            f"MCP tool server '{server['name']}' failed to connect in "
                            f"Claude Code (status={server.get('status')!r})"
                        )
            session_id = data.get("session_id")
            if session_id:
                yield SessionStarted(session_id=session_id)
        else:
            yield RawEvent(backend="claude", kind=f"system:{message.subtype}", data=message.data)

    elif isinstance(message, AssistantMessage):
        if message.error == "authentication_failed":
            raise AgentAuthError(
                "Claude Code is not authenticated: run `claude /login` or set ANTHROPIC_API_KEY"
            )
        if message.error:
            yield RawEvent(
                backend="claude", kind=f"assistant_error:{message.error}", data=message.error
            )
        for block in message.content:
            if isinstance(block, TextBlock):
                yield AssistantText(text=block.text)
            elif isinstance(block, ThinkingBlock):
                yield Reasoning(text=block.thinking)
            elif isinstance(block, ToolUseBlock):
                yield ToolCall(name=block.name, input=block.input, call_id=block.id)
            elif isinstance(block, ToolResultBlock):
                yield ToolResult(
                    call_id=block.tool_use_id,
                    output=_stringify_block_content(block.content),
                    is_error=bool(block.is_error),
                )

    elif isinstance(message, UserMessage):
        content = message.content
        if isinstance(content, list):
            for block in content:
                if isinstance(block, ToolResultBlock):
                    yield ToolResult(
                        call_id=block.tool_use_id,
                        output=_stringify_block_content(block.content),
                        is_error=bool(block.is_error),
                    )

    elif isinstance(message, StreamEvent):
        if opts.stream_text:
            event = message.event or {}
            delta = event.get("delta") or {}
            if event.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
                yield TextDelta(text=delta.get("text", ""))

    elif isinstance(message, ResultMessage):
        usage = message.usage or {}
        success = (not message.is_error) and message.subtype == "success"
        errors = getattr(message, "errors", None) or []
        yield TurnCompleted(
            success=success,
            final_text=message.result,
            usage=UnifiedUsage(
                input_tokens=usage.get("input_tokens", 0) or 0,
                cached_input_tokens=usage.get("cache_read_input_tokens", 0) or 0,
                output_tokens=usage.get("output_tokens", 0) or 0,
            ),
            cost_usd=message.total_cost_usd,
            session_id=message.session_id,
            duration_ms=message.duration_ms,
            structured_output=message.structured_output,
            stop_reason=message.subtype,
            error=None if success else ("; ".join(errors) or message.subtype),
        )

    else:
        yield RawEvent(backend="claude", kind=type(message).__name__, data=message)


class ClaudeCodeBackend:
    name = "claude"

    async def stream(self, prompt: str, opts: RunOptions) -> AsyncIterator[AgentEvent]:
        try:
            async for message in query(prompt=prompt, options=build_options(opts)):
                for event in normalize_message(message, opts):
                    yield event
        except CLINotFoundError as e:
            raise BackendUnavailableError(f"Claude Code CLI not found: {e}") from e
        except ProcessError as e:
            stderr = (e.stderr or "").strip()
            lowered = stderr.lower()
            if "auth" in lowered or "login" in lowered or "api key" in lowered:
                raise AgentAuthError(f"Claude Code process failed (auth): {stderr}") from e
            raise AgentRunError(
                f"Claude Code process failed (exit {e.exit_code}): {stderr[-2000:]}"
            ) from e
