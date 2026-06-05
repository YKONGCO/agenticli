from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from dataclasses import dataclass
from importlib.util import find_spec
from typing import Annotated, Literal

import pytest

from agenticli import (
    Callback,
    CliCommand,
    CommandError,
    CommandRegistry,
    CommandSpec,
    ExecTool,
    ExecutionCallbacks,
    Injected,
    Option,
    State,
    command,
    command_from_method,
    command_from_model,
    command_group,
    wrap_tool,
)
from agenticli.parser import CommandParser
from agenticli.commands import CliCommand as NativeCliCommand
from agenticli.adapters import wrap_autogen_tool, wrap_langchain_tool, wrap_openai_tool_schema, wrap_tool as native_wrap_tool


def execute_value(registry: CommandRegistry, command_text: str):
    result = registry.execute(command_text)
    assert not isinstance(result, list)
    return result.value if result.ok else result.error.render()


async def execute_value_async(registry: CommandRegistry, command_text: str):
    result = await registry.execute_async(command_text)
    assert not isinstance(result, list)
    return result.value if result.ok else result.error.render()


@command(name="weather", description="Get the weather for a city", aliases=["wx"])
def weather(
    city: Annotated[str, Option(description="target city", positional=True)],
    unit: Annotated[str, Option(short="u", description="temperature unit")] = "celsius",
    verbose: Annotated[bool, Option(short="v", description="verbose flag")] = False,
) -> str:
    return f"{city}:{unit}:{verbose}"


@command_group(name="calc", description="Calculator")
class Calculator:
    @command(name="add", description="Add two numbers")
    def add(self, a: int, b: int) -> int:
        return a + b

    @command(name="mul", description="Multiply two numbers")
    def mul(self, a: int, b: int) -> int:
        return a * b


@dataclass
class ExecArgs:
    command: Annotated[str, Option(description="command text", positional=True)]
    timeout: Annotated[int, Option(short="t", description="timeout seconds")] = 60
    sandbox: Annotated[bool, Option(short="s", description="sandbox mode")] = False


class ExecCommand(CliCommand):
    name = "exec"
    description = "Execute a command through the registry"
    args_model = ExecArgs

    async def run(self, **kwargs):
        return kwargs


class DummyTool:
    name = "search"
    description = "Search with a JSON schema backed tool"
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "search terms"},
            "count": {"type": "integer", "default": 5},
            "filters": {"type": "object"},
            "tags": {"type": "array"},
        },
        "required": ["query"],
    }

    async def execute(self, **kwargs):
        return kwargs


@command(name="mode", description="Mode selector")
def mode_select(
    name: Annotated[str, Option(positional=True, description="resource name")],
    mode: Literal["fast", "safe"] = "fast",
) -> str:
    return f"{name}:{mode}"


@command(name="legacy", description="Legacy command", deprecated="use weather instead")
def legacy() -> str:
    return "legacy"


@command(name="internal", description="Internal command", hidden=True)
def internal() -> str:
    return "internal"


def test_positional_argument_and_short_flag_compact_shape():
    registry = CommandRegistry()
    registry.register(weather)

    result = execute_value(registry, 'weather "Beijing" -u fahrenheit -v')
    assert result == "Beijing:fahrenheit:True"


def test_long_option_equals_and_short_compact_value():
    registry = CommandRegistry()
    registry.register(weather)

    assert execute_value(registry, "weather Shanghai --unit=kelvin") == "Shanghai:kelvin:False"
    assert execute_value(registry, "weather Shanghai -ukelvin") == "Shanghai:kelvin:False"


def test_alias_command_executes_same_spec():
    registry = CommandRegistry()
    registry.register(weather)

    assert execute_value(registry, "wx Shenzhen") == "Shenzhen:celsius:False"


def test_group_command_supports_multiple_subcommands():
    registry = CommandRegistry()
    registry.register(Calculator)

    assert execute_value(registry, "calc add 2 3") == 5
    assert execute_value(registry, "calc mul 4 5") == 20


def test_class_command_uses_dataclass_validation_and_defaults():
    registry = CommandRegistry()
    registry.register(ExecCommand())

    result = execute_value(registry, "exec pytest -t 30 -s")
    assert result == {"command": "pytest", "timeout": 30, "sandbox": True}


def test_command_from_model_builds_validated_command():
    registry = CommandRegistry()
    registry.register_spec(command_from_model("runner", ExecArgs, lambda **kwargs: kwargs, description="Run command"))

    assert execute_value(registry, "runner uv") == {"command": "uv", "timeout": 60, "sandbox": False}


def test_command_from_method_wraps_single_class_method_only():
    class Worker:
        def execute(self, task: str, count: int = 1) -> tuple[str, int]:
            return task, count

        def helper(self) -> str:
            return "helper"

    registry = CommandRegistry()
    registry.register_spec(command_from_method("work", Worker, method_name="execute", description="Run one worker method"))

    assert execute_value(registry, "work demo --count 2") == ("demo", 2)
    assert registry.has("helper") is False


def test_execution_callbacks_observe_before_after_and_error():
    events: list[tuple[str, str, object]] = []

    def before(ctx):
        events.append(("before", ctx.command, dict(ctx.args)))

    def after(ctx):
        events.append(("after", ctx.command, ctx.result))

    def on_error(ctx):
        events.append(("error", ctx.command, ctx.error.code if ctx.error else None))

    registry = CommandRegistry(callbacks=ExecutionCallbacks(before_execute=before, after_execute=after, on_error=on_error))
    registry.register(weather)

    assert execute_value(registry, "weather Beijing") == "Beijing:celsius:False"
    assert execute_value(registry, "wether Beijing") == "Error: Unknown command. Did you mean 'weather'?"

    assert events[0] == ("before", "weather", {"city": "Beijing", "unit": "celsius", "verbose": False})
    assert events[1] == ("after", "weather", "Beijing:celsius:False")
    assert events[2] == ("error", "wether", "unknown_command")


def test_internal_injected_callback_param_is_not_registered_or_parsed():
    events: list[str] = []

    def cb(value: str) -> None:
        events.append(value)

    @command(name="notify")
    def notify(
        name: Annotated[str, Option(positional=True)],
        callback: Annotated[object, Option(internal=True)] = cb,
    ) -> str:
        callback(name)
        return name

    registry = CommandRegistry()
    registry.register(notify)

    help_text = execute_value(registry, "notify --help")
    assert "callback" not in help_text
    assert execute_value(registry, "notify alice") == "alice"
    assert events == ["alice"]
    assert "unknown option: --callback" in execute_value(registry, "notify alice --callback nope")


def test_injected_helper_aliases_work_for_callback_and_state():
    seen: list[tuple[str, object]] = []

    def cb(value: str) -> None:
        seen.append(("callback", value))

    @command(name="deps")
    def deps(
        name: Annotated[str, Option(positional=True)],
        callback: Annotated[object, Callback()] = cb,
        state: Annotated[object, State(factory=lambda ctx: {"command": ctx.command, "raw": ctx.raw})] = None,
        helper: Annotated[object, Injected(value="helper")] = None,
    ) -> tuple[str, dict[str, str], str]:
        callback(name)
        return name, state, helper

    registry = CommandRegistry()
    registry.register(deps)

    result = execute_value(registry, "deps alice")
    assert result == ("alice", {"command": "deps", "raw": "deps alice"}, "helper")
    assert seen == [("callback", "alice")]
    help_text = execute_value(registry, "deps --help")
    assert "callback" not in help_text
    assert "state" not in help_text
    assert "helper" not in help_text


def test_wrap_tool_parses_object_and_array_json_arguments():
    registry = CommandRegistry()
    registry.register_spec(wrap_tool(DummyTool()))

    result = execute_value(registry, 
        'search --query llm --count 3 --filters "{\\"lang\\": \\"zh\\"}" --tags "[\\"a\\", \\"b\\"]"'
    )
    assert result == {"query": "llm", "count": 3, "filters": {"lang": "zh"}, "tags": ["a", "b"]}


def test_literal_annotation_validates_enum_values():
    registry = CommandRegistry()
    registry.register(mode_select)

    assert execute_value(registry, "mode worker --mode safe") == "worker:safe"
    assert "must be one of" in execute_value(registry, "mode worker --mode risky")
    assert "Did you mean 'safe'?" in execute_value(registry, "mode worker --mode sae")


