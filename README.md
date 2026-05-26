<div align="center">

# ⚡ agenticli

**Expose tools as lightweight CLI commands for LLM agents** 🔧✨

[English](README.md) | [中文](README_zh.md)

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![PyPI](https://img.shields.io/badge/pypi-agenticli-blue.svg)](https://pypi.org/project/agenticli/)
[![Version](https://img.shields.io/badge/version-0.2.0-blue.svg)](https://pypi.org/project/agenticli/#history)
[![GitHub](https://img.shields.io/badge/github-YKONGCO/agenticli-blue.svg)](https://github.com/YKONGCO/agenticli)

</div>

---

## ✨ What is this?

**agenticli** converts functions, classes, and schema-based tools into a stable CLI semantic layer. Instead of flooding prompts with large schemas, LLMs just output a single command string.

> 💡 **Philosophy: bash is everything.** The command string is the most stable, restrained, and observable intermediate representation between LLMs and tool systems.

## 🎯 When to use agenticli?

| Scenario | agenticli helps? |
|----------|---------------|
| You have many tools/functions and need a unified interface for LLMs | ✅ |
| You don't want massive schemas injected into prompts | ✅ |
| You want models to see minimal hints, expanding via `--help` | ✅ |
| You want validation, help, errors, and lifecycle in one place | ✅ |

## 🚀 Quick Start

```bash
pip install agenticli
```

```python
from typing import Annotated
from agenticli import CommandRegistry, Option, command, command_group

@command_group(name="calc", description="Calculator commands")
class Calc:
    @command(name="add", description="Add numbers")
    def add(self,
        values: Annotated[list[float], Option(positional=True, value_name="n")]
    ) -> dict:
        return {"result": sum(values)}

registry = CommandRegistry()
registry.register(Calc)

# LLM sees this minimal command context:
print(registry.render_llm_context())
# -> You can use the following CLI commands:
#     calc: Calculator commands

result = registry.execute("calc add 10 20 30")
print(result.value if result.ok else result.error.render())
# -> {"result": 60.0}
```

## 🏗️ Core Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        LLM Output                            │
│                    "calc add 10 20 30"                      │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                      CommandRegistry                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐  │
│  │  Parse   │─▶│ Validate │─▶│ Execute  │─▶│   Result   │  │
│  └──────────┘  └──────────┘  └──────────┘  └────────────┘  │
│                                                             │
│  • Command hit/matching      • Lifecycle callbacks          │
│  • Help generation           • Error with suggestions        │
│  • Argument injection        • Chain execution (&&, ||, ;)  │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    Your Functions / Tools                    │
└─────────────────────────────────────────────────────────────┘
```

## 📋 Key Features

| Feature | Description |
|---------|-------------|
| 🔌 **Multiple Registrations** | Decorators, class inheritance, dataclass, Pydantic, schema wrapping |
| ⚡ **CLI Parsing** | Positional args, quoted args, `--option value`, `-o value`, `--opt=val`, flags |
| 📖 **Smart Help** | Auto-generated usage, help text, LLM prompts |
| ✅ **Validation** | Type coercion, `requires`/`excludes`, enums |
| 💡 **Suggestions** | "Did you mean X?" for unknown commands/options/enums |
| 🔄 **Lifecycle Hooks** | `before_execute`, `after_execute`, `on_error` |
| 🏃 **Internal Injection** | Hide callbacks/state from CLI, inject at runtime |
| 🔗 **Chain Execution** | Quote-aware `cmd1 && cmd2 || cmd3 ; cmd4` |
| ⏳ **Async Execution** | Native `execute_async(..., chain=False)` |
| 🔌 **Tool Import** | Convert LangChain / AutoGen / OpenAI-style tools into `CommandSpec` |

## 📝 Registration Patterns

### 1️⃣ Decorator (Most Common)

```python
from typing import Annotated
from agenticli import command, Option

@command(name="ls", description="List directory")
def ls(
    path: Annotated[str, Option(short='p', description="Directory path")],
    verbose: Annotated[bool, Option(short='v')] = False,
) -> list[str]:
    import os
    return os.listdir(path)
```

### 2️⃣ Command Group

```python
from agenticli import command_group, command

@command_group(name="db", description="Database operations")
class Database:
    @command(description="Create database")
    def create(self, name: str) -> None: ...

    @command(description="Drop database")
    def drop(self, name: str) -> None: ...
```

### 3️⃣ Wrap Existing Tools

```python
from agenticli import wrap_tool

class MyTool:
    name = "my_tool"
    description = "Does something"
    parameters = {"type": "object", "properties": {"x": {"type": "int"}}}
    async def execute(self, **kwargs): return kwargs

registry.register_spec(wrap_tool(MyTool()))
```

### 4️⃣ Class Inheritance

```python
from agenticli import CliCommand, CommandRegistry

class AddCommand(CliCommand):
    name = "add"
    description = "Add numbers"
    args_model = AddArgs

    async def run(self, **kwargs) -> dict:
        return {"result": sum(kwargs["values"])}

registry.register(AddCommand())
```

## 🤖 LLM Integration

### Minimal Tool Schema

Expose only one `exec` tool to the LLM:

```python
from agenticli import ExecTool

def run_command(command: str, **kwargs):
    result = registry.execute(command)
    return result.value if result.ok else result.error.render()

exec_tool = ExecTool(callback=run_command)
# Tool schema: {name: "exec", params: {command: string, timeout?: int}}
```

### Lifecycle Callbacks

```python
from agenticli import ExecutionCallbacks

def on_error(ctx):
    print(f"Error: {ctx.error.code} - {ctx.error.message}")

registry = CommandRegistry(
    callbacks=ExecutionCallbacks(on_error=on_error)
)
```

### Internal Parameter Injection

```python
from typing import Annotated
from agenticli import Callback, State, command

@command(name="process")
def process(
    data: list[str],
    cache: Annotated[object, State(factory=lambda ctx: load_cache())] = None,
):
    # cache is injected automatically, hidden from CLI
    return cached_transform(data, cache)
```

## 🔌 Import External Tools

You can wrap existing framework tools into `agenticli` commands through
functions in `agenticli.adapters`:

```python
from agenticli import CommandRegistry
from agenticli.adapters import (
    wrap_autogen_tool,
    wrap_langchain_tool,
    wrap_openai_tool_schema,
)

registry = CommandRegistry()

registry.register_spec(wrap_langchain_tool(my_langchain_tool))
registry.register_spec(wrap_autogen_tool(my_autogen_tool))
registry.register_spec(
    wrap_openai_tool_schema(
        name="search_docs",
        description="Search docs",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        handler=lambda query: {"query": query},
    )
)
```

## ⚡ Async API

`agenticli` now supports native async execution:

```python
result = await registry.execute_async("calc add 1 2 3")
items = await registry.execute_async("cmd1 ; cmd2", chain=True)
```

## 🧾 Command Syntax

Command parsing uses shell-style quoting for arguments:

```bash
weather "New York" --unit fahrenheit
say 'single quoted text'
say "arg with \"nested\" quotes"
```

Backslash-newline continuations are normalized before parsing:

```bash
weather "New York" \
  --unit fahrenheit
```

Command chains support `;`, `&&`, and `||`. Operators inside quotes stay part
of the argument instead of splitting the chain:

```bash
say "hello ; world" ; say done
say "hello && world" && say ok
```

Invalid input returns structured errors:

```python
result = registry.execute('weather "Beijing')
assert result.ok is False
assert result.error.code == "parse_error"

registry.execute("missing && weather Beijing", chain=True)
# ["Error: Unknown command"]
```

## 📦 Stable API

```python
# Core
CommandRegistry
CommandRegistry.register(target)
CommandRegistry.register_spec(spec)
CommandRegistry.unregister(name)
CommandRegistry.get(name)
CommandRegistry.has(name)
CommandRegistry.parse(command_str, chain=False)
CommandRegistry.execute(command_str, chain=False)
CommandRegistry.execute_async(command_str, chain=False)
CommandRegistry.match(text, chain=False, mode="command")
CommandRegistry.help(command=None)
CommandRegistry.render_llm_context(detailed=False)
CommandRegistry.commands

# Decorators
command(name=None, description="", aliases=None, hidden=False, deprecated=None)
command_group(name, description)
get_registered_commands()
clear_commands()

# Helpers
CliCommand
wrap_tool(tool)
command_from_model(name, model, handler)
command_from_method(name, target, method_name)
wrap_langchain_tool(tool)
wrap_autogen_tool(tool)
wrap_openai_tool_schema(name, parameters, handler, ...)
Option
Injected / Callback / State
ExecutionCallbacks
ExecTool
```

Upgrading from 0.1.x? See [docs/migration_0.2.md](docs/migration_0.2.md).

## 💡 Examples

See [example/demo.py](example/demo.py) for a complete calc system with OpenAI/Anthropic integration:

```bash
pip install "agenticli[examples]"
python -m example.demo --provider openai
python -m example.demo --provider anthropic
```

## 📚 Documentation

| Language | Link |
|----------|------|
| 🇺🇸 English README | [README.md](README.md) |
| 🇨🇳 中文 README | [README_zh.md](README_zh.md) |
| 🇺🇸 English | [docs/index_en.md](docs/index_en.md) |
| 🇨🇳 中文 | [docs/index_zh.md](docs/index_zh.md) |
| Migration | [docs/migration_0.2.md](docs/migration_0.2.md) |

## 📄 License

MIT
