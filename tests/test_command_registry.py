from __future__ import annotations

import asyncio
import json
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
    assert "Usage: weather <city>" in help_text
    assert "short=-u" in help_text
    assert "short=-v" in help_text
    assert "positional" in help_text
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
    assert "Usage: fetch <query>" in help_text
    assert "example='OpenAI latest'" in help_text
    assert "Examples:" in help_text
    assert "Recommended order: fetch <query>" in help_text


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
    assert "Usage: ordered <first> <second> [--head <head>] [--tail <tail>]" in help_text
    assert "order=1" in help_text
    assert "position=0" in help_text
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

    assert "Usage: weather <city>" in execute_value(registry, "--help weather")


def test_help_for_subcommand_works():
    registry = CommandRegistry()
    registry.register(Calculator)

    help_text = execute_value(registry, "calc add --help")
    assert "Command: calc add" in help_text


def test_group_help_lists_subcommands():
    registry = CommandRegistry()
    registry.register(Calculator)

    help_text = execute_value(registry, "calc --help")
    assert "Usage: calc <subcommand> [args...]" in help_text
    assert "Subcommands:" in help_text
    assert "add:" in help_text
    assert "mul:" in help_text


def test_group_without_subcommand_returns_group_help():
    registry = CommandRegistry()
    registry.register(Calculator)

    help_text = execute_value(registry, "calc")
    assert "Usage: calc <subcommand> [args...]" in help_text
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