def test_help_prefers_command_local_form_and_shows_short_aliases():
    registry = CommandRegistry()
    registry.register(weather)

    help_text = execute_value(registry, "weather --help")
    assert "Usage:\n  weather <city> [--unit <unit>] [--verbose]" in help_text
    assert "-u,--unit unit" in help_text
    assert "-v,--verbose flag" in help_text
    assert "Aliases:" in help_text


def test_help_shows_example_and_custom_value_name():
    @command(name="fetch")
    def fetch(
        query: Annotated[str, Option(positional=True, value_name="query", example="OpenAI latest")],
    ) -> str:
        return query

    registry = CommandRegistry()
    registry.register(fetch)

    help_text = execute_value(registry, "fetch --help")
    assert "Usage:\n  fetch <query>" in help_text
    assert "example:OpenAI latest" in help_text


def test_parameter_order_and_position_control_usage_and_parsing():
    @command(name="ordered")
    def ordered(
        first: Annotated[str, Option(positional=True, position=0, value_name="first")],
        second: Annotated[str, Option(positional=True, position=1, value_name="second")],
        tail: Annotated[str, Option(short="t", order=5, value_name="tail")] = "x",
        head: Annotated[str, Option(short="h", order=1, value_name="head")] = "y",
    ) -> tuple[str, str, str, str]:
        return first, second, head, tail

    registry = CommandRegistry()
    registry.register(ordered)

    help_text = execute_value(registry, "ordered --help")
    assert "Usage:\n  ordered <first> <second> [--head <head>] [--tail <tail>]" in help_text
    assert execute_value(registry, "ordered a b -h H -t T") == ("a", "b", "H", "T")


def test_hidden_parameter_is_not_shown_but_still_parses():
    @command(name="hiddenarg")
    def hiddenarg(
        visible: Annotated[str, Option(positional=True)],
        token: Annotated[str, Option(hidden=True)] = "secret",
    ) -> tuple[str, str]:
        return visible, token

    registry = CommandRegistry()
    registry.register(hiddenarg)

    help_text = execute_value(registry, "hiddenarg --help")
    assert "--token" not in help_text
    assert execute_value(registry, "hiddenarg shown --token exposed") == ("shown", "exposed")


def test_optional_list_and_repeatable_option_support():
    @command(name="tags")
    def tags(
        name: Annotated[str, Option(positional=True)],
        tag: Annotated[list[str] | None, Option(short="t", repeatable=True)] = None,
    ) -> tuple[str, list[str] | None]:
        return name, tag

    registry = CommandRegistry()
    registry.register(tags)

    assert execute_value(registry, "tags item -t red -t blue") == ("item", ["red", "blue"])


def test_optional_dict_support():
    @command(name="meta")
    def meta(
        name: Annotated[str, Option(positional=True)],
        payload: dict[str, str] | None = None,
    ) -> tuple[str, dict[str, str] | None]:
        return name, payload

    registry = CommandRegistry()
    registry.register(meta)

    assert execute_value(registry, 'meta item --payload "{\\"a\\": \\"1\\"}"') == ("item", {"a": "1"})


def test_tuple_and_fixed_arity_option_support():
    @command(name="range")
    def range_cmd(
        pair: Annotated[tuple[int, int], Option(short="p")],
    ) -> tuple[int, int]:
        return pair

    registry = CommandRegistry()
    registry.register(range_cmd)

    assert execute_value(registry, "range -p 1 2") == (1, 2)
    assert "missing value for option: -p" in execute_value(registry, "range -p 1")


def test_repeatable_positional_list_support():
    @command(name="collect")
    def collect(items: Annotated[list[str], Option(positional=True)]) -> list[str]:
        return items

    registry = CommandRegistry()
    registry.register(collect)

    assert execute_value(registry, "collect a b c") == ["a", "b", "c"]


def test_parameter_requires_other_parameter():
    @command(name="auth")
    def auth(
        user: Annotated[str | None, Option()] = None,
        password: Annotated[str | None, Option(requires=("user",))] = None,
    ) -> tuple[str | None, str | None]:
        return user, password

    registry = CommandRegistry()
    registry.register(auth)

    assert execute_value(registry, "auth --user alice --password secret") == ("alice", "secret")
    assert "password requires user" in execute_value(registry, "auth --password secret")


def test_parameter_excludes_other_parameter():
    @command(name="mode2")
    def mode2(
        fast: Annotated[bool, Option(excludes=("safe",))] = False,
        safe: bool = False,
    ) -> tuple[bool, bool]:
        return fast, safe

    registry = CommandRegistry()
    registry.register(mode2)

    assert execute_value(registry, "mode2 --fast") == (True, False)
    assert "fast cannot be used with safe" in execute_value(registry, "mode2 --fast --safe")


def test_help_still_supports_global_form():
    registry = CommandRegistry()
    registry.register(weather)

    assert "Usage:\n  weather <city> [--unit <unit>] [--verbose]" in execute_value(registry, "--help weather")


def test_help_for_subcommand_works():
    registry = CommandRegistry()
    registry.register(Calculator)

    help_text = execute_value(registry, "calc add --help")
    assert "calc add - Add two numbers" in help_text


def test_group_help_lists_subcommands():
    registry = CommandRegistry()
    registry.register(Calculator)

    help_text = execute_value(registry, "calc --help")
    assert "Usage:\n  calc <subcommand> [args...]" in help_text
    assert "Subcommands:" in help_text
    assert "add:" in help_text
    assert "mul:" in help_text


def test_group_without_subcommand_returns_group_help():
    registry = CommandRegistry()
    registry.register(Calculator)

    help_text = execute_value(registry, "calc")
    assert "Usage:\n  calc <subcommand> [args...]" in help_text
    assert "Subcommands:" in help_text


def test_parse_returns_help_parse_result_for_command_help():
    registry = CommandRegistry()
    registry.register(weather)

    parsed = registry.parse("weather --help")
    assert parsed is not None
    assert parsed.command == "--help"
    assert parsed.args == {"command": "weather"}


def test_parse_supports_normal_command():
    registry = CommandRegistry()
    registry.register(weather)

    parsed = registry.parse("weather Beijing -u fahrenheit")
    assert parsed is not None
    assert parsed.command == "weather"
    assert parsed.args == {"city": "Beijing", "unit": "fahrenheit"}
    assert parsed.errors == []


def test_parse_preserves_quoted_argument_with_spaces():
    registry = CommandRegistry()
    registry.register(weather)

    parsed = registry.parse('weather "New York" --unit fahrenheit')

    assert parsed is not None
    assert parsed.args == {"city": "New York", "unit": "fahrenheit"}
    assert parsed.errors == []


def test_command_parser_parse_tokens_matches_string_parse():
    parser = CommandParser(weather.__command_spec__.args)

    parsed = parser.parse_tokens(["weather", "New York", "--unit", "fahrenheit"], raw='weather "New York" --unit fahrenheit')

    assert parsed.command == "weather"
    assert parsed.args == {"city": "New York", "unit": "fahrenheit"}
    assert parsed.raw == 'weather "New York" --unit fahrenheit'
    assert parsed.errors == []


def test_execute_preserves_quoted_argument_with_spaces():
    registry = CommandRegistry()
    registry.register(weather)

    result = execute_value(registry, 'weather "New York" --unit fahrenheit')

    assert result == "New York:fahrenheit:False"


def test_execute_preserves_mixed_quotes_and_escaped_quotes():
    @command(name="say")
    def say(text: Annotated[str, Option(positional=True)]) -> str:
        return text

    registry = CommandRegistry()
    registry.register(say)

    assert execute_value(registry, """say "arg with \\"nested\\" quotes" """) == 'arg with "nested" quotes'
    assert execute_value(registry, """say "a'b'c" """) == "a'b'c"
    assert execute_value(registry, """say 'single quoted text' """) == "single quoted text"


def test_parse_preprocesses_backslash_line_continuation():
    registry = CommandRegistry()
    registry.register(weather)

    parsed = registry.parse("weather Beijing \\\n-u fahrenheit")

    assert parsed is not None
    assert parsed.args == {"city": "Beijing", "unit": "fahrenheit"}
    assert parsed.errors == []


