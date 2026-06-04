"""Demo: control which commands/groups are exposed to the LLM prompt.

Some commands are useful for human operators (admin reset, interactive
prompts) but you do not want the LLM to suggest them. Use
``include_in_prompt=False`` to keep the command callable and visible in
``help()`` while hiding its description from ``render_llm_context()``.
"""

from __future__ import annotations

import json
from typing import Any

from agenticli import CommandRegistry, command, command_group


@command(name="greet", description="Greet someone")
def greet(name: str = "World") -> dict[str, str]:
    return {"message": f"Hello, {name}!"}


@command(name="reset", description="Reset the world state (admin only)", include_in_prompt=False)
def reset() -> dict[str, bool]:
    return {"reset": True}


@command(name="backup", description="Create a backup snapshot", include_in_prompt=False)
def backup() -> dict[str, bool]:
    return {"backup": True}


@command_group(name="ops", description="Operations menu", include_in_prompt=False)
class Ops:
    @command(name="deploy", description="Deploy a build")
    def deploy(self) -> dict[str, bool]:
        return {"deployed": True}

    @command(name="rollback", description="Roll back the last deploy")
    def rollback(self) -> dict[str, bool]:
        return {"rolled_back": True}


@command_group(name="reports", description="Reporting menu")
class Reports:
    @command(name="daily", description="Show daily report")
    def daily(self) -> dict[str, str]:
        return {"report": "daily"}

    @command(name="secret", description="Internal audit report", include_in_prompt=False)
    def secret(self) -> dict[str, str]:
        return {"report": "secret"}


def build_registry() -> CommandRegistry:
    registry = CommandRegistry()
    registry.register(greet)
    registry.register(reset)
    registry.register(backup)
    registry.register(Ops)
    registry.register(Reports)
    return registry


def execute_value(registry: CommandRegistry, command_text: str) -> Any:
    result = registry.execute(command_text)
    if isinstance(result, list):
        return result
    return result.value if result.ok else result.error.render()


def main() -> None:
    registry = build_registry()

    print("\n=== Help listing (CLI side: everything visible) ===")
    print(registry.help())

    print("\n=== LLM context (prompt side: hidden commands/groups absent) ===")
    print(registry.render_llm_context())

    print("\n=== Hidden commands are still executable ===")
    for command_text in ("reset", "backup", "ops deploy", "reports secret"):
        print(f"\n$ {command_text}")
        print(json.dumps(execute_value(registry, command_text), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
