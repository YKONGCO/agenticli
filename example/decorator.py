"""Demo: define commands with the @command decorator."""

from __future__ import annotations

import json
from typing import Annotated, Any

from agenticli import CommandRegistry, Option, command


@command(name="hello", description="Say hello to someone")
def hello(
    name: Annotated[str, Option(short="n", description="Name to greet")],
    loud: Annotated[bool, Option(short="l", description="Uppercase output")] = False,
) -> dict[str, str]:
    message = f"Hello, {name}!"
    return {"message": message.upper() if loud else message}


@command(name="add", description="Add numbers")
def add(
    values: Annotated[
        list[float],
        Option(positional=True, value_name="number", description="Numbers to add", example="add 1 2 3"),
    ],
) -> dict[str, Any]:
    return {"values": values, "result": sum(values)}


def build_registry() -> CommandRegistry:
    registry = CommandRegistry()
    registry.register(hello)
    registry.register(add)
    return registry


def execute_value(registry: CommandRegistry, command_text: str) -> Any:
    result = registry.execute(command_text)
    if isinstance(result, list):
        return result
    return result.value if result.ok else result.error.render()


def main() -> None:
    registry = build_registry()
    for command_text in ('hello -n Alice', 'hello --name Bob --loud', "add 1 2 3"):
        print(f"\n$ {command_text}")
        print(json.dumps(execute_value(registry, command_text), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
