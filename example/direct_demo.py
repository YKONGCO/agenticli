"""Comprehensive demo of direct command definition and parsing APIs.

This demo showcases all the ways to define commands and use the parsing/execution
APIs directly without needing an LLM provider.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from agenticli import (
    Callback,
    CliCommand,
    CommandError,
    CommandRegistry,
    ExecutionCallbacks,
    ExecutionContext,
    ExecutionResult,
    HitResult,
    Injected,
    Option,
    State,
    command,
    command_from_model,
    command_from_method,
    command_group,
    get_registered_commands,
    wrap_tool,
)


# =============================================================================
# 1. FUNCTION-BASED COMMANDS (using @command decorator)
# =============================================================================


@command(name="greet", description="Greet someone with a custom message")
def greet(name: Annotated[str, Option(description="The name to greet")]) -> dict[str, str]:
    """Greet someone with a custom message."""
    return {"message": f"Hello, {name}!"}


@command(name="add", description="Add two numbers")
def add(
    a: Annotated[float, Option(description="First number")],
    b: Annotated[float, Option(description="Second number")],
) -> dict[str, float]:
    """Add two numbers together."""
    return {"result": a + b}


@command(
    name="echo",
    description="Echo back text with optional transformation",
    aliases=["repeat", "copy"],
)
def echo(
    text: Annotated[str, Option(description="Text to echo back")],
    upper: Annotated[bool, Option(short="u", description="Convert to uppercase")] = False,
    times: Annotated[int, Option(short="n", description="Number of times to repeat")] = 1,
) -> dict[str, Any]:
    """Echo text with optional transformations."""
    result = text.upper() if upper else text
    return {"echoed": result * times, "times": times}


# =============================================================================
# 2. COMMAND GROUPS (using @command_group decorator)
# =============================================================================


@command_group(name="string", description="String manipulation commands")
class StringCommands:
    @command(name="upper", description="Convert text to uppercase")
    def upper(self, text: Annotated[str, Option(positional=True, description="Text to convert")]) -> dict[str, str]:
        return {"result": text.upper()}

    @command(name="lower", description="Convert text to lowercase")
    def lower(self, text: Annotated[str, Option(positional=True, description="Text to convert")]) -> dict[str, str]:
        return {"result": text.lower()}

    @command(name="reverse", description="Reverse a string")
    def reverse(self, text: Annotated[str, Option(positional=True, description="Text to reverse")]) -> dict[str, str]:
        return {"result": text[::-1]}


# =============================================================================
# 3. INJECTED DEPENDENCIES (Callback, State, Injected)
# =============================================================================


def my_callback(msg: str) -> None:
    print(f"[Callback] {msg}")


@command(name="with_state", description="Command demonstrating State injection")
def with_state(
    value: Annotated[str, Option(description="A value to process")],
    state: Annotated[dict, State(factory=lambda ctx: {"command": ctx.command, "raw": ctx.raw})] = None,
) -> dict[str, Any]:
    """Command that receives execution context via State injection."""
    state = state or {}
    return {"value": value, "state": state}


@command(name="with_callback", description="Command demonstrating Callback injection")
def with_callback(
    value: Annotated[str, Option(description="A value to process")],
    callback: Annotated[object, Callback()] = my_callback,
) -> dict[str, str]:
    """Command that receives a callback via injection."""
    callback(f"[with_callback] processing: {value}")
    return {"value": value, "callback_used": True}


@command(name="with_injected", description="Command demonstrating Injected dependency")
def with_injected(
    value: Annotated[str, Option(description="A value to process")],
    injected: Annotated[str, Injected(value="hardcoded_value")] = "",
) -> dict[str, str]:
    """Command with a hardcoded injected value."""
    return {"value": value, "injected": injected}


# =============================================================================
# 4. COMPLEX ARGUMENTS (lists, tuples, enums, flags)
# =============================================================================


@command(name="sum", description="Sum a list of numbers")
def sum_values(
    values: Annotated[list[float], Option(positional=True, description="Numbers to sum")],
) -> dict[str, Any]:
    """Sum multiple numbers."""
    return {"values": values, "result": sum(values), "count": len(values)}


@command(name="stats", description="Calculate basic statistics")
def stats(
    values: Annotated[list[float], Option(positional=True, description="Numbers to analyze")],
    precision: Annotated[int, Option(short="p", description="Decimal precision")] = 2,
) -> dict[str, Any]:
    """Calculate min, max, mean of values."""
    if not values:
        return {"error": "No values provided"}
    return {
        "min": min(values),
        "max": max(values),
        "mean": sum(values) / len(values),
        "count": len(values),
        "precision": precision,
    }


@command(name="range", description="Generate a range of numbers")
def number_range(
    start: Annotated[int, Option(description="Start of range")],
    end: Annotated[int, Option(description="End of range (exclusive)")],
    step: Annotated[int, Option(short="s", description="Step size")] = 1,
) -> dict[str, list[int]]:
    """Generate a range of numbers."""
    return {"range": list(range(start, end, step)), "start": start, "end": end, "step": step}


@command(name="config", description="Manage configuration")
def config(
    action: Annotated[Literal["get", "set", "delete"], Option(description="Action to perform")],
    key: Annotated[str, Option(description="Configuration key")],
    value: Annotated[str | None, Option(description="Value (for set action)")] = None,
) -> dict[str, Any]:
    """Configuration management command with enum-like argument."""
    if action == "get":
        return {"action": "get", "key": key, "value": None}
    elif action == "set":
        return {"action": "set", "key": key, "value": value}
    else:
        return {"action": "delete", "key": key}


# =============================================================================
# 5. ERROR HANDLING AND VALIDATION
# =============================================================================


@command(name="divide", description="Divide two numbers with validation")
def divide(
    numerator: Annotated[float, Option(description="Numerator")],
    denominator: Annotated[float, Option(description="Denominator")],
) -> dict[str, float]:
    """Divide two numbers."""
    if denominator == 0:
        raise ValueError("Cannot divide by zero")
    return {"result": numerator / denominator, "numerator": numerator, "denominator": denominator}


@command(name="require", description="Command with required arguments")
def require(
    name: Annotated[str, Option(description="Required name")],
    optional: Annotated[str | None, Option(description="Optional value")] = None,
) -> dict[str, Any]:
    """Command demonstrating required vs optional arguments."""
    return {"name": name, "optional": optional}


# =============================================================================
# 6. CLI-COMMAND CLASS (Inheritance-based)
# =============================================================================


@dataclass
class GreetInput:
    """Input model for GreetCommand."""

    name: str


class GreetCommand(CliCommand):
    """Greet command using class-based definition."""

    name = "class_greet"
    description = "Greet using CliCommand class"

    args_model = GreetInput

    async def run(self, name: str) -> dict[str, str]:
        return {"message": f"Hello, {name}! (from CliCommand)"}


# =============================================================================
# 7. COMMAND_FROM_MODEL (dataclass-based)
# =============================================================================


@dataclass
class MultiplyInput:
    """Input model for multiply command."""

    a: float
    b: float
    precision: int = 2


def multiply_handler(a: float, b: float, precision: int = 2) -> dict[str, Any]:
    """Handler for multiply command."""
    return {"result": round(a * b, precision), "a": a, "b": b, "precision": precision}


multiply_command = command_from_model(
    name="multiply",
    model=MultiplyInput,
    handler=multiply_handler,
    description="Multiply two numbers using dataclass model",
)


# =============================================================================
# 8. COMMAND_FROM_METHOD
# =============================================================================


class Calculator:
    """Calculator class for method-based commands."""

    async def run(self, operation: str, a: float, b: float) -> dict[str, Any]:
        if operation == "add":
            return {"result": a + b, "operation": operation}
        elif operation == "sub":
            return {"result": a - b, "operation": operation}
        elif operation == "mul":
            return {"result": a * b, "operation": operation}
        elif operation == "div":
            if b == 0:
                raise ValueError("Division by zero")
            return {"result": a / b, "operation": operation}
        return {"error": f"Unknown operation: {operation}"}


calculator_command = command_from_method(
    name="calc_method",
    target=Calculator(),
    method_name="run",
    description="Calculator using command_from_method",
)


# =============================================================================
# 9. WRAP_TOOL (wrapping existing tools)
# =============================================================================


class ExistingTool:
    """Simulated existing tool with execute method."""

    name = "wrapped_tool"
    description = "A pre-existing tool to wrap"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Message to process"},
                "uppercase": {"type": "boolean", "description": "Whether to uppercase"},
            },
            "required": ["message"],
        }

    def execute(self, message: str, uppercase: bool = False) -> dict[str, str]:
        return {"processed": message.upper() if uppercase else message}


wrapped_command = wrap_tool(ExistingTool(), name="wrapped", description="Wrapped existing tool")


# =============================================================================
# 10. LIFECYCLE CALLBACKS
# =============================================================================


def before_execute(ctx: ExecutionContext) -> None:
    print(f"  [BEFORE] Command: {ctx.command}, Args: {ctx.args}")


def after_execute(ctx: ExecutionContext) -> None:
    print(f"  [AFTER] Result: {ctx.result}")


def on_error(ctx: ExecutionContext) -> None:
    print(f"  [ERROR] {ctx.error}")


callbacks_registry = CommandRegistry(
    callbacks=ExecutionCallbacks(
        before_execute=before_execute,
        after_execute=after_execute,
        on_error=on_error,
    )
)


# =============================================================================
# 9. BUILD AND CONFIGURE REGISTRY
# =============================================================================


def build_registry() -> CommandRegistry:
    """Build a registry with all demo commands."""
    registry = CommandRegistry()

    # Function commands
    registry.register(greet)
    registry.register(add)
    registry.register(echo)
    registry.register(with_state)
    registry.register(with_callback)
    registry.register(with_injected)
    registry.register(sum_values)
    registry.register(stats)
    registry.register(number_range)
    registry.register(config)
    registry.register(divide)
    registry.register(require)

    # Command group
    registry.register(StringCommands)

    # Class-based command
    registry.register(GreetCommand)

    # Model-based command
    registry.register_spec(multiply_command)

    # Method-based command
    registry.register_spec(calculator_command)

    # Wrapped tool
    registry.register_spec(wrapped_command)

    return registry


def build_callbacks_registry() -> CommandRegistry:
    """Build registry with lifecycle callbacks."""
    # Function commands
    callbacks_registry.register(greet)
    callbacks_registry.register(add)
    callbacks_registry.register(echo)
    callbacks_registry.register(with_state)
    callbacks_registry.register(with_callback)
    callbacks_registry.register(with_injected)
    callbacks_registry.register(sum_values)
    callbacks_registry.register(stats)
    callbacks_registry.register(number_range)
    callbacks_registry.register(config)
    callbacks_registry.register(divide)
    callbacks_registry.register(require)

    # Command group
    callbacks_registry.register(StringCommands)

    # Class-based command
    callbacks_registry.register(GreetCommand)

    # Model-based command
    callbacks_registry.register_spec(multiply_command)

    # Method-based command
    callbacks_registry.register_spec(calculator_command)

    # Wrapped tool
    callbacks_registry.register_spec(wrapped_command)

    return callbacks_registry


# =============================================================================
# 10. DEMO FUNCTIONS
# =============================================================================


def demo_parse_and_execute(registry: CommandRegistry) -> None:
    """Demonstrate parse_and_execute - the simplest way to run a command."""
    print("\n" + "=" * 70)
    print("DEMO: parse_and_execute (parse string and execute in one call)")
    print("=" * 70)

    test_cases = [
        'greet --name "World"',
        "add --a 10 --b 20",
        'echo --text "hello" --upper --times 3',
        "sum 10 20 30 40 50",
        'config --action get --key "database.host"',
        "stats 10 20 30 40 50 --precision 3",
        "range --start 1 --end 10 --step 2",
        'string upper --text "hello world"',
    ]

    for cmd in test_cases:
        print(f"\nInput:  {cmd}")
        result = registry.parse_and_execute(cmd)
        print(f"Output: {json.dumps(result, indent=2, ensure_ascii=False)}")


def demo_execute_with_result(registry: CommandRegistry) -> None:
    """Demonstrate execute - returns ExecutionResult with full details."""
    print("\n" + "=" * 70)
    print("DEMO: execute (returns ExecutionResult with full details)")
    print("=" * 70)

    test_cases = [
        "add --a 5 --b 3",
        "divide --numerator 10 --denominator 0",  # Will error
        "unknown_command",  # Will error
    ]

    for cmd in test_cases:
        print(f"\nInput:  {cmd}")
        result: ExecutionResult = registry.execute(cmd)
        print(f"  ok: {result.ok}")
        print(f"  command: {result.command}")
        if result.ok:
            print(f"  value: {json.dumps(result.value, indent=4, ensure_ascii=False)}")
        else:
            print(f"  error.code: {result.error.code if result.error else 'N/A'}")
            print(f"  error.message: {result.error.message if result.error else 'N/A'}")
            print(f"  error.render(): {result.error.render() if result.error else 'N/A'}")


def demo_parse_only(registry: CommandRegistry) -> None:
    """Demonstrate parse - just parse without execution."""
    print("\n" + "=" * 70)
    print("DEMO: parse (just parse, don't execute)")
    print("=" * 70)

    test_cases = [
        'add --a "10" --b "20"',
        'greet --name "Alice"',
        "stats --precision 2 1 2 3 4 5",
    ]

    for cmd in test_cases:
        print(f"\nInput:  {cmd}")
        parsed = registry.parse(cmd)
        if parsed:
            print(f"  command: {parsed.command}")
            print(f"  args: {parsed.args}")
            print(f"  raw: {parsed.raw}")
            if parsed.errors:
                print(f"  errors: {parsed.errors}")
        else:
            print("  (no parse result)")


def demo_hit_detection(registry: CommandRegistry) -> None:
    """Demonstrate detect - find commands in natural language text."""
    print("\n" + "=" * 70)
    print("DEMO: detect (find commands in natural language)")
    print("=" * 70)

    test_cases = [
        "Can you add 5 and 10 for me?",
        "I want to convert some text to uppercase",
        "Please calculate the sum of 1, 2, 3, 4, 5",
        "What's the weather like?",
    ]

    for text in test_cases:
        print(f"\nInput:  {text}")
        hit: HitResult = registry.detect(text)
        print(f"  command: {hit.command}")
        print(f"  confidence: {hit.confidence}")
        if hit.suggested_args:
            print(f"  suggested_args: {hit.suggested_args}")


def demo_match_command(registry: CommandRegistry) -> None:
    """Demonstrate match_command - check if text is a command."""
    print("\n" + "=" * 70)
    print("DEMO: match_command (check if text is a command)")
    print("=" * 70)

    test_cases = [
        "add --a 1 --b 2",
        "/add 1 2",
        "greet --name Alice",
        "hello world",
    ]

    for text in test_cases:
        print(f"\nInput:  {text}")
        match = registry.match_command(text)
        print(f"  is_command: {match.confidence > 0}")
        print(f"  confidence: {match.confidence}")
        print(f"  match_type: {match.match_type}")
        if match.args_str:
            print(f"  args_str: {match.args_str}")


def demo_help_rendering(registry: CommandRegistry) -> None:
    """Demonstrate help rendering."""
    print("\n" + "=" * 70)
    print("DEMO: render_help (generate help text)")
    print("=" * 70)

    print("\n--- All commands help ---")
    print(registry.render_help())

    print("\n--- Specific command help ---")
    print(registry.render_help("echo"))

    print("\n--- Command group help ---")
    print(registry.render_help("string"))


def demo_llm_prompt(registry: CommandRegistry) -> None:
    """Demonstrate LLM prompt generation."""
    print("\n" + "=" * 70)
    print("DEMO: get_llm_prompt (generate prompt for LLM)")
    print("=" * 70)

    print("\n--- Brief prompt ---")
    print(registry.get_llm_prompt(detailed=False))

    print("\n--- Detailed prompt ---")
    print(registry.get_llm_prompt(detailed=True))


def demo_registry_inspection(registry: CommandRegistry) -> None:
    """Demonstrate registry inspection methods."""
    print("\n" + "=" * 70)
    print("DEMO: Registry inspection (commands, has, get, len)")
    print("=" * 70)

    print(f"\nNumber of commands: {len(registry)}")
    print(f"Command list: {registry.commands}")

    print(f"\nHas 'greet': {registry.has('greet')}")
    print(f"Has 'unknown': {registry.has('unknown')}")

    spec = registry.get("add")
    if spec:
        print(f"\nCommand spec for 'add':")
        print(f"  name: {spec.name}")
        print(f"  description: {spec.description}")
        print(f"  args: {[a.name for a in spec.args]}")
        print(f"  aliases: {spec.aliases}")
        print(f"  usage: {spec.usage}")


def demo_error_scenarios(registry: CommandRegistry) -> None:
    """Demonstrate various error scenarios."""
    print("\n" + "=" * 70)
    print("DEMO: Error scenarios")
    print("=" * 70)

    test_cases = [
        ("", "Empty command"),
        ("unknown", "Unknown command"),
        ("require", "Missing required argument"),
        ("divide --numerator 10 --denominator 0", "Division by zero"),
        ("echo --text hello --invalid-option", "Invalid option"),
    ]

    for cmd, description in test_cases:
        print(f"\n[{description}]")
        print(f"Input: '{cmd}'")
        result = registry.execute(cmd)
        print(f"  ok: {result.ok}")
        if not result.ok and result.error:
            print(f"  error.code: {result.error.code}")
            print(f"  error.message: {result.error.message}")
            if result.error.suggestion:
                print(f"  error.suggestion: {result.error.suggestion}")
            if result.error.hint:
                print(f"  error.hint: {result.error.hint}")


def demo_lifecycle_callbacks() -> None:
    """Demonstrate lifecycle callbacks."""
    print("\n" + "=" * 70)
    print("DEMO: Lifecycle callbacks (before_execute, after_execute, on_error)")
    print("=" * 70)

    registry = build_callbacks_registry()

    print("\n--- Successful execution with callbacks ---")
    result = registry.execute("add --a 5 --b 10")
    print(f"Final result: {result.value}")

    print("\n--- Failed execution with callbacks ---")
    result = registry.execute("divide --numerator 10 --denominator 0")
    print(f"Final result ok: {result.ok}")


def demo_all_features() -> None:
    """Run all demonstration functions."""
    print("=" * 70)
    print("LLMCLI DIRECT COMMAND DEFINITION AND PARSING DEMO")
    print("=" * 70)

    registry = build_registry()

    demo_parse_and_execute(registry)
    demo_execute_with_result(registry)
    demo_parse_only(registry)
    demo_hit_detection(registry)
    demo_match_command(registry)
    demo_help_rendering(registry)
    demo_llm_prompt(registry)
    demo_registry_inspection(registry)
    demo_error_scenarios(registry)
    demo_lifecycle_callbacks()

    print("\n" + "=" * 70)
    print("DEMO COMPLETE")
    print("=" * 70)


async def demo_async_execution() -> None:
    """Demonstrate async command execution."""
    print("\n" + "=" * 70)
    print("DEMO: Async execution (for async commands)")
    print("=" * 70)

    registry = build_registry()

    # Note: registry.execute() is synchronous but internally handles async commands
    # via run_sync(). For demonstration, we call the async method directly.

    # Class-based commands have async run() method
    cmd = GreetCommand()
    result = await cmd.run(name="AsyncWorld")
    print(f"class_greet result (direct async call): {result}")

    # Method-based command is also async
    calc = Calculator()
    result = await calc.run(operation="add", a=5, b=3)
    print(f"calc_method result (direct async call): {result}")


def main() -> None:
    """Main entry point."""
    demo_all_features()
    asyncio.run(demo_async_execution())


if __name__ == "__main__":
    main()