def test_parse_preprocesses_backslash_line_continuation_to_space():
    @command(name="collect")
    def collect(items: Annotated[list[str], Option(positional=True)]) -> list[str]:
        return items

    registry = CommandRegistry()
    registry.register(collect)

    assert execute_value(registry, "collect hello\\\nworld") == ["hello", "world"]


def test_parse_combines_backslash_continuation_with_quoted_arguments():
    registry = CommandRegistry()
    registry.register(weather)

    parsed = registry.parse('weather "New York" \\\n--unit fahrenheit')

    assert parsed is not None
    assert parsed.args == {"city": "New York", "unit": "fahrenheit"}
    assert parsed.errors == []


def test_execute_async_preprocesses_crlf_backslash_line_continuation():
    registry = CommandRegistry()
    registry.register(weather)

    result = asyncio.run(registry.execute_async("weather Beijing \\\r\n -u fahrenheit"))

    assert result.ok is True
    assert result.value == "Beijing:fahrenheit:False"


def test_detect_natural_language_hit():
    registry = CommandRegistry()
    registry.register(weather)

    hit = registry.match("please run weather for beijing", mode="natural")
    assert hit.command == "weather"
    assert hit.confidence > 0


def test_match_exact_prefix_and_slash():
    registry = CommandRegistry()
    registry.register(weather)

    exact = registry.match("weather Beijing")
    prefix = registry.match("wea Beijing")
    slash = registry.match("/wea Beijing")

    assert exact.match_type == "exact"
    assert prefix.match_type == "prefix"
    assert slash.match_type == "slash"


def test_match_false_for_plain_text():
    registry = CommandRegistry()
    registry.register(weather)

    assert registry.match("tell me the weather").confidence == 0


def test_help_lists_top_level_commands_without_duplicates():
    registry = CommandRegistry()
    registry.register(weather)
    registry.register(Calculator)
    registry.register(internal)
    registry.register(legacy)

    help_text = registry.help()
    assert help_text.count("weather:") == 1
    assert "calc:" in help_text
    assert "internal:" not in help_text
    assert "[deprecated]" in help_text


def test_render_llm_context_detailed_and_minimal():
    registry = CommandRegistry()
    registry.register(weather)
    registry.register(internal)
    registry.register(legacy)

    minimal = registry.render_llm_context()
    detailed = registry.render_llm_context(detailed=True)

    assert "weather:" in minimal
    assert "weather <city>" in detailed
    assert "internal" not in minimal
    assert "[deprecated]" in minimal


def test_unregister_removes_alias_and_primary():
    registry = CommandRegistry()
    registry.register(weather)
    registry.unregister("weather")

    assert registry.has("weather") is False
    assert registry.has("wx") is False


def test_register_conflict_on_duplicate_name_or_alias():
    registry = CommandRegistry()
    registry.register(weather)

    @command(name="weather")
    def weather2(city: str) -> str:
        return city

    @command(name="wind", aliases=["wx"])
    def wind(city: str) -> str:
        return city

    try:
        registry.register(weather2)
    except ValueError as exc:
        assert "command already registered" in str(exc)
    else:
        raise AssertionError("expected duplicate command registration to fail")

    try:
        registry.register(wind)
    except ValueError as exc:
        assert "alias already registered" in str(exc)
    else:
        raise AssertionError("expected duplicate alias registration to fail")


def test_register_conflict_on_duplicate_group_name_or_subcommand_name():
    registry = CommandRegistry()
    registry.register(Calculator)

    @command_group(name="calc")
    class AnotherCalculator:
        @command(name="add")
        def add(self, a: int, b: int) -> int:
            return a + b

    try:
        registry.register(AnotherCalculator)
    except ValueError as exc:
        assert "command already registered: calc" in str(exc)
    else:
        raise AssertionError("expected duplicate group registration to fail")


def test_commands_property_and_contains():
    registry = CommandRegistry()
    registry.register(weather)

    assert "weather" in registry.commands
    assert "weather" in registry
    assert len(registry) >= 1


def test_unknown_and_empty_command_errors():
    registry = CommandRegistry()

    assert execute_value(registry, "") == "Error: Empty command"
    assert execute_value(registry, "missingcmd") == "Error: Unknown command"


def test_incorrect_command_inputs_return_structured_errors_or_no_match():
    registry = CommandRegistry()
    registry.register(weather)

    empty_slash = registry.execute("/")
    assert empty_slash.ok is False
    assert empty_slash.error is not None
    assert empty_slash.error.code == "unknown_command"

    malformed = registry.execute('weather "Beijing')
    assert malformed.ok is False
    assert malformed.error is not None
    assert malformed.error.code == "parse_error"
    assert malformed.error.render() == "Error: No closing quotation"

    parsed = registry.parse('weather "Beijing')
    assert parsed is not None
    assert parsed.command == ""
    assert parsed.errors == ["No closing quotation"]

    assert registry.match("/").confidence == 0
    assert registry.match('weather "Beijing').command == "weather"


def test_match_rejects_unknown_mode():
    registry = CommandRegistry()

    try:
        registry.match("weather Beijing", mode="fuzzy")
    except ValueError as exc:
        assert "mode must be 'command' or 'natural'" in str(exc)
    else:
        raise AssertionError("expected invalid match mode to fail")


def test_unknown_command_suggests_close_match():
    registry = CommandRegistry()
    registry.register(weather)

    assert execute_value(registry, "wether Beijing") == "Error: Unknown command. Did you mean 'weather'?"


def test_execute_returns_structured_success_result():
    registry = CommandRegistry()
    registry.register(weather)

    result = registry.execute("weather Beijing")
    assert result.ok is True
    assert result.command == "weather"
    assert result.value == "Beijing:celsius:False"
    assert result.error is None


def test_execute_returns_structured_error_result():
    registry = CommandRegistry()
    registry.register(weather)

    result = registry.execute("wether Beijing")
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "unknown_command"
    assert result.error.suggestion == "weather"
    assert result.error.render() == "Error: Unknown command. Did you mean 'weather'?"


def test_execute_reports_unknown_group_subcommand_as_unknown_command():
    registry = CommandRegistry()
    registry.register(Calculator)

    result = registry.execute("calc div 10 2")

    assert result.ok is False
    assert result.command == "calc div"
    assert result.error is not None
    assert result.error.code == "unknown_command"
    assert result.error.suggestion is None
    assert result.error.hint == "Use 'calc --help' to inspect available subcommands."
    assert result.error.render() == "Error: Unknown command Use 'calc --help' to inspect available subcommands."


def test_unknown_group_subcommand_suggests_close_subcommand():
    registry = CommandRegistry()
    registry.register(Calculator)

    result = registry.execute("calc ad 10 2")

    assert result.ok is False
    assert result.command == "calc ad"
    assert result.error is not None
    assert result.error.code == "unknown_command"
    assert result.error.suggestion == "calc add"
    assert result.error.hint == "Use 'calc --help' to inspect available subcommands."
    assert result.error.render() == "Error: Unknown command Did you mean 'calc add'? Use 'calc --help' to inspect available subcommands."


def test_missing_required_argument_error():
    registry = CommandRegistry()
    registry.register(weather)

    result = execute_value(registry, "--unit celsius")
    assert result == "Error: Unknown command"
    result = execute_value(registry, "weather --unit celsius")
    assert "missing required argument: city" in result


def test_type_conversion_errors_surface_cleanly():
    registry = CommandRegistry()
    registry.register(ExecCommand())

    result = execute_value(registry, "exec pytest -t nope")
    assert "invalid literal for int()" in result


def test_strict_mode_rejects_unknown_option():
    registry = CommandRegistry(strict=True)
    registry.register(weather)

    result = execute_value(registry, "weather Beijing --bogus 1")
    assert result == "Error: unknown option: --bogus Did you mean '--verbose'? Use 'weather --help' to inspect valid options."


def test_structured_parse_error_contains_details():
    registry = CommandRegistry(strict=True)
    registry.register(weather)

    result = registry.execute("weather Beijing --bogus 1")
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "parse_error"
    assert result.error.details["errors"] == ["unknown option: --bogus"]


def test_unknown_option_suggests_closest_valid_option():
    registry = CommandRegistry(strict=True)
    registry.register(weather)

    result = execute_value(registry, "weather Beijing --unti celsius")
    assert result == "Error: unknown option: --unti Did you mean '--unit'? Use 'weather --help' to inspect valid options."


