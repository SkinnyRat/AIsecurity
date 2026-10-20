"""Importable registry fixture used by tool/agent tests and the stdio round-trip."""

from unified_agent.tools import ToolRegistry

REG = ToolRegistry("unified")


@REG.tool()
def add_numbers(a: float, b: float) -> str:
    """Add two numbers and return the sum."""
    return f"{a} + {b} = {a + b}"


@REG.tool(name="echo_upper", description="Echo a string in upper case.")
async def shout(text: str) -> str:
    return text.upper()
