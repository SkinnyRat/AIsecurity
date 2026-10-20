"""unified_agent: drive OpenAI Codex and Claude Code as one agent unit.

Same task input, same Python tools (over stdio MCP), same Agent Skills,
same normalized events/results — on either backend, or both at once.
"""

from .agent import SuperAgent, UnifiedAgent, collect
from .events import (
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
from .skills import Skill, discover_skills, install_skills, lint_skill, load_skill, make_skill
from .task import Task
from .tools import ToolRegistry, build_tool_server_spec, registry_spec, resolve_registry
from .types import (
    AgentAuthError,
    AgentRunError,
    BackendUnavailableError,
    RunOptions,
    SandboxPolicy,
    SkillError,
    ToolRegistryError,
    ToolServerError,
    ToolServerSpec,
    UnifiedAgentError,
    UnifiedResult,
    UnifiedUsage,
)

__version__ = "0.1.0"

__all__ = [
    "AgentAuthError",
    "AgentEvent",
    "AgentRunError",
    "AssistantText",
    "BackendUnavailableError",
    "CommandRun",
    "FileChanged",
    "RawEvent",
    "Reasoning",
    "RunOptions",
    "SandboxPolicy",
    "SessionStarted",
    "Skill",
    "SkillError",
    "SuperAgent",
    "Task",
    "TextDelta",
    "ToolCall",
    "ToolRegistry",
    "ToolRegistryError",
    "ToolResult",
    "ToolServerError",
    "ToolServerSpec",
    "TurnCompleted",
    "UnifiedAgent",
    "UnifiedAgentError",
    "UnifiedResult",
    "UnifiedUsage",
    "build_tool_server_spec",
    "collect",
    "discover_skills",
    "install_skills",
    "lint_skill",
    "load_skill",
    "make_skill",
    "registry_spec",
    "resolve_registry",
]
