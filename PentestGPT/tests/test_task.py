from pathlib import Path

import pytest

from unified_agent.task import Task


def test_instruction_only_render_is_instruction():
    t = Task(instruction="Fix the bug.")
    assert t.render("claude") == "Fix the bug."
    assert t.render("codex") == "Fix the bug."


def test_context_file_embedded_with_header(tmp_path: Path):
    readme = tmp_path / "README.md"
    readme.write_text("# Proj\n\nHello world.")
    out = Task(instruction="Summarize.", context_files=[readme]).render("claude")
    assert "## Context file: README.md" in out
    assert "Hello world." in out
    assert out.index("Summarize.") < out.index("## Context file")


def test_extra_context_appended():
    out = Task(instruction="Do it.", context="prefer tabs").render("codex")
    assert "## Additional context" in out
    assert "prefer tabs" in out


def test_skill_hint_renders_per_backend():
    t = Task(instruction="Report.", skill="word-count-report")
    codex = t.render("codex")
    claude = t.render("claude")
    assert "$word-count-report" in codex
    assert "'word-count-report' skill" in claude
    assert "Skill tool" in claude
    assert "$word-count-report" not in claude


def test_missing_context_file_raises():
    with pytest.raises(FileNotFoundError):
        Task(instruction="x", context_files=["/nonexistent/zz.txt"]).render("claude")


def test_huge_file_truncated(tmp_path: Path):
    big = tmp_path / "big.txt"
    big.write_text("x" * 250_000)
    out = Task(instruction="go", context_files=[big]).render("codex")
    assert "[... truncated ...]" in out
    assert len(out) < 220_000


def test_coerce_str_and_task_passthrough():
    t = Task(instruction="hi")
    assert Task.coerce(t) is t
    c = Task.coerce("hello")
    assert isinstance(c, Task) and c.instruction == "hello"
