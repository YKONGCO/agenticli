<div align="center">

# ⚡ agenticli

**把工具暴露为适合 LLM agent 使用的轻量 CLI 命令层** 🔧✨

[English](README.md) | [中文](README_zh.md)

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![PyPI](https://img.shields.io/badge/pypi-agenticli-blue.svg)](https://pypi.org/project/agenticli/)
[![Version](https://img.shields.io/badge/version-0.2.5-blue.svg)](https://pypi.org/project/agenticli/#history)
[![GitHub](https://img.shields.io/badge/github-YKONGCO/agenticli-blue.svg)](https://github.com/YKONGCO/agenticli)

</div>

---

## ✨ 这是什么？

**agenticli** 可以把函数、类和基于 schema 的工具转换成稳定的 CLI 语义层。相比把大段 schema 直接塞进 prompt，LLM 只需要输出一条命令字符串。

> 💡 **设计理念：bash is everything.** 命令字符串是 LLM 与工具系统之间最稳定、最克制、也最容易观察的中间表示。

## 🎯 适合什么场景？

| 场景 | agenticli 是否适合 |
|------|-------------------|
| 你有很多工具/函数，希望给 LLM 一个统一接口 | ✅ |
| 你不想把大量 schema 注入 prompt | ✅ |
| 你希望模型先看到极简提示，需要时再通过 `--help` 展开 | ✅ |
| 你想把校验、帮助、错误提示和生命周期钩子统一到一处 | ✅ |

## 📊 效果:token 两端都省

用 `cl100k_base` 在 15 个工具的 catalog + 一次 3 参数的 `read_file` 调用上测得:

|                       | 定义(系统提示) | 调用(模型输出) |
|-----------------------|---------------:|---------------:|
| OpenAI `tools=[]`     | 1,543 tokens   | 34 tokens      |
| `render_llm_context`  |    86 tokens   | 18 tokens      |
| **节省**              | **94.4%**(1,457)| **47.1%**(16) |

参数名、类型、约束模型照样能看到——只是从“每轮都贴 prompt”变成“调用时
再 `<cmd> --help`”。复现:

```bash
uv run --with tiktoken python scripts/token_benchmark.py
```

## 🚀 快速开始

```bash
pip install agenticli
```

```python
from typing import Annotated
from agenticli import CommandRegistry, Option, command, command_group


@command_group(name="calc", description="计算器命令")
class Calc:
    @command(name="add", description="求和")
    def add(
        self,
        values: Annotated[list[float], Option(positional=True, value_name="n")],
    ) -> dict:
        return {"result": sum(values)}


registry = CommandRegistry()
registry.register(Calc)

print(registry.render_llm_context())
# -> You can use the following CLI commands:
#     calc: 计算器命令

result = registry.execute("calc add 10 20 30")
print(result.value if result.ok else result.error.render())
# -> {"result": 60.0}
```

## 🏗️ 核心结构

```
┌─────────────────────────────────────────────────────────────┐
│                        LLM 输出                              │
│                    "calc add 10 20 30"                      │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                     CommandRegistry                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐  │
│  │  Parse   │─▶│ Validate │─▶│ Execute  │─▶│   Result   │  │
│  └──────────┘  └──────────┘  └──────────┘  └────────────┘  │
│                                                             │
│  • 命令命中/匹配           • 生命周期回调                   │
│  • 帮助生成                • 带建议的错误信息               │
│  • 参数注入                • 链式执行 (&&, ||, ;)          │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    你的函数 / 工具                           │
└─────────────────────────────────────────────────────────────┘
```

## 📋 核心能力

| 能力 | 说明 |
|------|------|
| 🔌 **多种注册方式** | 装饰器、类继承、dataclass、Pydantic、schema 包装 |
| ⚡ **CLI 解析** | 位置参数、带引号参数、`--option value`、`-o value`、`--opt=val`、flag |
| 📖 **帮助系统** | 自动生成 usage、help 文本和 LLM prompt |
| ✅ **参数校验** | 类型转换、`requires`/`excludes`、枚举校验 |
| 💡 **智能建议** | 未知命令、未知选项、枚举值拼写建议 |
| 🔄 **生命周期钩子** | `before_execute`、`after_execute`、`on_error` |
| 🏃 **内部注入** | 回调/状态对 CLI 隐藏，但可在运行时注入 |
| 🔗 **链式执行** | 支持引号感知的 `cmd1 && cmd2 || cmd3 ; cmd4` |
| ⏳ **异步执行** | 原生支持 `execute_async(..., chain=False)` |
| 🔌 **外部工具导入** | 可将 LangChain / AutoGen / OpenAI 风格工具包装成 `CommandSpec` |

## 📝 命令注册方式

### 1️⃣ 装饰器模式

```python
from typing import Annotated
from agenticli import command, Option


@command(name="ls", description="列出目录")
def ls(
    path: Annotated[str, Option(short="p", description="目录路径")],
    verbose: Annotated[bool, Option(short="v")] = False,
) -> list[str]:
    import os
    return os.listdir(path)
```

### 2️⃣ 命令组

```python
from agenticli import command_group, command


@command_group(name="db", description="数据库操作")
class Database:
    @command(description="创建数据库")
    def create(self, name: str) -> None: ...

    @command(description="删除数据库")
    def drop(self, name: str) -> None: ...
```

### 3️⃣ 包装现有工具

```python
from agenticli import wrap_tool


class MyTool:
    name = "my_tool"
    description = "做一些事情"
    parameters = {"type": "object", "properties": {"x": {"type": "int"}}}

    async def execute(self, **kwargs):
        return kwargs


registry.register_spec(wrap_tool(MyTool()))
```

### 4️⃣ 类继承模式

```python
from agenticli import CliCommand, CommandRegistry


class AddCommand(CliCommand):
    name = "add"
    description = "求和"
    args_model = AddArgs

    async def run(self, **kwargs) -> dict:
        return {"result": sum(kwargs["values"])}


registry.register(AddCommand())
```

## 🤖 与 LLM 集成

### 最小工具暴露

只向 LLM 暴露一个 `exec` 工具：

```python
from agenticli import ExecTool

def run_command(command: str, **kwargs):
    result = registry.execute(command)
    return result.value if result.ok else result.error.render()

exec_tool = ExecTool(callback=run_command)
```

### 生命周期回调

```python
from agenticli import ExecutionCallbacks


def on_error(ctx):
    print(f"Error: {ctx.error.code} - {ctx.error.message}")


registry = CommandRegistry(
    callbacks=ExecutionCallbacks(on_error=on_error)
)
```

### 内部参数注入

```python
from typing import Annotated
from agenticli import Callback, State, command


@command(name="process")
def process(
    data: list[str],
    cache: Annotated[object, State(factory=lambda ctx: load_cache())] = None,
):
    return cached_transform(data, cache)
```

## 🔌 导入外部工具

可以通过 `agenticli.adapters` 中的包装函数，把外部框架已有工具导入为
`agenticli` 命令：

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
        description="搜索文档",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        handler=lambda query: {"query": query},
    )
)
```

## ⚡ 异步 API

`agenticli` 现在支持原生异步执行：

```python
result = await registry.execute_async("calc add 1 2 3")
items = await registry.execute_async("cmd1 ; cmd2", chain=True)
```

## 🧾 命令语法

命令参数支持 shell 风格引号：

```bash
weather "New York" --unit fahrenheit
say 'single quoted text'
say "arg with \"nested\" quotes"
```

解析前会先处理反斜杠换行续行：

```bash
weather "New York" \
  --unit fahrenheit
```

命令链支持 `;`、`&&` 和 `||`。引号内的操作符会作为参数内容保留，
不会被当作链式分隔符：

```bash
say "hello ; world" ; say done
say "hello && world" && say ok
```

不正确的输入会返回结构化错误：

```python
result = registry.execute('weather "Beijing')
assert result.ok is False
assert result.error.code == "parse_error"

registry.execute("missing && weather Beijing", chain=True)
# ["Error: Unknown command"]
```

## 📖 自动生成的帮助内容

`<name> --help` 与 `registry.help(name)` 由每个命令的
`ValidationAdapter.help_text()` 渲染。假设：

```python
@command_group(name="files", description="文件与文本操作")
class Files:
    @command(name="ls", description="列出目录内容")
    def ls(
        self,
        path: Annotated[str, Option(short="p", description="目录路径", value_name="PATH", example="/tmp")],
        verbose: Annotated[bool, Option(short="v", description="同时列出隐藏条目")] = False,
        ext: Annotated[str, Option(short="e", description="按扩展名过滤", value_name="EXT", example=".log")] = "",
    ) -> list[str]: ...
```

`files ls --help` 渲染为：

```
files ls - 列出目录内容

Usage:
  ls --path <PATH> [--verbose] [--ext <EXT>]

Args:
  -p,--path PATH required example:/tmp, 目录路径
  -v,--verbose flag default:false, 同时列出隐藏条目
  -e,--ext EXT default: example:.log, 按扩展名过滤
```

命令组帮助只列出子命令。`registry.render_llm_context()` 输出的 LLM
prompt 刻意保持极简，**不会**嵌入完整帮助——它会提示模型在需要时
调用 `<command> --help`。

> **0.2.5**：自动生成的帮助改为扁平、每行一个参数的格式——
> `标题` / `Usage` / `Args`。每行参数上的修饰符用空格分隔
> （`flag`、`required`、`default:X`、`enum:[…]`、`example:X`），
> 末尾的 `, 描述`（带逗号）只在有描述时追加。

## 📦 稳定 API

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
CommandRegistry.discover(directory, *, context_provider=None, recursive=True, package=None, on_error="ignore")
CommandRegistry.match(text, chain=False, mode="command")
CommandRegistry.help(command=None)
CommandRegistry.render_llm_context(detailed=False)
CommandRegistry.commands

# Decorators
command(_func=None, *, name=None, description="", aliases=None, hidden=False, deprecated=None, include_in_prompt=None)
command_group(name="", description="", *, include_in_prompt=True, register_as_command=None)

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

从 0.1.x 升级请看 [docs/migration_0.2.md](docs/migration_0.2.md)。

## 💡 示例

完整的计算器与 OpenAI / Anthropic 集成示例见 [example/provider_integration.py](example/provider_integration.py)：

```bash
pip install "agenticli[examples]"
python -m example.provider_integration --provider openai
python -m example.provider_integration --provider anthropic
```

本地 Linux-like 命令示例（`pwd`、`cd`、`ls`、`cat`、`head`、`grep`、`wc`）见：

```bash
python -m example.linux_like_shell
```

各类使用方式的独立示例：

```bash
python -m example.decorator
python -m example.command_group
python -m example.cli_command
python -m example.command_from_model
python -m example.command_from_method
python -m example.wrap_tool
python -m example.external_adapters
python -m example.discover
```

## 🔎 自动发现

`CommandRegistry.discover()` 会扫描一个目录，自动注册所有通过
`@command_group` 标记、或继承 `CliCommand` 的类。可选的
`context_provider` 回调用来给每个发现的类绑定请求级上下文——同一
注册表复用于多租户场景时尤其方便：

```python
from agenticli import CommandRegistry

def provide_context(cls):
    if cls is UserService:
        return cls(user_id="alice", tenant_id="acme")
    return cls()

registry = CommandRegistry()
result = registry.discover(
    "example/discover_cmds",
    context_provider=provide_context,
    package="example.discover_cmds",
)
print(result.registered)   # 新注册的命令名
print(result.errors)       # 每个文件的失败（on_error="ignore" 时）
```

完整可运行示例见 [example/discover.py](example/discover.py)。

## 📚 文档

| 语言 | 链接 |
|------|------|
| 🇺🇸 English | [README.md](README.md) |
| 🇨🇳 中文 | [README_zh.md](README_zh.md) |
| 🇺🇸 English Docs | [docs/index_en.md](docs/index_en.md) |
| 🇨🇳 中文文档 | [docs/index_zh.md](docs/index_zh.md) |
| Migration | [docs/migration_0.2.md](docs/migration_0.2.md) |

## 📄 License

MIT
