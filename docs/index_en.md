# agenticli Documentation

Welcome to the agenticli documentation. This page provides an overview of the agenticli package.

## Table of Contents

- [Getting Started](#getting-started)
- [Core Concepts](#core-concepts)
- [Command Definition](#command-definition)
- [API Reference](#api-reference)

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

print(registry.get_llm_prompt())
print(registry.parse_and_execute("calc add 10 20 30"))
```

---

## Core Concepts

### CommandRegistry

The `CommandRegistry` is the central component of agenticli. It manages command registration, parsing, execution, and help generation.

Key responsibilities:
- Register commands and command groups
- Command hit detection and matching
- Parse positional args, long args, short args, boolean flags
- Auto-generate usage/help/LLM prompt
- Argument validation and default value filling
- Execute functions, class commands, and wrapped tools
- Support native async execution APIs
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

Use helpers from `agenticli.tooling` to wrap existing framework tools into
`CommandSpec` values:

```python
from agenticli.tooling import (
    wrap_autogen_tool,
    wrap_langchain_tool,
    wrap_openai_tool_schema,
)
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
| `parse(command_str)` | Parse without executing |
| `parse_and_execute(command_str)` | Parse and execute, return value or error |
| `parse_and_execute_async(command_str)` | Async parse and execute |
| `execute(command_str)` | Execute and return ExecutionResult |
| `execute_async(command_str)` | Async execute and return ExecutionResult |
| `chain_execute(command_str)` | Execute a chain of commands |
| `chain_execute_async(command_str)` | Async execute a chain of commands |
| `render_help(command)` | Get help text |
| `get_llm_prompt(detailed)` | Generate LLM context string |

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

Register a function as a CLI command.

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

Execute commands through a callback.

```python
from agenticli import ExecTool, CommandRegistry

def execute_callback(command: str, **kwargs):
    return subprocess.run(command, shell=True, timeout=kwargs.get("timeout", 60))

exec_tool = ExecTool(callback=execute_callback)
result = exec_tool.execute(command="ls -la")
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
registry.chain_execute("cmd1 ; cmd2")

# AND: stop if any fails
registry.chain_execute("cmd1 && cmd2")

# OR: stop if any succeeds
registry.chain_execute("cmd1 || cmd2")
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
