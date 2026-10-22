"""Unified task input: one instruction/context envelope rendered per backend."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

MAX_FILE_CHARS = 200_000


@dataclass
class Task:
    """The same input for every backend.

    instruction   -- what to do (plain text)
    context_files -- README / docs / source files inlined into the prompt
    context       -- extra free-form context text
    skill         -- name of an installed skill to invoke explicitly; rendered
                     as a `$name` mention for Codex and as a Skill-tool hint
                     for Claude Code (each host's native trigger syntax)
    """

    instruction: str
    context_files: Sequence[str | Path] = ()
    context: str | None = None
    skill: str | None = None

    @classmethod
    def coerce(cls, task: Task | str) -> Task:
        return task if isinstance(task, Task) else cls(instruction=str(task))

    def render(self, backend: str) -> str:
        parts = [self.instruction.strip()]
        for f in self.context_files:
            path = Path(f)
            text = path.read_text(encoding="utf-8", errors="replace")
            if len(text) > MAX_FILE_CHARS:
                text = text[:MAX_FILE_CHARS] + "\n[... truncated ...]"
            parts.append(f"## Context file: {path.name}\n\n{text}")
        if self.context:
            parts.append(f"## Additional context\n\n{self.context}")
        if self.skill:
            if backend == "codex":
                parts.append(f"Use the ${self.skill} skill for this task.")
            else:
                parts.append(
                    f"Use the '{self.skill}' skill for this task (invoke it with the Skill tool)."
                )
        return "\n\n".join(parts)