def test_strict_mode_rejects_missing_option_value():
    registry = CommandRegistry(strict=True)
    registry.register(weather)

    result = execute_value(registry, "weather Beijing --unit")
    assert result == "Error: missing value for option: --unit Use 'weather --help' to inspect expected values."


def test_lenient_mode_ignores_unknown_option_errors_for_execution():
    registry = CommandRegistry(strict=False)
    registry.register(weather)

    result = execute_value(registry, "weather Beijing --bogus 1")
    assert result == "Beijing:celsius:False"


def test_prefix_matching_can_be_disabled():
    registry = CommandRegistry(allow_prefix_match=False)
    registry.register(weather)

    assert execute_value(registry, "wea Beijing") == "Error: Unknown command. Did you mean 'weather'?"


def test_exec_tool_is_minimal_outer_tool_bridge():
    registry = CommandRegistry()
    registry.register(weather)
    exec_tool = ExecTool(callback=lambda command, **kwargs: execute_value(registry, command))

    result = ExecTool.execute  # keep reference to ensure method exists
    assert callable(result)


def test_builtin_exec_tool_registered_into_registry():
    registry = CommandRegistry()
    registry.register(ExecTool(callback=lambda command, **kwargs: {"command": command, **kwargs}))

    result = execute_value(registry, "exec --command echo --timeout 3")
    assert result == {"command": "echo", "timeout": 3}
    assert "Execute a command string through a callback" in execute_value(registry, "exec -h")


def test_async_function_command_executes():
    @command(name="ping", description="async ping")
    async def ping(target: str) -> str:
        return f"pong:{target}"

    registry = CommandRegistry()
    registry.register(ping)

    assert execute_value(registry, "ping server") == "pong:server"


def test_execute_async_returns_structured_success_result():
    registry = CommandRegistry()
    registry.register(weather)

    result = asyncio.run(registry.execute_async("weather Beijing"))
    assert result.ok is True
    assert result.command == "weather"
    assert result.value == "Beijing:celsius:False"
    assert result.error is None


def test_execute_async_returns_value():
    registry = CommandRegistry()
    registry.register(weather)

    result = asyncio.run(execute_value_async(registry, "weather Beijing -u fahrenheit"))
    assert result == "Beijing:fahrenheit:False"


def test_execute_async_chain_supports_operators():
    registry = CommandRegistry()
    registry.register(weather)

    results = asyncio.run(registry.execute_async("weather Beijing ; weather Shanghai -u kelvin", chain=True))
    assert results == ["Beijing:celsius:False", "Shanghai:kelvin:False"]


def test_unified_chain_parse_execute_and_match_api():
    registry = CommandRegistry()
    registry.register(weather)

    parsed = registry.parse("weather Beijing ; weather Shanghai -u kelvin", chain=True)
    assert parsed is not None
    assert [item.command for item in parsed] == ["weather", "weather"]

    assert registry.execute("weather Beijing ; weather Shanghai -u kelvin", chain=True) == [
        "Beijing:celsius:False",
        "Shanghai:kelvin:False",
    ]

    hits = registry.match("weather Beijing ; missing", chain=True)
    assert [hit.command for hit in hits] == ["weather", None]


def test_execute_chain_error_control_flow_for_bad_commands():
    registry = CommandRegistry()
    registry.register(weather)

    assert registry.execute("missing ; weather Beijing", chain=True) == [
        "Error: Unknown command",
        "Beijing:celsius:False",
    ]
    assert registry.execute("missing && weather Beijing", chain=True) == ["Error: Unknown command"]
    assert registry.execute("missing || weather Beijing", chain=True) == [
        "Error: Unknown command",
        "Beijing:celsius:False",
    ]
    assert registry.execute("weather Beijing || missing", chain=True) == ["Beijing:celsius:False"]


def test_execute_chain_handles_parse_error_and_empty_input():
    registry = CommandRegistry()
    registry.register(weather)

    assert registry.execute("", chain=True) == []
    assert registry.execute('weather "Beijing ; weather Shanghai', chain=True) == ["Error: No closing quotation"]


def test_match_chain_stops_on_bad_command_for_short_circuit_operators():
    registry = CommandRegistry()
    registry.register(weather)

    and_hits = registry.match("weather Beijing && missing && weather Shanghai", chain=True)
    or_hits = registry.match("weather Beijing ; missing ; weather Shanghai", chain=True)

    assert [hit.command for hit in and_hits] == ["weather", None]
    assert [hit.command for hit in or_hits] == ["weather", None, "weather"]


def test_new_command_and_adapter_modules_are_public_import_paths():
    assert NativeCliCommand is CliCommand
    assert native_wrap_tool is wrap_tool


def test_execute_chain_respects_quoted_operators():
    @command(name="say")
    def say(text: Annotated[str, Option(positional=True)]) -> str:
        return text

    registry = CommandRegistry()
    registry.register(say)

    assert registry.execute('say "hello | world"', chain=True) == ["hello | world"]
    assert registry.execute('say "hello ; world" ; say done', chain=True) == ["hello ; world", "done"]
    assert registry.execute('say "hello && world" && say ok', chain=True) == ["hello && world", "ok"]
    assert registry.execute("""say 'hello || world' || say skipped""", chain=True) == ["hello || world"]


def test_match_chain_respects_quoted_operators():
    @command(name="say")
    def say(text: Annotated[str, Option(positional=True)]) -> str:
        return text

    registry = CommandRegistry()
    registry.register(say)

    hits = registry.match('say "hello ; world" ; missing', chain=True)

    assert [hit.command for hit in hits] == ["say", None]


def test_execute_async_chain_preprocesses_backslash_line_continuation():
    @command(name="collect")
    def collect(items: Annotated[list[str], Option(positional=True)]) -> list[str]:
        return items

    registry = CommandRegistry()
    registry.register(collect)

    results = asyncio.run(registry.execute_async("collect hello \\\nworld", chain=True))

    assert results == [["hello", "world"]]


def test_parse_common_inputs_stays_sub_millisecond_average():
    @command(name="say")
    def say(text: Annotated[str, Option(positional=True)]) -> str:
        return text

    @command(name="collect")
    def collect(items: Annotated[list[str], Option(positional=True)]) -> list[str]:
        return items

    registry = CommandRegistry()
    registry.register(weather)
    registry.register(say)
    registry.register(collect)

    commands = [
        "weather Beijing -u fahrenheit",
        'weather "New York" --unit fahrenheit',
        "collect hello \\\nworld",
        'say "hello && world"',
    ]
    for command_text in commands:
        registry.parse(command_text)

    iterations = 1_000
    start = time.perf_counter()
    for index in range(iterations):
        parsed = registry.parse(commands[index % len(commands)])
        assert parsed is not None
        assert parsed.errors == []
    elapsed = time.perf_counter() - start
    avg_us = elapsed / iterations * 1_000_000

    assert avg_us < 1_500


def test_wrap_langchain_tool_creates_command_spec():
    class FakeArgs:
        query: str

    class FakeLangChainTool:
        name = "search_docs"
        description = "Search documents"
        parameters = None
        args_schema = ExecArgs

        async def ainvoke(self, payload):
            return {"payload": payload}

    registry = CommandRegistry()
    registry.register_spec(wrap_langchain_tool(FakeLangChainTool()))

    result = execute_value(registry, "search_docs docs")
    assert result == {"payload": {"command": "docs", "timeout": 60, "sandbox": False}}


def test_wrap_autogen_tool_creates_command_spec():
    class FakeAutoGenTool:
        schema = {
            "name": "lookup",
            "description": "Lookup value",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer", "default": 3},
                },
                "required": ["query"],
            },
        }

        async def run_json(self, args, cancellation_token=None):
            return {"args": args, "token": cancellation_token}

    registry = CommandRegistry()
    registry.register_spec(wrap_autogen_tool(FakeAutoGenTool()))

    result = execute_value(registry, "lookup --query docs --top_k 5")
    assert result == {"args": {"query": "docs", "top_k": 5}, "token": None}


