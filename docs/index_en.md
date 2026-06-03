# agenticli Documentation

Welcome to the agenticli documentation. This page provides an overview of the agenticli package.

## Table of Contents

- [Getting Started](#getting-started)
- [Core Concepts](#core-concepts)
- [Command Definition](#command-definition)
- [API Reference](#api-reference)
- [0.2.0 Migration Guide](migration_0.2.md)

---

## Getting Started

### Installation

```bash
pip install agenticli
```

For Pydantic v2 support:

```bash
pip install "agenticli[pydantic]"
```

### Minimal Example

```python
from typing import Annotated

from agenticli import CommandRegistry, Option, command, command_group


@command_group(name="calc", description="Structured calculator commands")
class Calc:
    @command(name="add", description="Add a sequence of numbers")
    def add(
        self,
        values: Annotated[list[float], Option(positional=True, value_name="value")],
    ) -> dict[str, object]:
        return {"operation": "add", "values": values, "result": sum(values)}


registry = CommandRegistry()
registry.register(Calc)

print(registry.render_llm_context())
result = registry.execute("calc add 10 20 30")
print(result.value if result.ok else result.error.render())
```

---

## Core Concepts

### CommandRegistry

The `CommandRegistry` is the central component of agenticli. It manages command registration, parsing, execution, and help generation.

Key responsibilities:
- Register commands and command groups
- Command hit detection and matching
- Parse positional args, quoted args, long args, short args, boolean flags
- Auto-generate usage/help/LLM prompt
- Argument validation and default value filling
- Execute functions, class commands, and wrapped tools
- Support native async execution APIs
- Support backslash-newline continuation and quote-aware chain splitting
- Unified error wrapping and suggestion prompting
- Support internal injected parameters and execution lifecycle callbacks

### Command Lifecycle

```
command string -> parse -> validate -> execute -> result
                   |
                   v
              error handling with suggestions
```

---

## Command Definition

### Decorator Pattern

Use `@command` to register a function as a CLI command:

```python
from typing import Annotated

from agenticli import command, Option

@command(name="ls", description="List directory contents")
def list_dir(
    path: Annotated[str, Option(description="Directory path")],
    verbose: Annotated[bool, Option(short='v')] = False,
) -> list[str]:
    import os
    files = os.listdir(path)
    if verbose:
        for f in files:
            print(f)
    return files
```

### Command Groups

Use `@command_group` to create a group with subcommands:

```python
from agenticli import command_group, command

@command_group(name="db", description="Database operations")
class Database:
    @command(description="Create a database")
    def create(self, name: str) -> None:
        print(f"Creating {name}")

    @command(description="Drop a database")
    def drop(self, name: str) -> None:
        print(f"Dropping {name}")
```

### Class Inheritance Pattern

Inherit from `CliCommand` for class-based commands:

```python
from dataclasses import dataclass
from agenticli import CliCommand, CommandRegistry

@dataclass
class AddArgs:
    values: list[float]

class AddCommand(CliCommand):
    name = "add"
    description = "Add numbers"
    args_model = AddArgs

    async def run(self, **kwargs) -> dict:
        return {"result": sum(kwargs["values"])}

registry = CommandRegistry()
registry.register(AddCommand())
```

### Wrapping Existing Tools

Use `wrap_tool()` to convert schema-based tools:

```python
from agenticli import CommandRegistry, wrap_tool

class MyTool:
    name = "my_tool"
    description = "My tool description"
    parameters = {
        "type": "object",
        "properties": {
            "value": {"type": "string"}
        },
        "required": ["value"]
    }

    async def execute(self, **kwargs):
        return kwargs

registry = CommandRegistry()
registry.register_spec(wrap_tool(MyTool()))
```

### Importing External Framework Tools

Use helpers from `agenticli.adapters` to wrap existing framework tools into
`CommandSpec` values:

```python
from agenticli.adapters import (
    wrap_autogen_tool,
    wrap_langchain_tool,
    wrap_openai_tool_schema,
)
```

---

## Command Syntax

### Quoted Arguments

Arguments are split with shell-style quoting:

```bash
weather "New York" --unit fahrenheit
say 'single quoted text'
say "arg with \"nested\" quotes"
```

Quoted spaces remain inside one argument.

### Backslash Continuation

A backslash immediately followed by LF or CRLF is normalized to a space before
parsing:

```bash
weather "New York" \
  --unit fahrenheit
```

This is parsed like:

```bash
weather "New York" --unit fahrenheit
```

### Chain Operators and Quotes

`execute(..., chain=True)` and `execute_async(..., chain=True)` support `;`, `&&`, and `||`.
The chain splitter respects quotes, so operators inside quoted arguments do
not split the command:

```bash
registry.execute('say "hello ; world" ; say done', chain=True)
registry.execute('say "hello && world" && say ok', chain=True)
```

The single pipe operator `|`, redirection, glob expansion, variable expansion,
and command substitution are not shell-expanded by agenticli.

---

## Error Handling

Invalid command input returns structured errors instead of raising parser
exceptions:

```python
result = registry.execute('weather "Beijing')
assert result.ok is False
assert result.error.code == "parse_error"

result = registry.execute("/")
assert result.ok is False
assert result.error.code == "unknown_command"

items = registry.execute("missing && weather Beijing", chain=True)
# ["Error: Unknown command"]
```

For command groups, unknown subcommands are reported as unknown commands:

```python
registry.execute("calc missing 1 2")
```

---

## API Reference

### Core Classes

#### CommandRegistry

Central registry for CLI commands.

```python
registry = CommandRegistry(
    strict=True,              # Enable strict parsing
    allow_prefix_match=True,  # Allow prefix matching
    callbacks=None            # ExecutionCallbacks for lifecycle events
)
```

**Methods:**

| Method | Description |
|--------|-------------|
| `register(target)` | Register a command from function, class, or tool |
| `register_spec(spec)` | Register a CommandSpec directly |
| `unregister(name)` | Remove a command |
| `get(name)` | Get CommandSpec by name |
| `has(name)` | Check if command exists |
| `parse(command_str, chain=False)` | Parse without executing; set `chain=True` for command chains |
| `execute(command_str, chain=False)` | Execute and return `ExecutionResult`; set `chain=True` to return a list of values/errors |
| `execute_async(command_str, chain=False)` | Async execute with the same chain behavior |
| `match(text, chain=False, mode="command")` | Match command text, command chains, or natural language with `mode="natural"` |
| `help(command=None)` | Get help text |
| `render_llm_context(detailed=False)` | Generate LLM command context string |
| `commands` | List visible registered command names |

#### CliCommand

Base class for inheritance-based commands.

```python
class MyCommand(CliCommand):
    name = "my_cmd"
    description = "My command"
    args_model = MyArgsModel

    async def run(self, **kwargs) -> Any:
        # Implementation
        pass
```

### Decorators

#### @command

Register a function as a CLI command. Usable bare (`@command`) or with arguments (`@command(...)`); the parentheses are optional when all parameters use their defaults.

```python
@command(
    name=None,           # Command name, defaults to function name
    description="",     # Command description
    aliases=None,       # List of alternative names
    hidden=False,       # Hide from command list
    deprecated=None,    # Deprecation message
)
def my_command(arg1: str, arg2: int = 10) -> str:
    pass
```

Bare form is equivalent to `@command()` with all defaults:

```python
@command
def my_command(arg1: str, arg2: int = 10) -> str:
    pass
```

#### @command_group

Mark a class as a command group.

```python
@command_group(name="group", description="Group description")
class MyGroup:
    @command(description="Subcommand")
    def sub(self, arg: str) -> None:
        pass
```

### Validation Helpers

#### Option

Per-argument CLI metadata for type annotations.

```python
from typing import Annotated
from agenticli import Option

def cmd(
    file: Annotated[str, Option(
        short='f',           # Short flag
        description='Input file',
        positional=True,      # Is positional argument
        value_name='FILE',    # Placeholder in usage
        example='data.txt',   # Example value
        order=1,              # Sort order
        position=0,           # Position index
        hidden=False,         # Hide from help
        repeatable=False,     # Can be repeated
        nargs=None,           # Number of values
        requires=(),         # Required other args
        excludes=(),          # Excluded other args
    )]
) -> None:
    pass
```

#### Injected / Callback / State

Mark parameters as internal injections.

```python
from typing import Annotated
from agenticli import Injected, Callback, State

def cmd(
    arg: str,
    callback: Annotated[object, Callback()] = my_callback,
    state: Annotated[object, State(factory=lambda ctx: {"raw": ctx.raw})] = None,
):
    pass
```

### Built-in Tools

#### ExecTool

Expose an `exec`-style schema tool backed by a callback. `ExecTool` does not
execute a shell by itself; the callback decides what the command string means.

```python
from agenticli import ExecTool

async def execute_callback(command: str, **kwargs):
    return {"command": command, "timeout": kwargs.get("timeout", 60)}

exec_tool = ExecTool(callback=execute_callback)
result = await exec_tool.execute(command="search docs", timeout=30)
```

---

## Error Handling

### CommandError

Structured error with code, message, hint, and suggestion.

```python
error = CommandError(
    code="unknown_command",
    message="Command 'foo' not found",
    suggestion="bar",
    subject="foo"
)
print(error.render())
# Error: Command 'foo' not found Did you mean 'bar'?
```

### ExecutionCallbacks

Lifecycle callbacks for logging, monitoring, and auditing.

```python
def before(ctx):
    print(f"Executing: {ctx.command}")

def after(ctx):
    print(f"Result: {ctx.result}")

def on_error(ctx):
    print(f"Error: {ctx.error.code}")

registry = CommandRegistry(
    callbacks=ExecutionCallbacks(
        before_execute=before,
        after_execute=after,
        on_error=on_error,
    )
)
```

---

## Chain Execution

Execute multiple commands with operators:

```python
# Sequential: execute all
registry.execute("cmd1 ; cmd2", chain=True)

# AND: stop if any fails
registry.execute("cmd1 && cmd2", chain=True)

# OR: stop if any succeeds
registry.execute("cmd1 || cmd2", chain=True)

# Operators inside quotes are treated as argument text
registry.execute('cmd1 "literal && text" ; cmd2', chain=True)
```

---

## Help Syntax

Recommended:
```bash
calc --help
calc add --help
```

Alternative:
```bash
--help
--help calc
```
