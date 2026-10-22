"""Backend protocol: anything that streams normalized events for a prompt."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from ..events import AgentEvent
from ..types import RunOptions


@runtime_checkable
class AgentBackend(Protocol):
    """One agent unit (Claude Code, Codex, or a fake in tests)."""

    name: str

    def stream(self, prompt: str, opts: RunOptions) -> AsyncIterator[AgentEvent]:
        """Run one turn and yield normalized events; must end with TurnCompleted."""
        ...