def test_wrap_openai_tool_schema_creates_command_spec():
    registry = CommandRegistry()
    registry.register_spec(
        wrap_openai_tool_schema(
            name="sum_numbers",
            description="Add two integers",
            parameters={
                "type": "object",
                "properties": {
                    "a": {"type": "integer"},
                    "b": {"type": "integer"},
                },
                "required": ["a", "b"],
            },
            handler=lambda a, b: a + b,
        )
    )

    assert execute_value(registry, "sum_numbers --a 2 --b 3") == 5


def test_execution_error_is_wrapped():
    @command(name="boom")
    def boom() -> str:
        raise RuntimeError("broken")

    registry = CommandRegistry()
    registry.register(boom)

    assert execute_value(registry, "boom") == "Error: executing boom: broken"


def test_execution_errors_are_structured():
    @command(name="boom2")
    def boom2() -> str:
        raise RuntimeError("broken")

    registry = CommandRegistry()
    registry.register(boom2)

    result = registry.execute("boom2")
    assert result.ok is False
    assert isinstance(result.error, CommandError)
    assert result.error.code == "execution_error"
    assert result.error.render() == "Error: executing boom2: broken"


def test_deprecated_command_help_and_execution_still_work():
    registry = CommandRegistry()
    registry.register(legacy)

    help_text = execute_value(registry, "legacy --help")
    assert help_text.startswith("Deprecated: use weather instead")
    assert execute_value(registry, "legacy") == "legacy"


def test_optional_pydantic_v2_support_when_installed():
    if find_spec("pydantic") is None:
        return

    from pydantic import BaseModel, Field

    class SearchModel(BaseModel):
        query: Annotated[str, Option(description="search text", positional=True)]
        top_k: Annotated[int, Option(short="k", description="top k")] = Field(default=5, description="top k")

    class SearchCommand(CliCommand):
        name = "psearch"
        description = "Pydantic-backed command"
        args_model = SearchModel

        async def run(self, **kwargs):
            return kwargs

    registry = CommandRegistry()
    registry.register(SearchCommand())

    result = execute_value(registry, "psearch docs -k 7")
    assert result == {"query": "docs", "top_k": 7}


@command(name="public", description="Public command")
def public_cmd() -> str:
    return "ok"


@command(name="secret", description="Secret command", include_in_prompt=False)
def secret_cmd() -> str:
    return "secret"


@command_group(name="admin", description="Admin operations", include_in_prompt=False)
class AdminGroup:
    @command(name="reset", description="Reset state")
    def reset(self) -> str:
        return "reset"

    @command(name="dump", description="Dump diagnostics")
    def dump(self) -> str:
        return "dump"


@command_group(name="visible", description="Visible group")
class VisibleGroup:
    @command(name="show", description="Show thing")
    def show(self) -> str:
        return "show"

    @command(name="hide_me", description="Hidden sub", include_in_prompt=False)
    def hide_me(self) -> str:
        return "hidden"


def test_include_in_prompt_defaults_to_true():
    registry = CommandRegistry()
    registry.register(public_cmd)

    spec = registry.get("public")
    assert spec.include_in_prompt is True
    assert "public:" in registry.render_llm_context()


def test_command_excluded_from_llm_context_when_include_in_prompt_false():
    registry = CommandRegistry()
    registry.register(public_cmd)
    registry.register(secret_cmd)

    context = registry.render_llm_context()
    assert "public:" in context
    assert "secret" not in context


def test_command_excluded_from_prompt_still_callable_and_in_help():
    registry = CommandRegistry()
    registry.register(secret_cmd)

    assert execute_value(registry, "secret") == "secret"
    assert "secret" in registry.help()


def test_command_group_excluded_from_llm_context():
    registry = CommandRegistry()
    registry.register(public_cmd)
    registry.register(AdminGroup)

    context = registry.render_llm_context()
    assert "public:" in context
    assert "admin" not in context


def test_command_group_excluded_still_lists_in_help_and_executes():
    registry = CommandRegistry()
    registry.register(AdminGroup)

    assert "admin" in registry.help()
    assert execute_value(registry, "admin reset") == "reset"


def test_subcommand_include_in_prompt_is_independent_of_group():
    registry = CommandRegistry()
    registry.register(VisibleGroup)

    context = registry.render_llm_context()
    assert "visible:" in context
    assert "hide_me" not in context


def test_command_from_model_propagates_include_in_prompt():
    @dataclass
    class Args:
        value: Annotated[str, Option(positional=True)]

    spec = command_from_model(
        "mcmd",
        Args,
        lambda value: value,
        description="Model command",
        include_in_prompt=False,
    )

    assert spec.include_in_prompt is False

    registry = CommandRegistry()
    registry.register_spec(spec)
    assert "mcmd" not in registry.render_llm_context()
    assert "mcmd" in registry.help()


def test_command_from_method_propagates_include_in_prompt():
    class Service:
        def ping(self) -> str:
            return "pong"

    spec = command_from_method(
        "ping",
        Service(),
        "ping",
        description="Ping service",
        include_in_prompt=False,
    )

    assert spec.include_in_prompt is False

    registry = CommandRegistry()
    registry.register_spec(spec)
    assert "ping" not in registry.render_llm_context()
    assert execute_value(registry, "ping") == "pong"


def test_cli_command_class_propagates_include_in_prompt():
    class HiddenCli(CliCommand):
        name = "hcli"
        description = "Hidden from prompt"
        args_model = ExecArgs
        include_in_prompt = False

        async def run(self, **kwargs):
            return kwargs

    registry = CommandRegistry()
    registry.register(HiddenCli())

    spec = registry.get("hcli")
    assert spec.include_in_prompt is False
    assert "hcli" not in registry.render_llm_context()
    assert "hcli" in registry.help()


def test_arg_spec_to_dict_is_json_safe_and_roundtrips():
    from agenticli.types import ArgSpec

    spec = ArgSpec(
        name="count",
        type=int,
        default=0,
        required=False,
        description="iteration count",
        short="c",
        positional=False,
        enum=[1, 2, 3],
        requires=["other"],
        excludes=[""],
    )
    data = spec.to_dict()
    assert json.dumps(data)  # JSON-serializable
    assert data["type"] == "int"

    restored = ArgSpec.from_dict(data)
    assert restored.name == spec.name
    # `type` is preserved as the string form so the dict stays JSON-safe.
    assert restored.type == "int"
    assert restored.default == spec.default
    assert restored.required == spec.required
    assert restored.short == spec.short
    assert restored.enum == spec.enum
    assert restored.requires == spec.requires


def test_command_spec_to_dict_drops_func_validator_and_factories():
    @command(name="ping", description="Ping")
    def ping() -> str:
        return "pong"

    registry = CommandRegistry()
    registry.register(ping)
    spec = registry.get("ping")

    data = spec.to_dict()
    dumped = json.dumps(data)
    assert "func" not in data
    assert "validator" not in data
    assert "injection_factories" not in data
    # only the names of factories are persisted
    assert "injection_factory_names" in data
    # help text and metadata preserved
    assert data["name"] == "ping"
    assert data["description"] == "Ping"
    assert isinstance(data["args"], list)
    assert json.loads(dumped) == data


def test_command_spec_from_dict_without_resolver_is_unexecutable():
    registry = CommandRegistry()
    registry.register(echo_for_serial)
    spec = registry.get("echo")
    data = spec.to_dict()
    restored = CommandSpec.from_dict(data)

    with pytest.raises(RuntimeError, match="func_resolver"):
        restored.func()


def test_command_spec_roundtrip_with_func_resolver_executes():
    registry = CommandRegistry()
    registry.register(echo_for_serial)
    spec = registry.get("echo")
    data = spec.to_dict()

    def resolver(name, parent):
        assert name == "echo"
        return registry.get("echo").func

    restored = CommandSpec.from_dict(data, func_resolver=resolver)

    new_registry = CommandRegistry()
    new_registry.register_spec(restored)
    assert execute_value(new_registry, "echo") == "echoed"


def test_command_registry_to_dict_excludes_builtin_help():
    registry = CommandRegistry()
    registry.register(echo_for_serial)

    data = registry.to_dict()
    names = [entry["name"] for entry in data]
    assert "--help" not in names
    assert "echo" in names


def test_command_registry_from_dict_re_registers_with_resolver():
    registry = CommandRegistry()
    registry.register(echo_for_serial)

    def resolver(name, parent):
        return registry.get(name).func

    snapshot = registry.to_dict()
    new_registry = CommandRegistry()
    new_registry.from_dict(snapshot, func_resolver=resolver)

    assert execute_value(new_registry, "echo") == "echoed"
    assert new_registry.help()  # --help re-added lazily


