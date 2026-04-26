from __future__ import annotations

from dataclasses import dataclass
from importlib.util import find_spec
from typing import Annotated, Literal

from agenticli import (
    Callback,
    CliCommand,
    CommandError,
    CommandRegistry,
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

    result = registry.parse_and_execute('weather "Beijing" -u fahrenheit -v')
    assert result == "Beijing:fahrenheit:True"


def test_long_option_equals_and_short_compact_value():
    registry = CommandRegistry()
    registry.register(weather)

    assert registry.parse_and_execute("weather Shanghai --unit=kelvin") == "Shanghai:kelvin:False"
    assert registry.parse_and_execute("weather Shanghai -ukelvin") == "Shanghai:kelvin:False"


def test_alias_command_executes_same_spec():
    registry = CommandRegistry()
    registry.register(weather)

    assert registry.parse_and_execute("wx Shenzhen") == "Shenzhen:celsius:False"


def test_group_command_supports_multiple_subcommands():
    registry = CommandRegistry()
    registry.register(Calculator)

    assert registry.parse_and_execute("calc add 2 3") == 5
    assert registry.parse_and_execute("calc mul 4 5") == 20


def test_class_command_uses_dataclass_validation_and_defaults():
    registry = CommandRegistry()
    registry.register(ExecCommand())

    result = registry.parse_and_execute("exec pytest -t 30 -s")
    assert result == {"command": "pytest", "timeout": 30, "sandbox": True}


def test_command_from_model_builds_validated_command():
    registry = CommandRegistry()
    registry.register_spec(command_from_model("runner", ExecArgs, lambda **kwargs: kwargs, description="Run command"))

    assert registry.parse_and_execute("runner uv") == {"command": "uv", "timeout": 60, "sandbox": False}


def test_command_from_method_wraps_single_class_method_only():
    class Worker:
        def execute(self, task: str, count: int = 1) -> tuple[str, int]:
            return task, count

        def helper(self) -> str:
            return "helper"

    registry = CommandRegistry()
    registry.register_spec(command_from_method("work", Worker, method_name="execute", description="Run one worker method"))

    assert registry.parse_and_execute("work demo --count 2") == ("demo", 2)
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

    assert registry.parse_and_execute("weather Beijing") == "Beijing:celsius:False"
    assert registry.parse_and_execute("wether Beijing") == "Error: Unknown command. Did you mean 'weather'?"

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

    help_text = registry.parse_and_execute("notify --help")
    assert "callback" not in help_text
    assert registry.parse_and_execute("notify alice") == "alice"
    assert events == ["alice"]
    assert "unknown option: --callback" in registry.parse_and_execute("notify alice --callback nope")


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

    result = registry.parse_and_execute("deps alice")
    assert result == ("alice", {"command": "deps", "raw": "deps alice"}, "helper")
    assert seen == [("callback", "alice")]
    help_text = registry.parse_and_execute("deps --help")
    assert "callback" not in help_text
    assert "state" not in help_text
    assert "helper" not in help_text


def test_wrap_tool_parses_object_and_array_json_arguments():
    registry = CommandRegistry()
    registry.register_spec(wrap_tool(DummyTool()))

    result = registry.parse_and_execute(
        'search --query llm --count 3 --filters "{\\"lang\\": \\"zh\\"}" --tags "[\\"a\\", \\"b\\"]"'
    )
    assert result == {"query": "llm", "count": 3, "filters": {"lang": "zh"}, "tags": ["a", "b"]}


def test_literal_annotation_validates_enum_values():
    registry = CommandRegistry()
    registry.register(mode_select)

    assert registry.parse_and_execute("mode worker --mode safe") == "worker:safe"
    assert "must be one of" in registry.parse_and_execute("mode worker --mode risky")
    assert "Did you mean 'safe'?" in registry.parse_and_execute("mode worker --mode sae")


def test_help_prefers_command_local_form_and_shows_short_aliases():
    registry = CommandRegistry()
    registry.register(weather)

    help_text = registry.parse_and_execute("weather --help")
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

    help_text = registry.parse_and_execute("fetch --help")
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

    help_text = registry.parse_and_execute("ordered --help")
    assert "Usage: ordered <first> <second> [--head <head>] [--tail <tail>]" in help_text
    assert "order=1" in help_text
    assert "position=0" in help_text
    assert registry.parse_and_execute("ordered a b -h H -t T") == ("a", "b", "H", "T")


def test_hidden_parameter_is_not_shown_but_still_parses():
    @command(name="hiddenarg")
    def hiddenarg(
        visible: Annotated[str, Option(positional=True)],
        token: Annotated[str, Option(hidden=True)] = "secret",
    ) -> tuple[str, str]:
        return visible, token

    registry = CommandRegistry()
    registry.register(hiddenarg)

    help_text = registry.parse_and_execute("hiddenarg --help")
    assert "--token" not in help_text
    assert registry.parse_and_execute("hiddenarg shown --token exposed") == ("shown", "exposed")


def test_optional_list_and_repeatable_option_support():
    @command(name="tags")
    def tags(
        name: Annotated[str, Option(positional=True)],
        tag: Annotated[list[str] | None, Option(short="t", repeatable=True)] = None,
    ) -> tuple[str, list[str] | None]:
        return name, tag

    registry = CommandRegistry()
    registry.register(tags)

    assert registry.parse_and_execute("tags item -t red -t blue") == ("item", ["red", "blue"])


def test_optional_dict_support():
    @command(name="meta")
    def meta(
        name: Annotated[str, Option(positional=True)],
        payload: dict[str, str] | None = None,
    ) -> tuple[str, dict[str, str] | None]:
        return name, payload

    registry = CommandRegistry()
    registry.register(meta)

    assert registry.parse_and_execute('meta item --payload "{\\"a\\": \\"1\\"}"') == ("item", {"a": "1"})


def test_tuple_and_fixed_arity_option_support():
    @command(name="range")
    def range_cmd(
        pair: Annotated[tuple[int, int], Option(short="p")],
    ) -> tuple[int, int]:
        return pair

    registry = CommandRegistry()
    registry.register(range_cmd)

    assert registry.parse_and_execute("range -p 1 2") == (1, 2)
    assert "missing value for option: -p" in registry.parse_and_execute("range -p 1")


def test_repeatable_positional_list_support():
    @command(name="collect")
    def collect(items: Annotated[list[str], Option(positional=True)]) -> list[str]:
        return items

    registry = CommandRegistry()
    registry.register(collect)

    assert registry.parse_and_execute("collect a b c") == ["a", "b", "c"]


def test_parameter_requires_other_parameter():
    @command(name="auth")
    def auth(
        user: Annotated[str | None, Option()] = None,
        password: Annotated[str | None, Option(requires=("user",))] = None,
    ) -> tuple[str | None, str | None]:
        return user, password

    registry = CommandRegistry()
    registry.register(auth)

    assert registry.parse_and_execute("auth --user alice --password secret") == ("alice", "secret")
    assert "password requires user" in registry.parse_and_execute("auth --password secret")


def test_parameter_excludes_other_parameter():
    @command(name="mode2")
    def mode2(
        fast: Annotated[bool, Option(excludes=("safe",))] = False,
        safe: bool = False,
    ) -> tuple[bool, bool]:
        return fast, safe

    registry = CommandRegistry()
    registry.register(mode2)

    assert registry.parse_and_execute("mode2 --fast") == (True, False)
    assert "fast cannot be used with safe" in registry.parse_and_execute("mode2 --fast --safe")


def test_help_still_supports_global_form():
    registry = CommandRegistry()
    registry.register(weather)

    assert "Usage: weather <city>" in registry.parse_and_execute("--help weather")


def test_help_for_subcommand_works():
    registry = CommandRegistry()
    registry.register(Calculator)

    help_text = registry.parse_and_execute("calc add --help")
    assert "Command: calc add" in help_text


def test_group_help_lists_subcommands():
    registry = CommandRegistry()
    registry.register(Calculator)

    help_text = registry.parse_and_execute("calc --help")
    assert "Usage: calc <subcommand> [args...]" in help_text
    assert "Subcommands:" in help_text
    assert "add:" in help_text
    assert "mul:" in help_text


def test_group_without_subcommand_returns_group_help():
    registry = CommandRegistry()
    registry.register(Calculator)

    help_text = registry.parse_and_execute("calc")
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


def test_detect_natural_language_hit():
    registry = CommandRegistry()
    registry.register(weather)

    hit = registry.detect("please run weather for beijing")
    assert hit.command == "weather"
    assert hit.confidence > 0


def test_match_command_exact_prefix_and_slash():
    registry = CommandRegistry()
    registry.register(weather)

    exact = registry.match_command("weather Beijing")
    prefix = registry.match_command("wea Beijing")
    slash = registry.match_command("/wea Beijing")

    assert exact.match_type == "exact"
    assert prefix.match_type == "prefix"
    assert slash.match_type == "slash"


def test_is_command_false_for_plain_text():
    registry = CommandRegistry()
    registry.register(weather)

    assert registry.is_command("tell me the weather") is False


def test_render_help_lists_top_level_commands_without_duplicates():
    registry = CommandRegistry()
    registry.register(weather)
    registry.register(Calculator)
    registry.register(internal)
    registry.register(legacy)

    help_text = registry.render_help()
    assert help_text.count("weather:") == 1
    assert "calc:" in help_text
    assert "internal:" not in help_text
    assert "[deprecated]" in help_text


def test_get_llm_prompt_detailed_and_minimal():
    registry = CommandRegistry()
    registry.register(weather)
    registry.register(internal)
    registry.register(legacy)

    minimal = registry.get_llm_prompt()
    detailed = registry.get_llm_prompt(detailed=True)

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

    assert registry.parse_and_execute("") == "Error: Empty command"
    assert registry.parse_and_execute("missingcmd") == "Error: Unknown command"


def test_unknown_command_suggests_close_match():
    registry = CommandRegistry()
    registry.register(weather)

    assert registry.parse_and_execute("wether Beijing") == "Error: Unknown command. Did you mean 'weather'?"


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


def test_missing_required_argument_error():
    registry = CommandRegistry()
    registry.register(weather)

    result = registry.parse_and_execute("--unit celsius")
    assert result == "Error: Unknown command"
    result = registry.parse_and_execute("weather --unit celsius")
    assert "missing required argument: city" in result


def test_type_conversion_errors_surface_cleanly():
    registry = CommandRegistry()
    registry.register(ExecCommand())

    result = registry.parse_and_execute("exec pytest -t nope")
    assert "invalid literal for int()" in result


def test_strict_mode_rejects_unknown_option():
    registry = CommandRegistry(strict=True)
    registry.register(weather)

    result = registry.parse_and_execute("weather Beijing --bogus 1")
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

    result = registry.parse_and_execute("weather Beijing --unti celsius")
    assert result == "Error: unknown option: --unti Did you mean '--unit'? Use 'weather --help' to inspect valid options."


def test_strict_mode_rejects_missing_option_value():
    registry = CommandRegistry(strict=True)
    registry.register(weather)

    result = registry.parse_and_execute("weather Beijing --unit")
    assert result == "Error: missing value for option: --unit Use 'weather --help' to inspect expected values."


def test_lenient_mode_ignores_unknown_option_errors_for_execution():
    registry = CommandRegistry(strict=False)
    registry.register(weather)

    result = registry.parse_and_execute("weather Beijing --bogus 1")
    assert result == "Beijing:celsius:False"


def test_prefix_matching_can_be_disabled():
    registry = CommandRegistry(allow_prefix_match=False)
    registry.register(weather)

    assert registry.parse_and_execute("wea Beijing") == "Error: Unknown command. Did you mean 'weather'?"


def test_exec_tool_is_minimal_outer_tool_bridge():
    registry = CommandRegistry()
    registry.register(weather)
    exec_tool = ExecTool(callback=registry.parse_and_execute)

    result = ExecTool.execute  # keep reference to ensure method exists
    assert callable(result)


def test_builtin_exec_tool_registered_into_registry():
    registry = CommandRegistry()
    registry.register(ExecTool(callback=lambda command, **kwargs: {"command": command, **kwargs}))

    result = registry.parse_and_execute("exec --command echo --timeout 3")
    assert result == {"command": "echo", "timeout": 3}
    assert "Execute a command string through a callback" in registry.parse_and_execute("exec -h")


def test_async_function_command_executes():
    @command(name="ping", description="async ping")
    async def ping(target: str) -> str:
        return f"pong:{target}"

    registry = CommandRegistry()
    registry.register(ping)

    assert registry.parse_and_execute("ping server") == "pong:server"


def test_execution_error_is_wrapped():
    @command(name="boom")
    def boom() -> str:
        raise RuntimeError("broken")

    registry = CommandRegistry()
    registry.register(boom)

    assert registry.parse_and_execute("boom") == "Error: executing boom: broken"


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

    help_text = registry.parse_and_execute("legacy --help")
    assert help_text.startswith("Deprecated: use weather instead")
    assert registry.parse_and_execute("legacy") == "legacy"


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

    result = registry.parse_and_execute("psearch docs -k 7")
    assert result == {"query": "docs", "top_k": 7}
