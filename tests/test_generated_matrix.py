from __future__ import annotations

import asyncio
from dataclasses import dataclass
from itertools import product
from typing import Annotated

import pytest

from agenticli import CliCommand, CommandRegistry, ExecutionCallbacks, Option, command, command_from_model, command_group, wrap_tool
from agenticli.validation import build_adapter


def execute_value(registry: CommandRegistry, command_text: str):
    result = registry.execute(command_text)
    assert not isinstance(result, list)
    return result.value if result.ok else result.error.render()


async def execute_value_async(registry: CommandRegistry, command_text: str):
    result = await registry.execute_async(command_text)
    assert not isinstance(result, list)
    return result.value if result.ok else result.error.render()


@command(name="coerce")
def coerce(
    count: Annotated[int, Option(short="n")],
    ratio: Annotated[float, Option(short="r")] = 1.0,
    enabled: Annotated[bool, Option(short="e")] = False,
) -> tuple[int, float, bool]:
    return count, ratio, enabled


@command(name="bags")
def bags(
    items: Annotated[list[int], Option(positional=True)],
    tags: Annotated[list[str] | None, Option(short="t", repeatable=True)] = None,
) -> tuple[list[int], list[str] | None]:
    return items, tags


@command(name="bounds")
def bounds(
    pair: Annotated[tuple[int, int], Option(short="p")],
) -> tuple[int, int]:
    return pair


@command(name="toggle")
def toggle(
    enabled: Annotated[bool, Option(short="e")],
) -> bool:
    return enabled


@command(name="sumlist")
def sumlist(
    items: Annotated[list[int], Option(positional=True)],
) -> list[int]:
    return items


async def _module_async_state(ctx) -> dict[str, str]:
    return {"raw": ctx.raw}


@command_group(name="calc", description="Generated test group")
class _CalcGroup:
    @command(name="add", description="Add two integers")
    def add(self, a: int, b: int) -> int:
        return a + b


def _coerce_cases() -> list[tuple[str, tuple[int, float, bool]]]:
    bool_forms = [
        ("--enabled", True),
        ("-e", True),
    ]
    count_forms = [
        ("--count 7", 7),
        ("--count=7", 7),
        ("-n 7", 7),
        ("-n7", 7),
    ]
    ratio_forms = [
        ("--ratio 2.5", 2.5),
        ("--ratio=2.5", 2.5),
        ("-r 2.5", 2.5),
        ("-r2.5", 2.5),
    ]
    cases: list[tuple[str, tuple[int, float, bool]]] = []
    for (count_text, count), (ratio_text, ratio), (bool_text, enabled) in product(count_forms, ratio_forms, bool_forms):
        command_text = f"coerce {count_text} {ratio_text} {bool_text}"
        cases.append((command_text, (count, ratio, enabled)))
    return cases


def _help_cases() -> list[tuple[str, str]]:
    return [
        ("calc --help", "Usage:\n  calc <subcommand> [args...]"),
        ("calc add --help", "calc add - Add two integers"),
        ("calc add -h", "calc add - Add two integers"),
        ("toggle --help", "Usage:\n  toggle --enabled"),
        ("toggle -h", "Usage:\n  toggle --enabled"),
        ("--help toggle", "Usage:\n  toggle --enabled"),
    ]


def _list_cases() -> list[tuple[str, object]]:
    return [
        ("bags 1 2 3", ([1, 2, 3], None)),
        ("bags 1 2 3 -t red -t blue", ([1, 2, 3], ["red", "blue"])),
    ]


class _SchemaTool:
    name = "schema-calc"
    description = "Schema tool with x-* metadata"
    parameters = {
        "type": "object",
        "properties": {
            "value": {
                "type": "number",
                "description": "primary value",
                "title": "number",
                "examples": ["42.5"],
                "x-order": 1,
            },
            "mode": {
                "type": "string",
                "enum": ["fast", "safe"],
                "x-hidden": True,
            },
            "flags": {
                "type": "array",
                "x-repeatable": True,
            },
            "pair": {
                "type": "array",
                "x-nargs": 2,
            },
        },
        "required": ["value"],
    }

    async def execute(self, **kwargs):
        return kwargs