def test_serialization_filters_non_json_safe_injections():
    live_handle = object()
    spec = CommandSpec(
        name="with_inj",
        description="",
        func=lambda: None,
        injections={"ok": 1, "bad": live_handle, "list": [1, "x"]},
    )

    data = spec.to_dict()
    assert data["injections"] == {"ok": 1, "list": [1, "x"]}
    assert "bad" not in data["injections"]


def test_serialization_preserves_visibility_flags():
    registry = CommandRegistry()
    registry.register(public_cmd)
    registry.register(secret_cmd)

    data = registry.to_dict()
    by_name = {entry["name"]: entry for entry in data}
    assert by_name["public"]["include_in_prompt"] is True
    assert by_name["secret"]["include_in_prompt"] is False
    assert by_name["secret"]["hidden"] is False


def test_serialization_handles_group_subcommands():
    registry = CommandRegistry()
    registry.register(Calculator)

    snapshot = registry.to_dict()
    names = {entry["name"] for entry in snapshot}
    assert "calc" in names
    assert "calc add" in names
    assert "calc mul" in names

    new_registry = CommandRegistry()

    def resolver(name, parent):
        return {"calc add": lambda: None, "calc mul": lambda: None, "calc": lambda: None}[name]

    new_registry.from_dict(snapshot, func_resolver=resolver)
    assert new_registry.has("calc add")


# --- fixtures local to serialization tests ---


@command(name="echo", description="Echo placeholder")
def echo_for_serial() -> str:
    return "echoed"


# --- bare @command usage (no parentheses) ---


@command
def bare_form(name: Annotated[str, Option(positional=True, description="name")]) -> str:
    return f"bare:{name}"


@command()
def parens_only_form(name: Annotated[str, Option(positional=True, description="name")]) -> str:
    return f"parens:{name}"


def test_command_decorator_accepts_bare_form():
    spec = bare_form.__command_spec__
    assert spec is not None
    assert spec.name == "bare_form"
    assert spec.description == ""

    registry = CommandRegistry()
    registry.register(bare_form)
    result = execute_value(registry, 'bare_form "x"')
    assert result == "bare:x"


def test_command_decorator_accepts_parens_only_form():
    spec = parens_only_form.__command_spec__
    assert spec is not None
    assert spec.name == "parens_only_form"

    registry = CommandRegistry()
    registry.register(parens_only_form)
    result = execute_value(registry, 'parens_only_form "x"')
    assert result == "parens:x"


# ---------------------------------------------------------------------------
# @command_group(register_as_command=False): namespace mode
# ---------------------------------------------------------------------------


@command_group(
    name="ns_admin",
    description="Admin namespace",
    register_as_command=False,
    include_in_prompt=False,
)
class NsAdminGroup:
    @command(name="ns_reset", description="Reset state")
    def reset(self) -> str:
        return "ns-reset"

    @command(name="ns_dump", description="Dump diagnostics")
    def dump(self) -> str:
        return "ns-dump"


@command_group(
    name="ns_public",
    description="Public namespace",
    register_as_command=False,
)
class NsPublicGroup:
    @command(name="ns_ping", description="Ping service")
    def ping(self) -> str:
        return "ns-pong"

    @command(name="ns_visible_secret", description="Explicit hidden", include_in_prompt=False)
    def secret(self) -> str:
        return "ns-secret"


@command_group(
    name="ns_mixed",
    description="Group hidden, one opt-in",
    register_as_command=False,
    include_in_prompt=False,
)
class NsMixedGroup:
    @command(name="ns_deploy", description="Deploy (default)")
    def deploy(self) -> str:
        return "ns-deployed"

    @command(name="ns_rollback", description="Rollback (explicit visible)", include_in_prompt=True)
    def rollback(self) -> str:
        return "ns-rolled-back"


def test_namespace_group_is_not_registered_as_command():
    registry = CommandRegistry()
    registry.register(NsAdminGroup())

    assert not registry.has("ns_admin")
    assert "ns_admin" not in registry.commands


def test_namespace_subcommands_register_as_flat_top_level():
    registry = CommandRegistry()
    registry.register(NsAdminGroup())

    assert registry.has("ns_reset")
    assert registry.has("ns_dump")
    assert not registry.has("ns_admin ns_reset")


def test_namespace_subcommands_are_executable_with_flat_name():
    registry = CommandRegistry()
    registry.register(NsAdminGroup())

    assert execute_value(registry, "ns_reset") == "ns-reset"
    assert execute_value(registry, "ns_dump") == "ns-dump"


def test_namespace_subcommand_cannot_be_invoked_with_group_prefix():
    registry = CommandRegistry()
    registry.register(NsAdminGroup())

    result = registry.execute("ns_admin ns_reset")
    assert not result.ok
    assert "unknown" in result.error.message.lower() or "ns_admin" in result.error.message


def test_namespace_subcommand_spec_has_no_parent():
    registry = CommandRegistry()
    registry.register(NsAdminGroup())

    spec = registry.get("ns_reset")
    assert spec is not None
    assert spec.parent is None
    assert spec.source == "function"


def test_namespace_help_lists_subcommands_at_top_level():
    registry = CommandRegistry()
    registry.register(NsAdminGroup())

    help_text = registry.help()
    assert "ns_reset" in help_text
    assert "ns_dump" in help_text
    assert "ns_admin" not in help_text.split("Subcommands:")[0]
    assert "ns_admin:" not in help_text


def test_namespace_include_in_prompt_propagates_to_default_subcommands():
    registry = CommandRegistry()
    registry.register(NsAdminGroup())

    context = registry.render_llm_context()
    assert "ns_reset" not in context
    assert "ns_dump" not in context
    assert "ns_admin" not in context


def test_namespace_visible_group_lists_in_llm_context():
    registry = CommandRegistry()
    registry.register(NsPublicGroup())

    context = registry.render_llm_context()
    assert "ns_ping" in context
    assert "ns_visible_secret" not in context


def test_namespace_subcommand_explicit_include_in_prompt_overrides_group():
    """When group is hidden, an explicit include_in_prompt=True on a subcommand wins."""
    registry = CommandRegistry()
    registry.register(NsMixedGroup())

    context = registry.render_llm_context()
    assert "ns_deploy" not in context
    assert "ns_rollback" in context


def test_namespace_subcommand_with_class_instance_uses_bound_method():
    class Stateful:
        def __init__(self) -> None:
            self.calls = 0

        @command(name="ns_inc", description="Increment counter")
        def inc(self) -> dict:
            self.calls += 1
            return {"calls": self.calls}

    # Decorate the class itself, not a wrapper.
    Stateful.__command_group__ = {
        "name": "",
        "description": "",
        "include_in_prompt": True,
        "register_as_command": False,
    }

    instance = Stateful()
    registry = CommandRegistry()
    registry.register(instance)

    assert execute_value(registry, "ns_inc") == {"calls": 1}
    # Registering the same instance reuses state on second invocation.
    result = registry.execute("ns_inc")
    assert result.ok
    assert isinstance(result.value, dict)


def test_namespace_default_register_as_command_is_true_back_compat():
    """When register_as_command is omitted, group registers as before."""
    @command_group(name="legacy_grp", description="Legacy")
    class LegacyGroup:
        @command(name="legacy_op", description="Legacy op")
        def op(self) -> str:
            return "legacy-ok"

    registry = CommandRegistry()
    registry.register(LegacyGroup())

    assert registry.has("legacy_grp")
    assert registry.has("legacy_grp legacy_op")
    assert execute_value(registry, "legacy_grp legacy_op") == "legacy-ok"


def test_namespace_subcommands_still_hidden_flag_works():
    @command_group(name="ns_vis", register_as_command=False, include_in_prompt=True)
    class VisGroup:
        @command(name="ns_silent", description="Silent", hidden=True)
        def silent(self) -> str:
            return "shh"

    registry = CommandRegistry()
    registry.register(VisGroup())

    assert "ns_silent" not in registry.help()
    assert execute_value(registry, "ns_silent") == "shh"


