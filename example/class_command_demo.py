"""Demo: define commands by subclassing CliCommand."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Annotated, Any

from agenticli import CliCommand, CommandRegistry, Option


@dataclass
class RepeatInput:
    text: Annotated[str, Option(description="Text to repeat")]
    times: Annotated[int, Option(short="n", description="Number of repetitions")] = 2


class RepeatCommand(CliCommand):
    name = "repeat"
    description = "Repeat text a fixed number of times"
    args_model = RepeatInput

    async def run(self, text: str, times: int = 2) -> dict[str, Any]:
        return {"text": text, "times": times, "result": text * times}


def build_registry() -> CommandRegistry:
    registry = CommandRegistry()
    registry.register(RepeatCommand)
    return registry


def execute_value(registry: CommandRegistry, command_text: str) -> Any:
    result = registry.execute(command_text)
    if isinstance(result, list):
        return result
    return result.value if result.ok else result.error.render()


def main() -> None:
    registry = build_registry()
    for command_text in ('repeat --text ha', 'repeat --text go -n 3'):
        print(f"\n$ {command_text}")
        print(json.dumps(execute_value(registry, command_text), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
