import asyncio
import time

import pytest

from unified_agent.agent import SuperAgent, UnifiedAgent
from unified_agent.events import (
    AssistantText,
    FileChanged,
    SessionStarted,
    ToolCall,
    TurnCompleted,
)
from unified_agent.types import BackendUnavailableError, UnifiedUsage


class FakeBackend:
    name = "fake"

    def __init__(self, events=None, delay=0.0, fail_with=None, fake_name="fake"):
        self.name = fake_name
        self.events = events or []
        self.delay = delay
        self.fail_with = fail_with
        self.seen_prompts = []
        self.seen_opts = []

    async def stream(self, prompt, opts):
        self.seen_prompts.append(prompt)
        self.seen_opts.append(opts)
        if self.delay:
            await asyncio.sleep(self.delay)
        for ev in self.events:
            yield ev
        if self.fail_with:
            raise self.fail_with


GOOD_EVENTS = [
    SessionStarted(session_id="s-1"),
    AssistantText("working on it"),
    ToolCall(name="mcp__unified__add_numbers", input={"a": 1, "b": 2}, call_id="c1"),
    FileChanged(path="out.txt", kind="add"),
    TurnCompleted(
        success=True,
        final_text="all done",
        usage=UnifiedUsage(input_tokens=10, output_tokens=5),
        cost_usd=0.01,
        session_id="s-1",
        duration_ms=123,
    ),
]


def make_agent(tmp_path, backend) -> UnifiedAgent:
    return UnifiedAgent(backend=backend, workspace=tmp_path / "ws")


async def test_run_collects_unified_result(tmp_path):
    backend = FakeBackend(events=GOOD_EVENTS)
    agent = make_agent(tmp_path, backend)
    result = await agent.run("do the thing")
    assert result.success is True
    assert result.backend == "fake"
    assert result.text == "all done"
    assert result.usage.input_tokens == 10
    assert result.cost_usd == 0.01
    assert result.session_id == "s-1"
    assert [t.name for t in result.tool_calls] == ["mcp__unified__add_numbers"]
    assert [f.path for f in result.file_changes] == ["out.txt"]
    assert len(result.events) == len(GOOD_EVENTS)
    assert result.error is None


async def test_run_text_falls_back_to_last_assistant_text(tmp_path):
    events = [AssistantText("a"), AssistantText("b"), TurnCompleted(success=True)]
    result = await make_agent(tmp_path, FakeBackend(events=events)).run("x")
    assert result.text == "b"


async def test_prompt_rendered_for_backend_name(tmp_path):
    backend = FakeBackend(events=GOOD_EVENTS, fake_name="codex")
    agent = make_agent(tmp_path, backend)
    from unified_agent.task import Task

    await agent.run(Task(instruction="go", skill="my-skill"))
    assert "$my-skill" in backend.seen_prompts[0]


async def test_run_failure_returns_result_not_exception(tmp_path):
    backend = FakeBackend(events=[AssistantText("partial")], fail_with=RuntimeError("boom"))
    result = await make_agent(tmp_path, backend).run("x")
    assert result.success is False
    assert "boom" in result.error
    assert result.text == "partial"  # falls back to last assistant text


async def test_stream_propagates_exception(tmp_path):
    backend = FakeBackend(fail_with=RuntimeError("boom"))
    agent = make_agent(tmp_path, backend)
    with pytest.raises(RuntimeError):
        async for _ in agent.stream("x"):
            pass


async def test_run_options_carry_configuration(tmp_path):
    backend = FakeBackend(events=GOOD_EVENTS)
    agent = UnifiedAgent(
        backend=backend,
        workspace=tmp_path / "ws",
        model="some-model",
        instructions="be terse",
        effort="xhigh",
    )
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    await agent.run("t", output_schema=schema, resume="sess-9", max_turns=3)
    opts = backend.seen_opts[0]
    assert opts.model == "some-model"
    assert opts.instructions == "be terse"
    assert opts.effort == "xhigh"
    assert opts.output_schema == schema
    assert opts.resume == "sess-9"
    assert opts.max_turns == 3
    assert opts.workspace == (tmp_path / "ws").resolve()
    assert (tmp_path / "ws").is_dir()  # created by prepare


async def test_tools_and_skills_prepared_once(tmp_path):
    from unified_agent.skills import make_skill

    skills_src = tmp_path / "skills"
    make_skill(skills_src, "alpha-skill", "Does alpha.", "Body")
    backend = FakeBackend(events=GOOD_EVENTS)
    agent = UnifiedAgent(
        backend=backend,
        workspace=tmp_path / "ws",
        tools="tests.fixture_registry:REG",
        skills_dir=skills_src,
    )
    await agent.run("a")
    await agent.run("b")
    opts = backend.seen_opts[0]
    assert opts.tool_server is not None
    assert opts.tool_server.server_name == "unified"
    assert (tmp_path / "ws" / ".claude" / "skills" / "alpha-skill").exists()
    assert (tmp_path / "ws" / ".agents" / "skills" / "alpha-skill").exists()


def test_unknown_backend_name_raises():
    with pytest.raises(BackendUnavailableError):
        UnifiedAgent(backend="gemini")


def test_run_sync(tmp_path):
    backend = FakeBackend(events=GOOD_EVENTS)
    result = make_agent(tmp_path, backend).run_sync("x")
    assert result.success


async def test_superagent_runs_all_concurrently(tmp_path):
    a = UnifiedAgent(
        backend=FakeBackend(events=GOOD_EVENTS, delay=0.2, fake_name="a"), workspace=tmp_path / "wa"
    )
    b = UnifiedAgent(
        backend=FakeBackend(events=GOOD_EVENTS, delay=0.2, fake_name="b"), workspace=tmp_path / "wb"
    )
    squad = SuperAgent({"a": a, "b": b})
    t0 = time.monotonic()
    results = await squad.run_all("same task")
    elapsed = time.monotonic() - t0
    assert set(results) == {"a", "b"}
    assert all(r.success for r in results.values())
    assert elapsed < 0.35, f"not concurrent: {elapsed:.2f}s"


async def test_superagent_run_one_and_subset(tmp_path):
    a = UnifiedAgent(
        backend=FakeBackend(events=GOOD_EVENTS, fake_name="a"), workspace=tmp_path / "wa"
    )
    b = UnifiedAgent(
        backend=FakeBackend(events=GOOD_EVENTS, fake_name="b"), workspace=tmp_path / "wb"
    )
    squad = SuperAgent({"a": a, "b": b})
    r = await squad.run("a", "task")
    assert r.backend == "a"
    only_b = await squad.run_all("task", only=["b"])
    assert set(only_b) == {"b"}
