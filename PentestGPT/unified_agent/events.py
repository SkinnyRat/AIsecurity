"""Normalized event model shared by all backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .types import UnifiedUsage


@dataclass(frozen=True)
class SessionStarted:
    session_id: str


@dataclass(frozen=True)
class TextDelta:
    """Incremental assistant text (only when stream_text=True)."""

    text: str


@dataclass(frozen=True)
class AssistantText:
    """A completed assistant message."""

    text: str


@dataclass(frozen=True)
class Reasoning:
    text: str


@dataclass(frozen=True)
class ToolCall:
    name: str
    input: Any
    call_id: str | None = None


@dataclass(frozen=True)
class ToolResult:
    call_id: str | None
    output: str
    is_error: bool = False


@dataclass(frozen=True)
class CommandRun:
    """A shell command executed by the agent (Codex commandExecution items)."""

    command: str
    exit_code: int | None
    output: str


@dataclass(frozen=True)
class FileChanged:
    path: str
    kind: str  # add | update | delete (backend vocabulary passed through)


@dataclass(frozen=True)
class TurnCompleted:
    success: bool
    final_text: str | None = None
    usage: UnifiedUsage = field(default_factory=UnifiedUsage)
    cost_usd: float | None = None
    session_id: str | None = None
    duration_ms: int | None = None
    structured_output: Any | None = None
    stop_reason: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class RawEvent:
    """Escape hatch: backend-native event that has no normalized mapping."""

    backend: str
    kind: str
    data: Any


AgentEvent = (
    SessionStarted
    | TextDelta
    | AssistantText
    | Reasoning
    | ToolCall
    | ToolResult
    | CommandRun
    | FileChanged
    | TurnCompleted
    | RawEvent
)
