"""Calculator commands — discovered by example.discover."""
from __future__ import annotations

from typing import Annotated

from agenticli import Option, command, command_group


@command_group(name="calc", description="Calculator commands")
class Calc:
    @command(name="add", description="Add two numbers")
    def add(self, a: int, b: int) -> dict[str, int]:
        return {"result": a + b}

    @command(name="multiply", description="Multiply two numbers")
    def multiply(self, a: int, b: int) -> dict[str, int]:
        return {"result": a * b}