@dataclass
class _InjectedArgs:
    value: Annotated[int, Option(positional=True)]
    trace: Annotated[object, Option(internal=True, inject="trace-token")] = None


class _InjectedCommand(CliCommand):
    name = "inject-model"
    description = "Dataclass injection command"
    args_model = _InjectedArgs

    async def run(self, **kwargs):
        return kwargs


def _build_registry() -> CommandRegistry:
    registry = CommandRegistry()
    registry.register(coerce)
    registry.register(bags)
    registry.register(bounds)
    registry.register(toggle)
    registry.register(sumlist)
    registry.register(_CalcGroup)
    registry.register_spec(wrap_tool(_SchemaTool()))
    registry.register(_InjectedCommand())
    return registry


@pytest.mark.parametrize(("command_text", "expected"), _coerce_cases())
def test_generated_numeric_and_flag_matrix(command_text: str, expected: tuple[int, float, bool]):
    registry = _build_registry()
    assert execute_value(registry, command_text) == expected


@pytest.mark.parametrize(("command_text", "expected"), _list_cases())
def test_generated_list_matrix(command_text: str, expected: object):
    registry = _build_registry()
    assert execute_value(registry, command_text) == expected


@pytest.mark.parametrize(
    ("command_text", "expected"),
    [
        ("bounds -p 1 2", (1, 2)),
    ],
)
def test_generated_tuple_input_matrix(command_text: str, expected: tuple[int, int]):
    registry = _build_registry()
    assert execute_value(registry, command_text) == expected


@pytest.mark.parametrize(("command_text", "snippet"), _help_cases())
def test_generated_help_forms(command_text: str, snippet: str):
    registry = _build_registry()
    assert snippet in execute_value(registry, command_text)


@pytest.mark.parametrize(
    ("token", "expected"),
    [("--enabled", True), ("-e", True)],
)
def test_generated_boolean_flag_matrix(token: str, expected: bool):
    registry = _build_registry()
    assert execute_value(registry, f"toggle {token}") is expected


def test_schema_tool_metadata_is_exposed_and_hidden_fields_stay_hidden():
    registry = _build_registry()

    help_text = execute_value(registry, "schema-calc --help")
    assert "Usage: schema-calc value" not in help_text
    assert "Usage:\n  schema-calc --value <number>" in help_text
    assert "example:42.5" in help_text
    assert "--mode" not in help_text

    result = execute_value(registry, "schema-calc --value 42.5 --flags a --flags b --pair 1 2 --mode safe")
    assert result == {"value": 42.5, "mode": "safe", "flags": ["a", "b"], "pair": ["1", "2"]}


def test_parse_and_match_unknown_inputs_and_unknown_help_target():
    registry = _build_registry()

    assert registry.parse("missing command") is None
    assert registry.match("/missing arg").command is None
    assert registry.match("plain natural language with no command").command is None
    assert registry.help("missing") == "Unknown command: missing"


def test_registry_get_and_empty_prompt_behaviors():
    empty_registry = CommandRegistry()
    assert empty_registry.get("missing") is None
    empty_prompt = empty_registry.render_llm_context()
    assert "You can use the following CLI commands:" in empty_prompt

    registry = _build_registry()
    assert registry.get("coerce") is not None
    assert registry.get("missing") is None


def test_dataclass_model_internal_injection_survives_command_from_model_and_class_command():
    registry = CommandRegistry()
    registry.register_spec(command_from_model("inject-fn", _InjectedArgs, lambda **kwargs: kwargs, description="inject fn"))
    registry.register(_InjectedCommand())

    assert execute_value(registry, "inject-fn 3") == {"value": 3, "trace": "trace-token"}
    assert execute_value(registry, "inject-model 4") == {"value": 4, "trace": "trace-token"}


