"""Demo: expose a dataclass model plus a handler with command_from_model."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Annotated, Any

from agenticli import CommandRegistry, Option, command_from_model


@dataclass
class ScaleInput:
    value: Annotated[float, Option(positional=True, value_name="value", description="Input value")]
    factor: Annotated[float, Option(short="f", description="Scale factor")] = 1.0
    offset: Annotated[float, Option(short="o", description="Offset after scaling")] = 0.0


def scale(value: float, factor: float = 1.0, offset: float = 0.0) -> dict[str, float]:
    return {"value": value, "factor": factor, "offset": offset, "result": value * factor + offset}


def build_registry() -> CommandRegistry:
    registry = CommandRegistry()
    registry.register_spec(command_from_model("scale", ScaleInput, scale, description="Scale a numeric value"))
    return registry


def execute_value(registry: CommandRegistry, command_text: str) -> Any:
    result = registry.execute(command_text)
    if isinstance(result, list):
        return result
    return result.value if result.ok else result.error.render()


def main() -> None:
    registry = build_registry()
    for command_text in ("scale 10", "scale 10 -f 1.5 -o 2"):
        print(f"\n$ {command_text}")
        print(json.dumps(execute_value(registry, command_text), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
