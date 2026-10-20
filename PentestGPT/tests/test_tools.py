import os
import sys

import pytest

from tests.fixture_registry import REG
from unified_agent.tools import (
    ToolRegistry,
    build_tool_server_spec,
    registry_spec,
    resolve_registry,
)
from unified_agent.types import ToolRegistryError


def test_registration_keeps_fn_callable_and_lists_tools():
    names = [e.name for e in REG.tools]
    assert names == ["add_numbers", "echo_upper"]
    from tests.fixture_registry import add_numbers

    assert add_numbers(2, 3) == "2 + 3 = 5"


def test_default_description_from_docstring_first_line():
    entry = {e.name: e for e in REG.tools}["add_numbers"]
    assert entry.description == "Add two numbers and return the sum."


def test_duplicate_name_rejected():
    reg = ToolRegistry("unified")

    @reg.tool()
    def alpha() -> str:
        """A."""
        return "a"

    with pytest.raises(ToolRegistryError, match="duplicate"):

        @reg.tool(name="alpha", description="again")
        def alpha2() -> str:
            return "b"


@pytest.mark.parametrize("bad", ["Add", "add-nums", "9x", "_x", ""])
def test_invalid_tool_names_rejected(bad):
    reg = ToolRegistry("unified")
    with pytest.raises(ToolRegistryError):

        @reg.tool(name=bad, description="d")
        def f() -> str:
            return "x"


def test_missing_description_rejected():
    reg = ToolRegistry("unified")
    with pytest.raises(ToolRegistryError, match="description"):

        @reg.tool()
        def nodoc() -> str:
            return "x"


def test_fully_qualified_length_capped_at_64():
    reg = ToolRegistry("unified")  # mcp__unified__ = 13 chars -> tool max 51
    with pytest.raises(ToolRegistryError, match="64"):

        @reg.tool(name="t" * 52, description="d")
        def long_tool() -> str:
            return "x"


def test_invalid_server_name_rejected():
    with pytest.raises(ToolRegistryError):
        ToolRegistry("My-Server")


def test_registry_spec_roundtrip():
    spec = registry_spec(REG)
    assert spec == "tests.fixture_registry:REG"
    assert resolve_registry(spec) is REG


def test_registry_spec_rejects_main_module():
    reg = ToolRegistry("unified")
    reg._defining_module = "__main__"
    with pytest.raises(ToolRegistryError, match="importable"):
        registry_spec(reg)


def test_resolve_registry_bad_specs():
    with pytest.raises(ToolRegistryError):
        resolve_registry("no-colon")
    with pytest.raises(ToolRegistryError):
        resolve_registry("tests.fixture_registry:NOPE")
    with pytest.raises(ToolRegistryError):
        resolve_registry("tests.fixture_registry:add_numbers")  # not a registry


def test_build_tool_server_spec_command_and_env(tmp_path):
    spec = build_tool_server_spec(REG, extra_env={"FOO": "bar"})
    assert spec.server_name == "unified"
    assert spec.command[0] == sys.executable
    assert spec.command[1:3] == ["-m", "unified_agent.tool_server"]
    assert spec.command[3] == "tests.fixture_registry:REG"
    paths = spec.env["PYTHONPATH"].split(os.pathsep)
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert repo_root in paths  # root of tests.fixture_registry
    assert any(os.path.isdir(os.path.join(p, "unified_agent")) for p in paths)
    assert spec.env["FOO"] == "bar"