def test_async_execution_callbacks_and_async_injection_factory_work():
    events: list[tuple[str, object]] = []

    async def before(ctx):
        events.append(("before", dict(ctx.args)))

    async def after(ctx):
        events.append(("after", ctx.result))

    async def on_error(ctx):
        events.append(("error", ctx.error.code if ctx.error else None))

    @command(name="async-deps")
    def async_deps(
        value: Annotated[int, Option(positional=True)],
        state: Annotated[object, Option(internal=True, inject_factory=_module_async_state)] = None,
    ) -> tuple[int, object]:
        return value, state

    registry = CommandRegistry(
        callbacks=ExecutionCallbacks(before_execute=before, after_execute=after, on_error=on_error)
    )
    registry.register(async_deps)

    assert execute_value(registry, "async-deps 9") == (9, {"raw": "async-deps 9"})
    assert execute_value(registry, "zzz 9") == "Error: Unknown command"
    assert events[0] == ("before", {"value": 9, "state": {"raw": "async-deps 9"}})
    assert events[1] == ("after", (9, {"raw": "async-deps 9"}))
    assert events[2] == ("error", "unknown_command")


def test_async_api_awaits_callbacks_and_injection_factory_without_sync_bridge():
    events: list[tuple[str, object]] = []

    async def before(ctx):
        events.append(("before", dict(ctx.args)))

    async def after(ctx):
        events.append(("after", ctx.result))

    @command(name="async-native")
    async def async_native(
        value: Annotated[int, Option(positional=True)],
        state: Annotated[object, Option(internal=True, inject_factory=_module_async_state)] = None,
    ) -> tuple[int, object]:
        return value, state

    registry = CommandRegistry(
        callbacks=ExecutionCallbacks(before_execute=before, after_execute=after)
    )
    registry.register(async_native)

    result = asyncio.run(execute_value_async(registry, "async-native 5"))
    assert result == (5, {"raw": "async-native 5"})
    assert events[0] == ("before", {"value": 5, "state": {"raw": "async-native 5"}})
    assert events[1] == ("after", (5, {"raw": "async-native 5"}))


def test_local_injection_factory_name_fails_under_future_annotations():
    async def _local_state(ctx) -> dict[str, str]:
        return {"raw": ctx.raw}

    with pytest.raises(NameError):
        @command(name="local-async-deps")
        def local_async_deps(
            value: Annotated[int, Option(positional=True)],
            state: Annotated[object, Option(internal=True, inject_factory=_local_state)] = None,
        ) -> tuple[int, object]:
            return value, state


@pytest.mark.parametrize(
    ("raw_args", "expected"),
    [
        ({"enabled": "true"}, {"enabled": True}),
        ({"enabled": "false"}, {"enabled": False}),
        ({"enabled": "yes"}, {"enabled": True}),
        ({"enabled": "off"}, {"enabled": False}),
        ({"enabled": "1"}, {"enabled": True}),
        ({"enabled": "0"}, {"enabled": False}),
    ],
)
def test_generated_validator_boolean_string_matrix(raw_args: dict[str, str], expected: dict[str, bool]):
    adapter = build_adapter(toggle)
    assert adapter.validate(raw_args) == expected


@pytest.mark.parametrize(
    ("target", "raw_args", "expected"),
    [
        (bounds, {"pair": "[1,2]"}, {"pair": (1, 2)}),
        (bounds, {"pair": "1,2"}, {"pair": (1, 2)}),
        (sumlist, {"items": "[1,2,3]"}, {"items": [1, 2, 3]}),
        (sumlist, {"items": "1,2,3"}, {"items": [1, 2, 3]}),
    ],
)
def test_generated_validator_collection_string_matrix(target, raw_args: dict[str, str], expected: dict[str, object]):
    adapter = build_adapter(target)
    assert adapter.validate(raw_args) == expected

