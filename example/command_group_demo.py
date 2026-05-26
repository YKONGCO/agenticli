"""Demo: define grouped commands with @command_group."""

from __future__ import annotations

import json
from typing import Annotated, Any

from agenticli import CommandRegistry, Option, command, command_group


@command_group(name="string", description="String manipulation commands")
class StringCommands:
    @command(name="upper", description="Convert text to uppercase")
    def upper(
        self,
        text: Annotated[str, Option(positional=True, value_name="text", description="Text to convert")],
    ) -> dict[str, str]:
        return {"result": text.upper()}

    @command(name="replace", description="Replace text")
    def replace(
        self,
        text: Annotated[str, Option(positional=True, value_name="text", description="Original text")],
        old: Annotated[str, Option(short="o", description="Text to replace")] = "",
        new: Annotated[str, Option(short="n", description="Replacement text")] = "",
    ) -> dict[str, str]:
        return {"result": text.replace(old, new)}


def build_registry() -> CommandRegistry:
    registry = CommandRegistry()
    registry.register(StringCommands)
    return registry


def execute_value(registry: CommandRegistry, command_text: str) -> Any:
    result = registry.execute(command_text)
    if isinstance(result, list):
        return result
    return result.value if result.ok else result.error.render()


def main() -> None:
    registry = build_registry()
    for command_text in ('string upper "hello world"', 'string replace "hello world" -o world -n agenticli'):
        print(f"\n$ {command_text}")
        print(json.dumps(execute_value(registry, command_text), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
