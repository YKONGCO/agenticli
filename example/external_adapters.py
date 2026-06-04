"""Demo: wrap LangChain-like and AutoGen-like tool shapes.

No external dependencies are required here. The classes below mimic the small
interface surface that agenticli expects from those frameworks.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Annotated
from typing import Any

from agenticli import CommandRegistry, Option, wrap_autogen_tool, wrap_langchain_tool


@dataclass
class LangChainEchoInput:
    text: Annotated[str, Option(description="Text to echo")]
    upper: Annotated[bool, Option(description="Uppercase output")] = False


class LangChainLikeTool:
    name = "lc_echo"
    description = "LangChain-like echo tool"
    args_schema = LangChainEchoInput

    def invoke(self, data: dict[str, Any]) -> dict[str, str]:
        text = data["text"]
        return {"echo": text.upper() if data.get("upper") else text}


class AutoGenLikeTool:
    schema = {
        "name": "ag_join",
        "description": "AutoGen-like join tool",
        "parameters": {
            "type": "object",
            "properties": {
                "left": {"type": "string", "description": "Left text"},
                "right": {"type": "string", "description": "Right text"},
                "sep": {"type": "string", "description": "Separator", "default": "-"},
            },
            "required": ["left", "right"],
        },
    }

    def run_json(self, data: dict[str, Any], cancellation_token: Any = None) -> dict[str, str]:
        return {"joined": f"{data['left']}{data.get('sep', '-')}{data['right']}"}


def build_registry() -> CommandRegistry:
    registry = CommandRegistry()
    registry.register_spec(wrap_langchain_tool(LangChainLikeTool()))
    registry.register_spec(wrap_autogen_tool(AutoGenLikeTool()))
    return registry


def execute_value(registry: CommandRegistry, command_text: str) -> Any:
    result = registry.execute(command_text)
    if isinstance(result, list):
        return result
    return result.value if result.ok else result.error.render()


def main() -> None:
    registry = build_registry()
    for command_text in ('lc_echo --text hello --upper', 'ag_join --left agent --right cli --sep /'):
        print(f"\n$ {command_text}")
        print(json.dumps(execute_value(registry, command_text), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
