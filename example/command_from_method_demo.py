"""Demo: expose one method on an object with command_from_method."""

from __future__ import annotations

import json
from typing import Annotated, Any

from agenticli import CommandRegistry, Option, command_from_method


class Counter:
    def __init__(self) -> None:
        self.total = 0

    def add(
        self,
        value: Annotated[int, Option(positional=True, value_name="value", description="Amount to add")],
    ) -> dict[str, int]:
        self.total += value
        return {"total": self.total}

    def reset(self) -> dict[str, int]:
        self.total = 0
        return {"total": self.total}


def build_registry() -> CommandRegistry:
    counter = Counter()
    registry = CommandRegistry()
    registry.register_spec(command_from_method("counter add", counter, "add", description="Add to the counter"))
    registry.register_spec(command_from_method("counter reset", counter, "reset", description="Reset the counter"))
    return registry


def execute_value(registry: CommandRegistry, command_text: str) -> Any:
    result = registry.execute(command_text)
    if isinstance(result, list):
        return result
    return result.value if result.ok else result.error.render()


def main() -> None:
    registry = build_registry()
    command_text = "counter add 2 ; counter add 3 ; counter reset"
    print(f"\n$ {command_text}")
    print(json.dumps(registry.execute(command_text, chain=True), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
