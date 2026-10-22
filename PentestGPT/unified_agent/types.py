"""Core shared types: sandbox policy, usage, run options, result, errors."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # avoid circular import; events.py imports UnifiedUsage
    from .events import AgentEvent, FileChanged, ToolCall


class SandboxPolicy(StrEnum):
    """Unified write/execution policy, mapped per backend.

    Codex enforces these with an OS sandbox. Claude Code has no OS sandbox by
    default, so the mapping uses its permission system (see backends/claude_code.py);
    the practical asymmetry is documented in the README.
    """

    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    FULL_ACCESS = "full_access"


@dataclass
class UnifiedUsage:
    """Token usage normalized across backends.

    Note: the two providers count differently (Claude reports cache reads
    separately from input tokens; Codex counts cached tokens as a subset of
    input tokens). Values are passed through raw, not reconciled.
    """

    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0

    def __add__(self, other: UnifiedUsage) -> UnifiedUsage:
        return UnifiedUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            reasoning_output_tokens=self.reasoning_output_tokens + other.reasoning_output_tokens,
        )


@dataclass(frozen=True)
class ToolServerSpec:
    """How a backend should launch the shared stdio MCP tool server."""

    server_name: str
    command: list[str]
    env: dict[str, str]


@dataclass
class RunOptions:
    """Backend-independent run configuration, built by UnifiedAgent."""

    workspace: Path
    model: str | None = None
    sandbox: SandboxPolicy = SandboxPolicy.WORKSPACE_WRITE
    instructions: str | None = None
    # Reasoning effort. Both backends accept "low"|"medium"|"high"|"xhigh";
    # Claude additionally accepts "max", Codex "none"/"minimal".
    effort: str | None = None
    tool_server: ToolServerSpec | None = None
    output_schema: dict[str, Any] | None = None
    resume: str | None = None
    max_turns: int | None = None
    extra_env: dict[str, str] = field(default_factory=dict)
    stream_text: bool = False


@dataclass
class UnifiedResult:
    backend: str
    success: bool
    text: str
    structured_output: Any | None
    usage: UnifiedUsage
    cost_usd: float | None
    session_id: str | None
    duration_ms: int | None
    tool_calls: list[ToolCall]
    file_changes: list[FileChanged]
    events: list[AgentEvent]
    error: str | None = None


class UnifiedAgentError(Exception):
    """Base error for the unified_agent package."""


class BackendUnavailableError(UnifiedAgentError):
    """The requested backend SDK is not importable or its CLI is missing."""


class ToolRegistryError(UnifiedAgentError):
    """Invalid tool registration or registry spec."""


class SkillError(UnifiedAgentError):
    """Invalid skill or skill installation failure."""


class ToolServerError(UnifiedAgentError):
    """The shared MCP tool server failed to start/connect in a backend."""


class AgentRunError(UnifiedAgentError):
    """A run failed inside the backend."""


class AgentAuthError(AgentRunError):
    """The backend is not authenticated (login/API key required)."""
