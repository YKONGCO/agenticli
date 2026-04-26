<div align="center">

# ⚡ agenticli

**把工具暴露为适合 LLM agent 使用的轻量 CLI 命令层** 🔧✨

[English](README.md) | [中文](README_zh.md)

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![PyPI](https://img.shields.io/badge/pypi-agenticli-blue.svg)](https://pypi.org/project/agenticli/)

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

print(registry.get_llm_prompt())
# -> You can use the following CLI commands:
#     calc: 计算器命令

registry.parse_and_execute("calc add 10 20 30")
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
| ⚡ **CLI 解析** | 位置参数、`--option value`、`-o value`、`--opt=val`、flag |
| 📖 **帮助系统** | 自动生成 usage、help 文本和 LLM prompt |
| ✅ **参数校验** | 类型转换、`requires`/`excludes`、枚举校验 |
| 💡 **智能建议** | 未知命令、未知选项、枚举值拼写建议 |
| 🔄 **生命周期钩子** | `before_execute`、`after_execute`、`on_error` |
| 🏃 **内部注入** | 回调/状态对 CLI 隐藏，但可在运行时注入 |
| 🔗 **链式执行** | `cmd1 && cmd2 || cmd3 ; cmd4` |

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

exec_tool = ExecTool(callback=registry.parse_and_execute)
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

## 📦 稳定 API

```python
# Core
CommandRegistry
CommandRegistry.register(target)
CommandRegistry.register_spec(spec)
CommandRegistry.execute(command_str)
CommandRegistry.parse_and_execute(command_str)
CommandRegistry.render_help(command)
CommandRegistry.get_llm_prompt(detailed=False)

# Decorators
command(name=None, description="", aliases=None, hidden=False, deprecated=None)
command_group(name, description)

# Helpers
CliCommand
wrap_tool(tool)
command_from_model(name, model, handler)
command_from_method(name, target, method_name)
Option
Injected / Callback / State
ExecutionCallbacks
ExecTool
```

## 💡 示例

完整的计算器与 OpenAI / Anthropic 集成示例见 [example/demo.py](example/demo.py)：

```bash
pip install "agenticli[examples]"
python -m example.demo --provider openai
python -m example.demo --provider anthropic
```

## 📚 文档

| 语言 | 链接 |
|------|------|
| 🇺🇸 English | [README.md](README.md) |
| 🇨🇳 中文 | [README_zh.md](README_zh.md) |
| 🇺🇸 English Docs | [docs/index_en.md](docs/index_en.md) |
| 🇨🇳 中文文档 | [docs/index_zh.md](docs/index_zh.md) |

## 📄 License

MIT