def test_namespace_group_name_is_optional():
    @command_group(register_as_command=False, include_in_prompt=True)
    class AnonGroup:
        @command(name="anon_op", description="Anon op")
        def op(self) -> str:
            return "anon-ok"

    registry = CommandRegistry()
    registry.register(AnonGroup())

    assert not registry.has("")  # name defaults to "" but never registered
    assert registry.has("anon_op")
    assert execute_value(registry, "anon_op") == "anon-ok"


def test_command_group_with_register_as_command_true_requires_name():
    with pytest.raises(ValueError, match="non-empty 'name'"):
        @command_group(register_as_command=True)
        class BadGroup:
            @command
            def op(self) -> str:
                return "x"


def test_empty_name_defaults_to_namespace_mode():
    """When name is empty and register_as_command is not set, namespace mode kicks in."""
    @command_group(include_in_prompt=False)
    class AutoNs:
        @command(name="auto_op", description="Auto namespace op")
        def op(self) -> str:
            return "auto-ok"

    registry = CommandRegistry()
    registry.register(AutoNs())

    assert not registry.has("")  # group not registered
    assert registry.has("auto_op")
    assert "auto_op" not in registry.render_llm_context()


def test_non_empty_name_defaults_to_group_mode():
    """When name is provided and register_as_command is not set, group mode is the default."""
    @command_group(name="auto_grp", description="Auto group")
    class AutoGrp:
        @command(name="auto_op2", description="Auto group op")
        def op(self) -> str:
            return "auto-grp-ok"

    registry = CommandRegistry()
    registry.register(AutoGrp())

    assert registry.has("auto_grp")
    assert registry.has("auto_grp auto_op2")
    assert execute_value(registry, "auto_grp auto_op2") == "auto-grp-ok"


def test_explicit_register_as_command_false_overrides_non_empty_name():
    """Even with a name, explicit register_as_command=False → namespace mode (name ignored)."""
    @command_group(name="ignored", register_as_command=False, include_in_prompt=True)
    class OverrideNs:
        @command(name="over_op", description="Override op")
        def op(self) -> str:
            return "over-ok"

    registry = CommandRegistry()
    registry.register(OverrideNs())

    assert not registry.has("ignored")
    assert registry.has("over_op")
    assert execute_value(registry, "over_op") == "over-ok"


# ---------------------------------------------------------------------------
# Real-world usage scenarios
# ---------------------------------------------------------------------------
#
# These tests exercise patterns that mirror the existing example/ scripts,
# so regressions in those scenarios show up as test failures.


# Scenario 1: Linux-like command set (stateful shell).
# Mirrors example/linux_like_shell.py but uses @command on methods instead
# of the manual command_from_method loop. State (cwd) persists across
# invocations because the user registers an instance, not a class.


@command_group(include_in_prompt=True)
class LinuxLikeShell:
    """Small read-only command set with a shared cwd."""

    def __init__(self, root: str = ".") -> None:
        from pathlib import Path
        self.cwd = Path(root).resolve()

    @command(name="pwd", description="Print working directory")
    def pwd(self) -> dict:
        return {"cwd": str(self.cwd)}

    @command(name="ls", description="List entries at path")
    def ls(
        self,
        path: Annotated[str, Option(positional=True, value_name="path")] = ".",
    ) -> list:
        target = self.cwd / path if path != "." else self.cwd
        return sorted(p.name for p in target.iterdir())

    @command(name="cd", description="Change directory")
    def cd(
        self,
        path: Annotated[str, Option(positional=True, value_name="path")],
    ) -> dict:
        target = (self.cwd / path).resolve()
        if not target.is_dir():
            raise NotADirectoryError(path)
        self.cwd = target
        return {"cwd": str(self.cwd)}


def test_linux_like_shell_state_persists_across_calls():
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        sub = Path(tmp) / "sub"
        sub.mkdir()
        (sub / "a.txt").write_text("a")
        (sub / "b.txt").write_text("b")

        # Use a relative starting point so cd/ls paths don't have to
        # round-trip through shlex (which would mangle Windows
        # backslashes). This mirrors the usage in example/linux_like_shell.py.
        cwd = Path(tmp).resolve()
        os.chdir(cwd)  # noqa: S605 - test-only
        try:
            registry = CommandRegistry()
            registry.register(LinuxLikeShell(root="."))

            # cwd starts at the resolved cwd
            assert execute_value(registry, "pwd") == {"cwd": str(cwd)}

            # cd into sub, then ls shows the two files
            cd_result = execute_value(registry, "cd sub")
            assert cd_result["cwd"] == str(sub)
            listing = execute_value(registry, "ls .")
            assert sorted(listing) == ["a.txt", "b.txt"]
        finally:
            os.chdir(Path.cwd().anchor or "/")


def test_linux_like_shell_subcommands_appear_at_top_level_in_help():
    registry = CommandRegistry()
    registry.register(LinuxLikeShell())
    help_text = registry.help()
    assert "pwd" in help_text
    assert "ls" in help_text
    assert "cd" in help_text
    # No spurious "LinuxLikeShell" header
    assert "LinuxLikeShell:" not in help_text


# Scenario 2: Admin namespace, hidden from the LLM but callable.


@command_group(include_in_prompt=False)
class AdminCommands:
    @command(name="admin_reset", description="Reset state (admin)", include_in_prompt=False)
    def reset(self) -> dict:
        return {"reset": True}

    @command(name="admin_dump", description="Dump diagnostics (admin)", include_in_prompt=False)
    def dump(self) -> dict:
        return {"dump": True}

    @command(name="admin_safe_ping", description="Safe ping (admin-visible)", include_in_prompt=True)
    def safe_ping(self) -> str:
        return "pong"


def test_admin_namespace_hides_all_subcommands_from_llm_prompt_by_default():
    registry = CommandRegistry()
    registry.register(AdminCommands())

    context = registry.render_llm_context()
    assert "admin_reset" not in context
    assert "admin_dump" not in context
    # The explicitly visible subcommand still appears.
    assert "admin_safe_ping" in context


def test_admin_namespace_subcommands_remain_callable():
    registry = CommandRegistry()
    registry.register(AdminCommands())

    assert execute_value(registry, "admin_reset") == {"reset": True}
    assert execute_value(registry, "admin_dump") == {"dump": True}
    assert execute_value(registry, "admin_safe_ping") == "pong"


# Scenario 3: Async subcommands in a namespace.


@command_group(include_in_prompt=True)
class AsyncCommands:
    @command(name="async_fetch", description="Fetch async")
    async def fetch(self) -> dict:
        await asyncio.sleep(0)
        return {"fetched": True}

    @command(name="async_compute", description="Compute sum", include_in_prompt=True)
    async def compute(
        self,
        values: Annotated[list[int], Option(positional=True, value_name="n")],
    ) -> dict:
        return {"sum": sum(values)}


def test_namespace_supports_async_subcommands():
    registry = CommandRegistry()
    registry.register(AsyncCommands())

    assert execute_value(registry, "async_fetch") == {"fetched": True}
    assert execute_value(registry, "async_compute 1 2 3 4") == {"sum": 10}


def test_namespace_async_subcommands_runnable_via_execute_async():
    registry = CommandRegistry()
    registry.register(AsyncCommands())

    result = asyncio.run(registry.execute_async("async_compute 10 20"))
    assert result.ok
    assert result.value == {"sum": 30}


# Scenario 4: Subcommand with aliases.


@command_group(include_in_prompt=True)
class AliasedCommands:
    @command(name="weather", description="Get weather", aliases=["wx", "w"])
    def weather(
        self,
        city: Annotated[str, Option(positional=True, value_name="city")],
    ) -> dict:
        return {"city": city, "temp": 20}


def test_namespace_subcommand_aliases_resolve_to_same_handler():
    registry = CommandRegistry()
    registry.register(AliasedCommands())

    assert execute_value(registry, "weather paris") == {"city": "paris", "temp": 20}
    assert execute_value(registry, "wx tokyo") == {"city": "tokyo", "temp": 20}
    assert execute_value(registry, "w london") == {"city": "london", "temp": 20}


# Scenario 5: Mix namespace groups with regular groups in the same registry.


@command_group(include_in_prompt=True)
class ProjectTools:
    @command(name="proj_status", description="Show project status")
    def status(self) -> str:
        return "ok"


