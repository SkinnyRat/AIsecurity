import sys

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from unified_agent.backends.claude_code import (
    ClaudeCodeBackend,
    build_options,
    normalize_message,
)
from unified_agent.events import (
    AssistantText,
    Reasoning,
    SessionStarted,
    TextDelta,
    ToolCall,
    ToolResult,
    TurnCompleted,
)
from unified_agent.types import (
    AgentAuthError,
    RunOptions,
    SandboxPolicy,
    ToolServerError,
    ToolServerSpec,
)


def opts(tmp_path, **kw) -> RunOptions:
    return RunOptions(workspace=tmp_path, **kw)


TOOL_SERVER = ToolServerSpec(
    server_name="unified",
    command=[sys.executable, "-m", "unified_agent.tool_server", "tests.fixture_registry:REG"],
    env={"PYTHONPATH": "/repo"},
)


# --- option mapping -------------------------------------------------------


def test_read_only_policy_maps_to_dontask_and_no_write_tools(tmp_path):
    o = build_options(opts(tmp_path, sandbox=SandboxPolicy.READ_ONLY))
    assert o.permission_mode == "dontAsk"
    assert "Read" in o.allowed_tools and "Bash" not in o.allowed_tools
    assert set(o.disallowed_tools) >= {"Write", "Edit", "Bash"}
    assert o.cwd == str(tmp_path)
    assert o.setting_sources == ["project"]


def test_workspace_write_policy_maps_to_acceptedits_with_bash(tmp_path):
    o = build_options(opts(tmp_path, sandbox=SandboxPolicy.WORKSPACE_WRITE))
    assert o.permission_mode == "acceptEdits"
    assert {"Bash", "Write", "Edit", "Read"} <= set(o.allowed_tools)
    assert o.disallowed_tools == []


def test_full_access_policy_maps_to_bypass(tmp_path):
    o = build_options(opts(tmp_path, sandbox=SandboxPolicy.FULL_ACCESS))
    assert o.permission_mode == "bypassPermissions"


def test_tool_server_becomes_stdio_mcp_config_and_allowlist(tmp_path):
    o = build_options(opts(tmp_path, tool_server=TOOL_SERVER))
    cfg = o.mcp_servers["unified"]
    assert cfg["type"] == "stdio"
    assert cfg["command"] == sys.executable
    assert cfg["args"][0:2] == ["-m", "unified_agent.tool_server"]
    assert cfg["env"] == {"PYTHONPATH": "/repo"}
    assert "mcp__unified__*" in o.allowed_tools


def test_instructions_append_to_claude_code_preset(tmp_path):
    o = build_options(opts(tmp_path, instructions="be terse"))
    assert o.system_prompt == {
        "type": "preset",
        "preset": "claude_code",
        "append": "be terse",
    }


def test_effort_passthrough(tmp_path):
    assert build_options(opts(tmp_path, effort="xhigh")).effort == "xhigh"
    assert build_options(opts(tmp_path)).effort is None


def test_default_keeps_native_claude_code_system_prompt(tmp_path):
    """Regression: system_prompt=None strips Claude Code's system prompt entirely
    (including working-directory context), making file ops land outside the
    workspace. The agent unit must always run with the native preset."""
    o = build_options(opts(tmp_path))
    assert o.system_prompt == {"type": "preset", "preset": "claude_code"}


def test_output_schema_and_passthroughs(tmp_path):
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}}
    o = build_options(
        opts(
            tmp_path,
            output_schema=schema,
            resume="sess-1",
            max_turns=4,
            model="claude-opus-4-8",
            extra_env={"X": "1"},
            stream_text=True,
        )
    )
    assert o.output_format == {"type": "json_schema", "schema": schema}
    assert o.resume == "sess-1"
    assert o.max_turns == 4
    assert o.model == "claude-opus-4-8"
    assert o.env == {"X": "1"}
    assert o.include_partial_messages is True


# --- message normalization ------------------------------------------------


def norm(msg, tmp_path, **kw):
    return list(normalize_message(msg, opts(tmp_path, **kw)))


def test_init_system_message_yields_session_started(tmp_path):
    msg = SystemMessage(
        subtype="init",
        data={"session_id": "s-9", "mcp_servers": [{"name": "unified", "status": "connected"}]},
    )
    events = norm(msg, tmp_path, tool_server=TOOL_SERVER)
    assert events == [SessionStarted(session_id="s-9")]


def test_failed_tool_server_raises(tmp_path):
    msg = SystemMessage(
        subtype="init",
        data={"session_id": "s", "mcp_servers": [{"name": "unified", "status": "failed"}]},
    )
    with pytest.raises(ToolServerError, match="unified"):
        norm(msg, tmp_path, tool_server=TOOL_SERVER)


def test_assistant_blocks_normalize(tmp_path):
    msg = AssistantMessage(
        content=[
            ThinkingBlock(thinking="hmm", signature="sig"),
            TextBlock(text="hello"),
            ToolUseBlock(id="t1", name="mcp__unified__add_numbers", input={"a": 1, "b": 2}),
        ],
        model="claude-opus-4-8",
    )
    events = norm(msg, tmp_path)
    assert events == [
        Reasoning(text="hmm"),
        AssistantText(text="hello"),
        ToolCall(name="mcp__unified__add_numbers", input={"a": 1, "b": 2}, call_id="t1"),
    ]


def test_auth_error_raises(tmp_path):
    msg = AssistantMessage(content=[], model="m", error="authentication_failed")
    with pytest.raises(AgentAuthError):
        norm(msg, tmp_path)


def test_tool_result_in_user_message(tmp_path):
    msg = UserMessage(content=[ToolResultBlock(tool_use_id="t1", content="3.0", is_error=False)])
    events = norm(msg, tmp_path)
    assert events == [ToolResult(call_id="t1", output="3.0", is_error=False)]


def test_result_message_maps_to_turn_completed(tmp_path):
    msg = ResultMessage(
        subtype="success",
        duration_ms=1500,
        duration_api_ms=900,
        is_error=False,
        num_turns=3,
        session_id="s-9",
        total_cost_usd=0.0123,
        usage={
            "input_tokens": 100,
            "cache_read_input_tokens": 40,
            "output_tokens": 25,
        },
        result="done!",
        structured_output={"n": 1},
    )
    [event] = norm(msg, tmp_path)
    assert isinstance(event, TurnCompleted)
    assert event.success is True
    assert event.final_text == "done!"
    assert event.usage.input_tokens == 100
    assert event.usage.cached_input_tokens == 40
    assert event.usage.output_tokens == 25
    assert event.cost_usd == 0.0123
    assert event.session_id == "s-9"
    assert event.duration_ms == 1500
    assert event.structured_output == {"n": 1}
    assert event.stop_reason == "success"


def test_error_result_message(tmp_path):
    msg = ResultMessage(
        subtype="error_max_turns",
        duration_ms=10,
        duration_api_ms=5,
        is_error=True,
        num_turns=9,
        session_id="s",
        errors=["ran out of turns"],
    )
    [event] = norm(msg, tmp_path)
    assert event.success is False
    assert "ran out of turns" in event.error


def test_stream_event_text_delta_only_when_enabled(tmp_path):
    ev = {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "he"}}
    msg = StreamEvent(uuid="u", session_id="s", event=ev, parent_tool_use_id=None)
    assert norm(msg, tmp_path, stream_text=True) == [TextDelta(text="he")]
    assert norm(msg, tmp_path, stream_text=False) == []


def test_backend_name():
    assert ClaudeCodeBackend().name == "claude"
