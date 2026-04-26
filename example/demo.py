"""Combined provider demo using one shared calc command system."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Annotated, Any, Literal

from agenticli import Callback, CommandRegistry, ExecTool, ExecutionCallbacks, Option, State, command, command_group


def _noop(_: str) -> None:
    return None


@command_group(name="calc", description="Structured calculator commands for LLM tool calling")
class CalcCommands:
    @command(name="add", description="Add a sequence of numbers")
    def add(
        self,
        values: Annotated[list[float], Option(positional=True, value_name="value", example="calc add 10 20 30 40")],
    ) -> dict[str, object]:
        return {"operation": "add", "values": values, "result": sum(values)}

    @command(name="mean", description="Compute the arithmetic mean")
    def mean(
        self,
        values: Annotated[list[float], Option(positional=True, value_name="value", example="calc mean 10 20 30 -p 3")],
        precision: Annotated[int, Option(short="p", value_name="digits", description="decimal digits")] = 2,
    ) -> dict[str, object]:
        mean_value = sum(values) / len(values)
        return {
            "operation": "mean",
            "values": values,
            "precision": precision,
            "result": round(mean_value, precision),
        }

    @command(name="dot", description="Compute the dot product of two vectors")
    def dot(
        self,
        left: Annotated[
            list[float],
            Option(
                short="l",
                value_name="json",
                description="left vector as JSON array",
                example='calc dot -l "[1,2,3]" -r "[4,5,6]"',
            ),
        ],
        right: Annotated[
            list[float],
            Option(short="r", value_name="json", description="right vector as JSON array"),
        ],
    ) -> dict[str, object]:
        if len(left) != len(right):
            raise ValueError("left and right vectors must have the same length")
        return {
            "operation": "dot",
            "left": left,
            "right": right,
            "result": sum(a * b for a, b in zip(left, right, strict=False)),
        }

    @command(name="affine", description="Apply scale and offset to a value")
    def affine(
        self,
        value: Annotated[float, Option(positional=True, value_name="value", example="calc affine 10 -s 1.5 -o 2 -c 0 20 -p 2")],
        scale: Annotated[float, Option(short="s", description="scale factor")] = 1.0,
        offset: Annotated[float, Option(short="o", description="offset")] = 0.0,
        clamp: Annotated[
            tuple[float, float] | None,
            Option(short="c", value_name="min max", description="optional clamp range"),
        ] = None,
        precision: Annotated[int, Option(short="p", value_name="digits", description="decimal digits")] = 2,
    ) -> dict[str, object]:
        result = value * scale + offset
        if clamp is not None:
            low, high = clamp
            result = min(max(result, low), high)
        return {
            "operation": "affine",
            "value": value,
            "scale": scale,
            "offset": offset,
            "clamp": clamp,
            "precision": precision,
            "result": round(result, precision),
        }

    @command(name="stats", description="Summarize a dataset")
    def stats(
        self,
        values: Annotated[list[float], Option(positional=True, value_name="value", example="calc stats 10 20 30 40 --mode full -p 3")],
        mode: Annotated[Literal["basic", "full"], Option(description="summary depth")] = "basic",
        precision: Annotated[int, Option(short="p", value_name="digits", description="decimal digits")] = 2,
        callback: Annotated[object, Callback()] = _noop,
        state: Annotated[object, State(factory=lambda ctx: {"command": ctx.command, "raw": ctx.raw})] = None,
    ) -> dict[str, object]:
        state = state or {"command": "calc stats", "raw": "calc stats"}
        callback(f"[calc.stats] raw={state['raw']}")
        total = sum(values)
        count = len(values)
        mean_value = total / count
        result: dict[str, object] = {
            "operation": "stats",
            "mode": mode,
            "count": count,
            "sum": round(total, precision),
            "mean": round(mean_value, precision),
            "min": min(values),
            "max": max(values),
        }
        if mode == "full":
            variance = sum((value - mean_value) ** 2 for value in values) / count
            result["variance"] = round(variance, precision)
        result["context"] = state
        return result


def build_registry(*, with_lifecycle_logs: bool = False) -> CommandRegistry:
    if not with_lifecycle_logs:
        registry = CommandRegistry()
        registry.register(CalcCommands)
        return registry

    def before(ctx) -> None:
        print(f"[before] command={ctx.command} args={ctx.args}")

    def after(ctx) -> None:
        print(f"[after] result={ctx.result}")

    registry = CommandRegistry(callbacks=ExecutionCallbacks(before_execute=before, after_execute=after))
    registry.register(CalcCommands)
    return registry


def build_openai_tools(exec_tool: ExecTool) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": exec_tool.name,
                "description": exec_tool.description,
                "parameters": exec_tool.parameters,
            },
        }
    ]


def build_openai_functions(exec_tool: ExecTool) -> list[dict[str, Any]]:
    return [
        {
            "name": exec_tool.name,
            "description": exec_tool.description,
            "parameters": exec_tool.parameters,
        }
    ]


def extract_openai_function_calls(message: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    tool_calls = getattr(message, "tool_calls", None) or []
    for tool_call in tool_calls:
        func = getattr(tool_call, "function", None) or {}
        calls.append(
            {
                "call_id": getattr(tool_call, "id", ""),
                "name": getattr(func, "name", ""),
                "arguments": json.loads(getattr(func, "arguments", "{}") or "{}"),
            }
        )
    if calls:
        return calls

    function_call = getattr(message, "function_call", None)
    if function_call:
        calls.append(
            {
                "call_id": "function_call_0",
                "name": getattr(function_call, "name", ""),
                "arguments": json.loads(getattr(function_call, "arguments", "{}") or "{}"),
            }
        )
    return calls


def build_openai_tool_messages(calls: list[dict[str, Any]], outputs: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "role": "tool",
            "tool_call_id": call["call_id"],
            "content": json.dumps(output, ensure_ascii=False),
        }
        for call, output in zip(calls, outputs, strict=False)
    ]


def build_openai_function_messages(calls: list[dict[str, Any]], outputs: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "role": "function",
            "name": call["name"],
            "content": json.dumps(output, ensure_ascii=False),
        }
        for call, output in zip(calls, outputs, strict=False)
    ]


def build_anthropic_tools(exec_tool: ExecTool) -> list[dict[str, Any]]:
    return [
        {
            "name": exec_tool.name,
            "description": exec_tool.description,
            "input_schema": exec_tool.parameters,
        }
    ]


def extract_anthropic_tool_uses(message: Any) -> list[dict[str, Any]]:
    uses: list[dict[str, Any]] = []
    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", None) != "tool_use":
            continue
        uses.append(
            {
                "id": getattr(block, "id", ""),
                "name": getattr(block, "name", ""),
                "input": getattr(block, "input", {}) or {},
            }
        )
    return uses


def build_anthropic_tool_results(tool_uses: list[dict[str, Any]], outputs: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "type": "tool_result",
            "tool_use_id": tool_use["id"],
            "content": json.dumps(output, ensure_ascii=False),
        }
        for tool_use, output in zip(tool_uses, outputs, strict=False)
    ]


async def run_openai_demo() -> None:
    from openai import OpenAI

    api_key = os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("OPENAI_BASE_URL")
    model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
    
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for example/demo.py --provider openai")

    registry = build_registry()
    exec_tool = ExecTool(callback=registry.parse_and_execute)
    tools = [exec_tool.to_schema()]
    client = OpenAI(api_key=api_key, base_url=base_url)

    messages = [
        {
            "role": "user",
            "content": (
                "调用exec 工具执行 calc 命令, 可以用calc --help 来查看具体内容"
            ),
        }
    ]
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        tools=tools,
        tool_choice="auto",
        max_tokens=1024,
    )

    message = response.choices[0].message
    calls = extract_openai_function_calls(message)
    if not calls:
        print(message.content)
        return

    outputs: list[Any] = []
    for call in calls:
        if call["name"] != exec_tool.name:
            continue
        outputs.append(await exec_tool.execute(**call["arguments"]))

    messages.append(message.model_dump(exclude_none=True))
    messages.extend(build_openai_tool_messages(calls, outputs))
    followup = client.chat.completions.create(model=model, messages=messages, tools=tools, tool_choice="auto", max_tokens=1024)
    print(followup.choices[0].message.content)


async def run_anthropic_demo() -> None:
    from anthropic import Anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    model = os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is required for example/demo.py --provider anthropic")

    registry = build_registry(with_lifecycle_logs=True)
    exec_tool = ExecTool(callback=registry.parse_and_execute)
    tools = build_anthropic_tools(exec_tool)
    prompt = '调用exec 工具执行 calc 命令, 可以用calc --help 来查看具体内容'
    client = Anthropic(api_key=api_key, base_url=base_url)

    message = client.messages.create(
        model=model,
        max_tokens=1024,
        tools=tools,
        messages=[{"role": "user", "content": prompt}],
    )

    tool_uses = extract_anthropic_tool_uses(message)
    if not tool_uses:
        print(getattr(message, "content", []))
        return

    outputs: list[Any] = []
    for tool_use in tool_uses:
        if tool_use["name"] != exec_tool.name:
            continue
        outputs.append(await exec_tool.execute(**tool_use["input"]))

    followup = client.messages.create(
        model=model,
        max_tokens=1024,
        tools=tools,
        messages=[
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": message.content},
            {"role": "user", "content": build_anthropic_tool_results(tool_uses, outputs)},
        ],
    )
    print(getattr(followup, "content", []))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the shared llmcli calc demo against a provider SDK.")
    parser.add_argument(
        "--provider",
        choices=("openai", "anthropic"),
        default="openai",
        help="Select which SDK/provider demo to run.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    if args.provider == "openai":
        asyncio.run(run_openai_demo())
        return
    asyncio.run(run_anthropic_demo())


if __name__ == "__main__":
    main()
