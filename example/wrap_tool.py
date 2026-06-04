"""Demo: wrap existing tool objects and schemas as commands."""

from __future__ import annotations

import json
from typing import Any

from agenticli import CommandRegistry, wrap_openai_tool_schema, wrap_tool


class WeatherTool:
    name = "weather"
    description = "Return mock weather for a city"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name"},
                "unit": {"type": "string", "description": "Temperature unit", "enum": ["celsius", "fahrenheit"]},
            },
            "required": ["city"],
        }

    def execute(self, city: str, unit: str = "celsius") -> dict[str, Any]:
        temperature = 22 if unit == "celsius" else 72
        return {"city": city, "unit": unit, "temperature": temperature}


def translate(text: str, target: str = "zh") -> dict[str, str]:
    return {"text": text, "target": target, "translated": f"[{target}] {text}"}


def build_registry() -> CommandRegistry:
    registry = CommandRegistry()
    registry.register_spec(wrap_tool(WeatherTool()))
    registry.register_spec(
        wrap_openai_tool_schema(
            name="translate",
            description="Mock translation tool from an OpenAI-style schema",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to translate"},
                    "target": {"type": "string", "description": "Target language", "default": "zh"},
                },
                "required": ["text"],
            },
            handler=translate,
        )
    )
    return registry


def execute_value(registry: CommandRegistry, command_text: str) -> Any:
    result = registry.execute(command_text)
    if isinstance(result, list):
        return result
    return result.value if result.ok else result.error.render()


def main() -> None:
    registry = build_registry()
    for command_text in ('weather --city Beijing --unit celsius', 'translate --text "hello" --target ja'):
        print(f"\n$ {command_text}")
        print(json.dumps(execute_value(registry, command_text), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
