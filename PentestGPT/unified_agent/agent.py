"""UnifiedAgent: one class that drives Claude Code or Codex interchangeably.

SuperAgent fans the same task out to several UnifiedAgents concurrently.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable, Mapping
from pathlib import Path
from typing import Any

from .backends.base import AgentBackend
from .events import (
    AgentEvent,
    AssistantText,
    FileChanged,
    SessionStarted,
    ToolCall,
    TurnCompleted,
)
from .skills import install_skills
from .task import Task
from .tools import ToolRegistry, build_tool_server_spec
from .types import (
    BackendUnavailableError,
    RunOptions,
    SandboxPolicy,
    ToolServerSpec,
    UnifiedResult,
    UnifiedUsage,
)

BACKEND_NAMES = ("claude", "codex")


def _make_backend(backend: str | AgentBackend) -> AgentBackend:
    if not isinstance(backend, str):
        return backend
    try:
        if backend == "claude":
            from .backends.claude_code import ClaudeCodeBackend

            return ClaudeCodeBackend()
        if backend == "codex":
            from .backends.codex import CodexBackend

            return CodexBackend()
    except ImportError as e:
        raise BackendUnavailableError(
            f"backend {backend!r} is installed-time unavailable: {e}. "
            f"Install the SDK ('pip install claude-agent-sdk' / 'pip install --pre openai-codex')."
        ) from e
    raise BackendUnavailableError(
        f"unknown backend {backend!r}; expected one of {BACKEND_NAMES} or an AgentBackend instance"
    )


def collect(backend_name: str, events: list[AgentEvent], error: str | None = None) -> UnifiedResult:
    """Fold a normalized event stream into a UnifiedResult."""
    turn = next((e for e in reversed(events) if isinstance(e, TurnCompleted)), None)
    last_text = next((e.text for e in reversed(events) if isinstance(e, AssistantText)), None)
    session_id = next((e.session_id for e in events if isinstance(e, SessionStarted)), None)

    text = (turn.final_text if turn and turn.final_text else last_text) or ""
    success = bool(turn and turn.success) and error is None
    return UnifiedResult(
        backend=backend_name,
        success=success,
        text=text,
        structured_output=turn.structured_output if turn else None,
        usage=turn.usage if turn else UnifiedUsage(),
        cost_usd=turn.cost_usd if turn else None,
        session_id=(turn.session_id if turn and turn.session_id else session_id),
        duration_ms=turn.duration_ms if turn else None,
        tool_calls=[e for e in events if isinstance(e, ToolCall)],
        file_changes=[e for e in events if isinstance(e, FileChanged)],
        events=list(events),
        error=error or (turn.error if turn else None),
    )


class UnifiedAgent:
    """One agent unit. Same task, tools, skills and events on either backend.

    Args:
        backend: "claude", "codex", or any AgentBackend instance.
        workspace: directory the agent works in (created if missing; skills are
            installed into its .claude/skills and .agents/skills).
        model: backend-native model name (e.g. "claude-opus-4-8" / "gpt-5.5");
            None uses each backend's default.
        sandbox: unified write policy (see SandboxPolicy for the per-backend mapping).
        tools: a ToolRegistry or "pkg.mod:REGISTRY" spec served to both backends
            over stdio MCP as mcp__<server>__<tool>.
        skills_dir: canonical Agent Skills source dir, installed into both hosts'
            discovery dirs on first run.
        instructions: appended to each backend's native system prompt
            (Claude: claude_code preset append; Codex: developer_instructions).
        effort: reasoning effort. Both accept "low"|"medium"|"high"|"xhigh";
            Claude additionally "max", Codex "none"/"minimal".
        extra_env: environment passed to the agent process and the tool server.
        stream_text: emit TextDelta events for incremental assistant text.
    """

    def __init__(
        self,
        backend: str | AgentBackend,
        workspace: str | Path = ".",
        *,
        model: str | None = None,
        sandbox: SandboxPolicy = SandboxPolicy.WORKSPACE_WRITE,
        tools: ToolRegistry | str | None = None,
        skills_dir: str | Path | None = None,
        instructions: str | None = None,
        effort: str | None = None,
        extra_env: Mapping[str, str] | None = None,
        stream_text: bool = False,
        skills_install_mode: str = "symlink",
    ):
        self.backend = _make_backend(backend)
        self.workspace = Path(workspace).resolve()
        self.model = model
        self.sandbox = SandboxPolicy(sandbox)
        self.tools = tools
        self.skills_dir = Path(skills_dir).resolve() if skills_dir else None
        self.instructions = instructions
        self.effort = effort
        self.extra_env = dict(extra_env or {})
        self.stream_text = stream_text
        self.skills_install_mode = skills_install_mode
        self._tool_server: ToolServerSpec | None = None
        self._prepared = False

    @property
    def name(self) -> str:
        return self.backend.name

    def _prepare(self) -> None:
        if self._prepared:
            return
        self.workspace.mkdir(parents=True, exist_ok=True)
        if self.skills_dir is not None:
            install_skills(self.workspace, self.skills_dir, mode=self.skills_install_mode)
        if self.tools is not None:
            self._tool_server = build_tool_server_spec(self.tools, self.extra_env)
        self._prepared = True

    def _run_options(
        self,
        output_schema: dict[str, Any] | None,
        resume: str | None,
        max_turns: int | None,
    ) -> RunOptions:
        return RunOptions(
            workspace=self.workspace,
            model=self.model,
            sandbox=self.sandbox,
            instructions=self.instructions,
            effort=self.effort,
            tool_server=self._tool_server,
            output_schema=output_schema,
            resume=resume,
            max_turns=max_turns,
            extra_env=dict(self.extra_env),
            stream_text=self.stream_text,
        )

    async def stream(
        self,
        task: Task | str,
        *,
        output_schema: dict[str, Any] | None = None,
        resume: str | None = None,
        max_turns: int | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Yield normalized events for one run. Raises on backend failure."""
        self._prepare()
        prompt = Task.coerce(task).render(self.backend.name)
        opts = self._run_options(output_schema, resume, max_turns)
        async for event in self.backend.stream(prompt, opts):
            yield event

    async def run(
        self,
        task: Task | str,
        *,
        output_schema: dict[str, Any] | None = None,
        resume: str | None = None,
        max_turns: int | None = None,
    ) -> UnifiedResult:
        """Run one task to completion; failures come back as success=False results."""
        events: list[AgentEvent] = []
        try:
            async for event in self.stream(
                task, output_schema=output_schema, resume=resume, max_turns=max_turns
            ):
                events.append(event)
        except Exception as e:
            return collect(self.backend.name, events, error=f"{type(e).__name__}: {e}")
        return collect(self.backend.name, events)

    def run_sync(self, task: Task | str, **kwargs: Any) -> UnifiedResult:
        return asyncio.run(self.run(task, **kwargs))


class SuperAgent:
    """Controls several UnifiedAgents as one unit."""

    def __init__(self, agents: Mapping[str, UnifiedAgent]):
        if not agents:
            raise ValueError("SuperAgent needs at least one agent")
        self._agents = dict(agents)

    @property
    def agents(self) -> dict[str, UnifiedAgent]:
        return dict(self._agents)

    async def run(self, name: str, task: Task | str, **kwargs: Any) -> UnifiedResult:
        return await self._agents[name].run(task, **kwargs)

    async def run_all(
        self,
        task: Task | str,
        *,
        only: Iterable[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, UnifiedResult]:
        """Run the same task on every (selected) agent concurrently."""
        names = list(only) if only is not None else list(self._agents)
        results = await asyncio.gather(*(self._agents[n].run(task, **kwargs) for n in names))
        return dict(zip(names, results, strict=True))

    def run_all_sync(self, task: Task | str, **kwargs: Any) -> dict[str, UnifiedResult]:
        return asyncio.run(self.run_all(task, **kwargs))
