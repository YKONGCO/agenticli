<div align="center">

# ⚡ agenticli

**Expose tools as lightweight CLI commands for LLM agents** 🔧✨

[English](README.md) | [中文](README_zh.md)

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![PyPI](https://img.shields.io/badge/pypi-agenticli-blue.svg)](https://pypi.org/project/agenticli/)
[![Version](https://img.shields.io/badge/version-0.2.5-blue.svg)](https://pypi.org/project/agenticli/#history)
[![GitHub](https://img.shields.io/badge/github-YKONGCO/agenticli-blue.svg)](https://github.com/YKONGCO/agenticli)

</div>

---

**agenticli** turns functions, classes, and schema-based tools into a stable
CLI semantic layer. Instead of flooding prompts with full JSON Schemas, the
LLM sees a one-line list of commands and outputs a single command string.

## 📊 Effect: fewer tokens, in both directions

Measured with `cl100k_base` on a 15-tool catalog and a 3-arg `read_file` call:

|                       | Definition (system prompt) | Call (model output) |
|-----------------------|---------------------------:|--------------------:|
| OpenAI `tools=[]`     | 1,543 tokens               | 34 tokens           |
| `render_llm_context`  |    86 tokens               | 18 tokens           |
| **Saved**             | **94.4%** (1,457 tokens)   | **47.1%** (16 tokens) |

Argument names, types, and constraints are still available — pulled from
`<cmd> --help` at call time, not stuffed into every system prompt.

```bash
pip install agenticli
```

## 🚀 Quick Start

```python
from typing import Annotated
from agenticli import CommandRegistry, Option, command, command_group

@command_group(name="calc", description="Calculator commands")
class Calc:
    @command(name="add", description="Add numbers")
    def add(self,
        values: Annotated[list[float], Option(positional=True, value_name="n")],
    ) -> dict:
        return {"result": sum(values)}

registry = CommandRegistry()
registry.register(Calc)

print(registry.render_llm_context())
# You can use the following CLI commands:
#   calc: Calculator commands
# Use <command> --help when you need full argument details.

print(registry.execute("calc add 10 20 30").value)
# {"result": 60.0}
```

## 🤖 LLM Integration

Expose a single `exec` tool to the model — it outputs a command string, you
execute it and feed the result back.

```python
from agenticli import ExecTool

def run_command(command: str, **kwargs):
    result = registry.execute(command)
    return result.value if result.ok else result.error.render()

exec_tool = ExecTool(callback=run_command)
# Tool schema: {name: "exec", params: {command: string, timeout?: int}}
```

## 📝 A Few Patterns

```python
# Decorator
@command(name="ls", description="List directory")
def ls(
    path: Annotated[str, Option(short='p')],
    verbose: Annotated[bool, Option(short='v')] = False,
) -> list[str]:
    return os.listdir(path)

# Group
@command_group(name="db", description="Database operations")
class Database:
    @command(description="Create database")
    def create(self, name: str) -> None: ...
    @command(description="Drop database")
    def drop(self, name: str) -> None: ...

# Wrap an existing tool
registry.register_spec(wrap_tool(MyTool()))

# Class-based
class AddCommand(CliCommand):
    name = "add"
    async def run(self, **kwargs) -> dict:
        return {"result": sum(kwargs["values"])}

registry.register(AddCommand())
```

## ⚡ Async

```python
result = await registry.execute_async("calc add 1 2 3")
items = await registry.execute_async("cmd1 ; cmd2", chain=True)
```

## 📚 More

- **Examples**: [example/](example/) — calc, provider integration, Linux-like shell, auto-discovery, etc.
- **Docs**: [docs/index_en.md](docs/index_en.md) · [中文](docs/index_zh.md)
- **Migration from 0.1.x**: [docs/migration_0.2.md](docs/migration_0.2.md)
- **API reference**: see `## 📦 Stable API` in [docs/index_en.md](docs/index_en.md)

## 📄 License

MIT
