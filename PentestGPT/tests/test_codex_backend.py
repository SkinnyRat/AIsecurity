import json
import sys
from types import SimpleNamespace as NS

import pytest
from openai_codex import Sandbox

from unified_agent.backends.codex import (
    CodexBackend,
    _TurnState,
    build_config_overrides,
    build_thread_kwargs,
    build_turn_kwargs,
    normalize_notification,
)
from unified_agent.events import (
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
from unified_agent.types import RunOptions, SandboxPolicy, ToolServerSpec


def opts(tmp_path, **kw) -> RunOptions:
    return RunOptions(workspace=tmp_path, **kw)


TOOL_SERVER = ToolServerSpec(
    server_name="unified",
    command=[sys.executable, "-m", "unified_agent.tool_server", "tests.fixture_registry:REG"],
    env={"PYTHONPATH": "/re po"},  # space exercises TOML string quoting
)


# --- config / thread option mapping ----------------------------------------


def test_config_overrides_define_the_mcp_server_inline():
    overrides = build_config_overrides(TOOL_SERVER)
    joined = "\n".join(overrides)
    assert f"mcp_servers.unified.command={json.dumps(sys.executable)}" in overrides
    args_line = next(o for o in overrides if ".args=" in o)
    assert json.loads(args_line.split("=", 1)[1]) == [
        "-m",
        "unified_agent.tool_server",
        "tests.fixture_registry:REG",
    ]
    env_line = next(o for o in overrides if ".env=" in o)
    assert env_line == 'mcp_servers.unified.env={ "PYTHONPATH" = "/re po" }'
    assert "mcp_servers.unified.startup_timeout_sec=30" in joined
    assert "mcp_servers.unified.tool_timeout_sec=120" in joined
    assert "mcp_servers.unified.required=true" in joined
    assert 'mcp_servers.unified.default_tools_approval_mode="auto"' in joined


@pytest.mark.parametrize(
    "policy,expected",
    [
        (SandboxPolicy.READ_ONLY, Sandbox.read_only),
        (SandboxPolicy.WORKSPACE_WRITE, Sandbox.workspace_write),
        (SandboxPolicy.FULL_ACCESS, Sandbox.full_access),
    ],
)
def test_thread_kwargs_sandbox_mapping(tmp_path, policy, expected):
    kw = build_thread_kwargs(opts(tmp_path, sandbox=policy))
    assert kw["sandbox"] is expected
    assert kw["cwd"] == str(tmp_path)


def test_thread_kwargs_passthroughs(tmp_path):
    kw = build_thread_kwargs(opts(tmp_path, model="gpt-5.5", instructions="be terse"))
    assert kw["model"] == "gpt-5.5"
    assert kw["developer_instructions"] == "be terse"
    kw2 = build_thread_kwargs(opts(tmp_path))
    assert "model" not in kw2 and "developer_instructions" not in kw2


def test_turn_kwargs_effort_mapping(tmp_path):
    from openai_codex.generated.v2_all import ReasoningEffort

    kw = build_turn_kwargs(opts(tmp_path, effort="xhigh"))
    assert kw["effort"] is ReasoningEffort.xhigh
    assert build_turn_kwargs(opts(tmp_path)) == {"output_schema": None}


def test_turn_kwargs_invalid_effort(tmp_path):
    from unified_agent.types import AgentRunError

    with pytest.raises(AgentRunError, match="effort"):
        build_turn_kwargs(opts(tmp_path, effort="max"))  # claude-only level


# --- notification normalization ---------------------------------------------


def fresh_state(tmp_path, **kw) -> _TurnState:
    return _TurnState(opts=opts(tmp_path, **kw))


def norm(method, payload, state):
    return list(normalize_notification(method, payload, state))


def test_thread_started_announces_session_once(tmp_path):
    state = fresh_state(tmp_path)
    events = norm("thread/started", NS(thread=NS(id="thr-1")), state)
    assert events == [SessionStarted(session_id="thr-1")]
    assert norm("thread/started", NS(thread=NS(id="thr-1")), state) == []


def test_agent_message_item(tmp_path):
    state = fresh_state(tmp_path)
    item = NS(root=NS(type="agentMessage", text="hello there", id="i1"))
    events = norm("item/completed", NS(item=item), state)
    assert events == [AssistantText(text="hello there")]
    assert state.last_agent_text == "hello there"


def test_reasoning_item_prefers_summary(tmp_path):
    state = fresh_state(tmp_path)
    item = NS(root=NS(type="reasoning", summary=["thought hard"], content=[], id="i2"))
    assert norm("item/completed", NS(item=item), state) == [Reasoning(text="thought hard")]


def test_command_execution_item(tmp_path):
    state = fresh_state(tmp_path)
    item = NS(
        root=NS(
            type="commandExecution",
            command="ls -la",
            exit_code=0,
            aggregated_output="total 0",
            status="completed",
            id="i3",
        )
    )
    assert norm("item/completed", NS(item=item), state) == [
        CommandRun(command="ls -la", exit_code=0, output="total 0")
    ]


def test_mcp_tool_call_item(tmp_path):
    state = fresh_state(tmp_path)
    item = NS(
        root=NS(
            type="mcpToolCall",
            server="unified",
            tool="add_numbers",
            arguments='{"a": 2, "b": 3}',
            result=NS(content=[NS(type="text", text="2 + 3 = 5")], structured_content=None),
            error=None,
            status="completed",
            id="i4",
        )
    )
    call, result = norm("item/completed", NS(item=item), state)
    assert call == ToolCall(name="mcp__unified__add_numbers", input={"a": 2, "b": 3}, call_id="i4")
    assert isinstance(result, ToolResult)
    assert "5" in result.output and result.is_error is False


def test_failed_mcp_tool_call_marks_error(tmp_path):
    state = fresh_state(tmp_path)
    item = NS(
        root=NS(
            type="mcpToolCall",
            server="unified",
            tool="boom",
            arguments=None,
            result=None,
            error=NS(message="exploded"),
            status="failed",
            id="i5",
        )
    )
    _call, result = norm("item/completed", NS(item=item), state)
    assert result.is_error is True
    assert "exploded" in result.output


def test_file_change_item(tmp_path):
    state = fresh_state(tmp_path)
    item = NS(
        root=NS(
            type="fileChange",
            status="completed",
            changes=[NS(path="a.txt", kind="add"), NS(path="b.txt", kind="update")],
            id="i6",
        )
    )
    assert norm("item/completed", NS(item=item), state) == [
        FileChanged(path="a.txt", kind="add"),
        FileChanged(path="b.txt", kind="update"),
    ]


def test_agent_message_delta_gated_by_stream_text(tmp_path):
    on = fresh_state(tmp_path, stream_text=True)
    off = fresh_state(tmp_path, stream_text=False)
    assert norm("item/agentMessage/delta", NS(delta="he"), on) == [TextDelta(text="he")]
    assert norm("item/agentMessage/delta", NS(delta="he"), off) == []


def test_token_usage_tracked_then_reported_on_turn_completed(tmp_path):
    state = fresh_state(tmp_path)
    usage = NS(
        total=NS(
            input_tokens=100,
            cached_input_tokens=40,
            output_tokens=9,
            reasoning_output_tokens=3,
            total_tokens=112,
        ),
        last=None,
        model_context_window=None,
    )
    assert norm("thread/tokenUsage/updated", NS(token_usage=usage, turn_id="t"), state) == []
    state.thread_id = "thr-1"
    state.last_agent_text = "final answer"
    turn = NS(id="t", status="completed", error=None)
    [event] = norm("turn/completed", NS(turn=turn, thread_id="thr-1"), state)
    assert isinstance(event, TurnCompleted)
    assert event.success is True
    assert event.final_text == "final answer"
    assert event.usage.input_tokens == 100
    assert event.usage.cached_input_tokens == 40
    assert event.usage.reasoning_output_tokens == 3
    assert event.session_id == "thr-1"
    assert event.cost_usd is None


def test_turn_failed_with_error_notification(tmp_path):
    state = fresh_state(tmp_path)
    norm("error", NS(error=NS(message="rate limited"), will_retry=False), state)
    turn = NS(id="t", status=NS(value="failed"), error=NS(message="turn died"))
    [event] = norm("turn/completed", NS(turn=turn), state)
    assert event.success is False
    assert "turn died" in event.error and "rate limited" in event.error


def test_structured_output_parsed_from_final_text(tmp_path):
    state = fresh_state(tmp_path, output_schema={"type": "object"})
    state.last_agent_text = '{"n": 42}'
    turn = NS(id="t", status="completed", error=None)
    [event] = norm("turn/completed", NS(turn=turn), state)
    assert event.structured_output == {"n": 42}


def test_unknown_notification_becomes_raw_event(tmp_path):
    state = fresh_state(tmp_path)
    [event] = norm("guardianWarning", NS(anything=1), state)
    assert isinstance(event, RawEvent)
    assert event.kind == "guardianWarning"


def test_backend_name():
    assert CodexBackend().name == "codex"