def test_namespace_and_group_modes_coexist_in_same_registry():
    @command_group(name="db", description="Database operations", include_in_prompt=True)
    class DbCommands:
        @command(name="list", description="List databases")
        def list_dbs(self) -> list:
            return ["main", "audit"]

    registry = CommandRegistry()
    registry.register(ProjectTools())
    registry.register(DbCommands())

    # Namespace subcommands: flat at top level
    assert registry.has("proj_status")
    assert execute_value(registry, "proj_status") == "ok"

    # Regular group: nested invocation
    assert registry.has("db")
    assert registry.has("db list")
    assert execute_value(registry, "db list") == ["main", "audit"]


# Scenario 6: Namespace group with deeply nested options (bool flags, list
# args, defaults, shortcuts) — verifies the full signature machinery
# works for namespace subcommands the same way as top-level @commands.


@command_group(include_in_prompt=True)
class GrepLikeCommands:
    @command(name="grep", description="Search text in files")
    def grep(
        self,
        pattern: Annotated[str, Option(positional=True, value_name="pattern")],
        paths: Annotated[list[str], Option(positional=True, value_name="file")],
        ignore_case: Annotated[bool, Option(short="i")] = False,
        max_results: Annotated[int, Option(short="n")] = 10,
    ) -> dict:
        return {
            "pattern": pattern,
            "files": list(paths),
            "ignore_case": ignore_case,
            "limit": max_results,
        }


def test_namespace_subcommand_signature_parsing_with_options():
    registry = CommandRegistry()
    registry.register(GrepLikeCommands())

    result = execute_value(registry, "grep hello a.txt b.txt -i -n 5")
    assert result == {
        "pattern": "hello",
        "files": ["a.txt", "b.txt"],
        "ignore_case": True,
        "limit": 5,
    }


# Scenario 7: discover() picks up namespace groups when scanning a
# directory. This mirrors example/discover.py but with namespace
# mode so the @command_group classes do not register a parent command.


def test_namespace_group_round_trips_through_discover(tmp_path, monkeypatch):
    import textwrap

    pkg = tmp_path / "fake_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "tools.py").write_text(
        textwrap.dedent(
            """
            from __future__ import annotations
            from typing import Annotated
            from agenticli import Option, command, command_group

            @command_group(include_in_prompt=False)
            class DiscoveredTools:
                @command(name="discovered_echo", description="Echo back")
                def echo(self, value: Annotated[str, Option(positional=True)]) -> str:
                    return value
            """
        )
    )

    import sys
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("fake_pkg", None)
    sys.modules.pop("fake_pkg.tools", None)

    registry = CommandRegistry()
    result = registry.discover(pkg, package="fake_pkg", on_error="raise")

    assert "discovered_echo" in result.registered
    assert registry.has("discovered_echo")
    assert execute_value(registry, "discovered_echo hi") == "hi"
    # The group itself is not registered.
    assert not registry.has("DiscoveredTools")
    # And it's hidden from the LLM context.
    assert "discovered_echo" not in registry.render_llm_context()


# ---------------------------------------------------------------------------
# Regression tests for code-reviewer findings
# ---------------------------------------------------------------------------


def test_namespace_explicit_include_in_prompt_via_command_from_method_is_preserved():
    """command_from_method with explicit include_in_prompt=True inside a
    hidden namespace group must NOT be silently overridden to False.

    Regression: the old code read the explicit marker from the wrapper
    function. Wrappers from @command set it, but command_from_method's
    spec has no such wrapper, so the fallback to False clobbered the
    user's explicit value.
    """
    class Service:
        def cmd(self) -> str:
            return "ok"

    spec = command_from_method("cfm_visible", Service(), "cmd", include_in_prompt=True)
    # Sanity: the spec carries the explicit value and the marker.
    assert spec.include_in_prompt is True
    assert getattr(spec, "_include_in_prompt_explicit", False) is True

    @command_group(register_as_command=False, include_in_prompt=False)
    class Holder:
        pass

    Holder.service = spec  # type: ignore[attr-defined]

    # Apply the spec to the namespace class so the namespace branch reads it.
    Holder.__command_group__ = {
        "name": "",
        "description": "",
        "include_in_prompt": False,
        "register_as_command": False,
    }
    # Replace the holder's class with a class whose only method is the spec.
    class ToolWithSpec:
        def cmd(self) -> str:
            return "ok"
    ToolWithSpec.cmd.__command_spec__ = spec  # type: ignore[attr-defined]
    ToolWithSpec.__command_group__ = Holder.__command_group__

    registry = CommandRegistry()
    registry.register(ToolWithSpec())

    # The explicit True must win over the group's False.
    assert "cfm_visible" in registry.render_llm_context()
    assert execute_value(registry, "cfm_visible") == "ok"


def test_namespace_alias_collision_does_not_leave_partial_state():
    """If a namespace subcommand's alias collides with an already-registered
    command, the registry must not contain a half-registered entry for the
    subcommand name (the old code inserted the name first, then raised on
    the alias).
    """
    # Pre-register a command whose name collides with one of the
    # subcommand's aliases.
    @command(name="taken_alias", description="taken")
    def taken() -> str:
        return "t"

    @command_group(register_as_command=False, include_in_prompt=True)
    class CollideNs:
        @command(name="collide_sub", description="collide sub", aliases=["taken_alias"])
        def sub(self) -> str:
            return "s"

    registry = CommandRegistry()
    registry.register(taken)

    with pytest.raises(ValueError, match="alias already registered"):
        registry.register(CollideNs())

    # The colliding alias "taken_alias" already existed; the new
    # subcommand "collide_sub" must not have been inserted, and the
    # original alias still points to the original handler.
    assert registry.has("taken_alias")
    assert execute_value(registry, "taken_alias") == "t"
    assert not registry.has("collide_sub")


def test_namespace_name_collision_raises_before_partial_state():
    """A namespace subcommand whose name collides with an existing command
    raises before mutating _commands."""
    @command(name="dup_name", description="existing")
    def existing() -> str:
        return "e"

    @command_group(register_as_command=False, include_in_prompt=True)
    class DupNs:
        @command(name="dup_name", description="dup")
        def op(self) -> str:
            return "o"

    registry = CommandRegistry()
    registry.register(existing)

    with pytest.raises(ValueError, match="(already registered|alias already registered)"):
        registry.register(DupNs())

    # Only the original command remains.
    spec = registry.get("dup_name")
    assert spec is not None
    assert execute_value(registry, "dup_name") == "e"


def test_group_mode_subcommand_preserves_hidden_flag():
    """Regression: the True branch of _register_command_group used to drop
    spec.hidden and spec.deprecated when wrapping @command methods into
    '<group> <subcommand>' subcommands."""
    @command_group(name="grp_hidden", description="Group with hidden sub")
    class GrpHidden:
        @command(name="inner", description="inner", hidden=True)
        def inner(self) -> str:
            return "i"

    registry = CommandRegistry()
    registry.register(GrpHidden())

    spec = registry.get("grp_hidden inner")
    assert spec is not None
    assert spec.hidden is True
    assert "grp_hidden inner" not in registry.help()

    # And in render_llm_context the group entry shows but the hidden
    # subcommand is filtered out (group has include_in_prompt=True).
    context = registry.render_llm_context()
    assert "grp_hidden:" in context
    assert "inner" not in context  # filtered because hidden

    # Same for deprecated.
    @command_group(name="grp_dep", description="Group with deprecated sub")
    class GrpDep:
        @command(name="inner_dep", description="inner dep", deprecated="use foo instead")
        def inner_dep(self) -> str:
            return "d"

    registry2 = CommandRegistry()
    registry2.register(GrpDep())
    spec_dep = registry2.get("grp_dep inner_dep")
    assert spec_dep is not None
    assert spec_dep.deprecated == "use foo instead"
    help_text = registry2.help("grp_dep inner_dep")
    assert "Deprecated: use foo instead" in help_text


def test_group_mode_subcommand_preserves_aliases():
    """The True branch also used to drop spec.aliases."""
    @command_group(name="grp_alias", description="Group with aliased sub")
    class GrpAlias:
        @command(name="inner", description="inner", aliases=["in"])
        def inner(self) -> str:
            return "i"

    registry = CommandRegistry()
    registry.register(GrpAlias())

    assert registry.has("grp_alias inner")
    assert registry.has("grp_alias in")
    assert execute_value(registry, "grp_alias in") == "i"
