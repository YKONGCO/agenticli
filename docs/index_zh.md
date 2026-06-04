# agenticli 文档

欢迎使用 agenticli 文档。本页提供 agenticli 包的概述。

## 目录

- [快速开始](#快速开始)
- [核心概念](#核心概念)
- [命令定义](#命令定义)
- [API 参考](#api-参考)
- [0.2.x 迁移指南](migration_0.2.md)

---

## 快速开始

### 安装

```bash
pip install agenticli
```

如需 Pydantic v2 支持：

```bash
pip install "agenticli[pydantic]"
```

### 最小示例

```python
from typing import Annotated

from agenticli import CommandRegistry, Option, command, command_group


@command_group(name="calc", description="结构化计算器命令")
class Calc:
    @command(name="add", description="将一串数字相加")
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

## 核心概念

### CommandRegistry

`CommandRegistry` 是 agenticli 的核心组件。它管理命令的注册、解析、执行和帮助生成。

主要职责：
- 注册命令和命令组
- 命令命中检测和匹配
- 解析位置参数、带引号参数、长参数、短参数、布尔 flag 和紧凑参数形式
- 自动生成 usage/help/LLM prompt
- 参数验证和默认值填充
- 执行函数、类命令和包装后的 tool
- 支持原生异步执行 API
- 支持反斜杠换行续行和引号感知的命令链拆分
- 统一错误包装和建议提示
- 支持内部注入参数和执行生命周期回调

### 命令生命周期

```
command string -> parse -> validate -> execute -> result
                   |
                   v
              error handling with suggestions
```

---

## 命令定义

### 装饰器模式

使用 `@command` 将函数注册为 CLI 命令：

```python
from typing import Annotated

from agenticli import command, Option

@command(name="ls", description="列出目录内容")
def list_dir(
    path: Annotated[str, Option(description="目录路径")],
    verbose: Annotated[bool, Option(short='v')] = False,
) -> list[str]:
    import os
    files = os.listdir(path)
    if verbose:
        for f in files:
            print(f)
    return files
```

### 命令组

使用 `@command_group` 创建带有子命令的组：

```python
from agenticli import command_group, command

@command_group(name="db", description="数据库操作")
class Database:
    @command(description="创建数据库")
    def create(self, name: str) -> None:
        print(f"正在创建 {name}")

    @command(description="删除数据库")
    def drop(self, name: str) -> None:
        print(f"正在删除 {name}")
```

### 类继承模式

继承 `CliCommand` 来定义类-based 命令：

```python
from dataclasses import dataclass
from agenticli import CliCommand, CommandRegistry

@dataclass
class AddArgs:
    values: list[float]

class AddCommand(CliCommand):
    name = "add"
    description = "将数字相加"
    args_model = AddArgs

    async def run(self, **kwargs) -> dict:
        return {"result": sum(kwargs["values"])}

registry = CommandRegistry()
registry.register(AddCommand())
```

### 包装现有工具

使用 `wrap_tool()` 转换基于 schema 的工具：

```python
from agenticli import CommandRegistry, wrap_tool

class MyTool:
    name = "my_tool"
    description = "我的工具描述"
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

### 导入外部框架工具

如果你已经有 LangChain、AutoGen 或 OpenAI 风格的工具定义，可以通过
`agenticli.adapters` 里的包装函数把它们转成 `CommandSpec`：

```python
from agenticli.adapters import (
    wrap_autogen_tool,
    wrap_langchain_tool,
    wrap_openai_tool_schema,
)
```

### 自动发现

`CommandRegistry.discover()` 会扫描一个目录，自动注册所有通过
`@command_group` 标记、或继承 `CliCommand` 的类。可选的
`context_provider` 回调是给每个发现的类绑定请求级上下文（user id、
tenant、db 连接等）的天然接缝。

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
# result.registered -> 新注册的命令名
# result.errors     -> 每个文件的失败（on_error="ignore" 时被收集）
```

识别两种标记：带有 `__command_group__` 的类（由 `@command_group`
设置）和 `CliCommand` 的子类。文件名以 `_` 或 `.` 开头（包括
`__init__.py` 和 dotfile）、以及 `__pycache__` 目录下的文件都会跳过。
完整可运行示例见 [example/discover.py](../example/discover.py)。

### 命名空间模式的命令组

将 `register_as_command=False` 可以让 `@command_group` 类纯粹作为命名
空间：类本身**不会**作为父命令注册，方法会变成顶层扁平命令，且
`spec.parent=None`。

```python
@command_group(include_in_prompt=False)  # 省略 name → 命名空间模式
class ShellCommands:
    @command
    def ls(self, path: str = ".") -> list[str]: ...
    # 注册为顶层命令 "ls"
```

`register_as_command` 的默认值由 `name` 推断：`name` 非空时为
`True`，空时为 `False`。当命名空间组设为隐藏
（`include_in_prompt=False`）时，这个 `False` 会传播到所有未显式
设置 `include_in_prompt` 的子命令；子命令上的显式值始终优先。

> **有状态类**：如果方法依赖需要跨调用保留的 `self` 状态，请注册
> **实例**而不是类。注册类时每次执行都会构造一个新实例，导致有状态
> 的改动丢失。

---

## 命令语法

### 带引号参数

参数使用 shell 风格引号拆分：

```bash
weather "New York" --unit fahrenheit
say 'single quoted text'
say "arg with \"nested\" quotes"
```

引号内的空格会保留在同一个参数中。

### 反斜杠续行

反斜杠后紧跟 LF 或 CRLF 时，会在解析前被规范化为空格：

```bash
weather "New York" \
  --unit fahrenheit
```

等价于：

```bash
weather "New York" --unit fahrenheit
```

### 命令链操作符与引号

`execute(..., chain=True)` 和 `execute_async(..., chain=True)` 支持 `;`、`&&` 和 `||`。
命令链拆分会尊重引号，因此引号内的操作符不会拆分命令：

```bash
registry.execute('say "hello ; world" ; say done', chain=True)
registry.execute('say "hello && world" && say ok', chain=True)
```

单个管道符 `|`、重定向、glob 展开、变量展开和命令替换不会由
agenticli 进行 shell 展开。

---

## 错误处理

不正确的命令输入会返回结构化错误，而不是抛出解析异常：

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

对于命令组，未知子命令会按未知命令处理：

```python
registry.execute("calc missing 1 2")
```

---

## API 参考

### 核心类

#### CommandRegistry

CLI 命令的中央注册表。

```python
registry = CommandRegistry(
    strict=True,              # 启用严格解析
    allow_prefix_match=True,  # 允许前缀匹配
    callbacks=None            # 生命周期的 ExecutionCallbacks
)
```

**方法：**

| 方法 | 描述 |
|--------|-------------|
| `register(target)` | 从函数、类或工具注册命令 |
| `register_spec(spec)` | 直接注册 CommandSpec |
| `discover(directory, *, context_provider=None, recursive=True, package=None, on_error="ignore")` | 从目录自动发现并注册命令类 |
| `unregister(name)` | 移除命令 |
| `get(name)` | 按名称获取 CommandSpec |
| `has(name)` | 检查命令是否存在 |
| `parse(command_str, chain=False)` | 解析但不执行；`chain=True` 时解析命令链 |
| `execute(command_str, chain=False)` | 执行并返回 `ExecutionResult`；`chain=True` 时返回值/错误列表 |
| `execute_async(command_str, chain=False)` | 异步执行，链式行为同上 |
| `match(text, chain=False, mode="command")` | 匹配命令文本、命令链，或用 `mode="natural"` 匹配自然语言 |
| `help(command=None)` | 获取帮助文本 |
| `render_llm_context(detailed=False)` | 生成 LLM 命令上下文字符串 |
| `commands` | 列出可见的已注册命令名 |

#### CliCommand

用于类继承模式的基类。

```python
class MyCommand(CliCommand):
    name = "my_cmd"
    description = "我的命令"
    args_model = MyArgsModel

    async def run(self, **kwargs) -> Any:
        # 实现
        pass
```

### 装饰器

#### @command

将函数注册为 CLI 命令。支持裸用（`@command`）或带参数（`@command(...)`）两种形式；当所有参数都使用默认值时括号可省略。

```python
@command(
    name=None,           # 命令名，默认为函数名
    description="",     # 命令描述
    aliases=None,       # 别名列表
    hidden=False,       # 从命令列表中隐藏
    deprecated=None,    # 弃用消息
    include_in_prompt=None,  # None → 继承 @command_group 命名空间；True/False → 显式
)
def my_command(arg1: str, arg2: int = 10) -> str:
    pass
```

裸用等价于 `@command()` 全默认：

```python
@command
def my_command(arg1: str, arg2: int = 10) -> str:
    pass
```

#### @command_group

将类标记为命令组。默认情况下组本身也会注册为父命令（例如 `db
create`）。将 `register_as_command=False` 可以让类纯粹作为命名空间
（见[命名空间模式的命令组](#命名空间模式的命令组)）。

```python
@command_group(name="group", description="组描述")
class MyGroup:
    @command(description="子命令")
    def sub(self, arg: str) -> None:
        pass

# 命名空间模式：方法注册为顶层扁平命令
@command_group(include_in_prompt=False)
class ShellCommands:
    @command
    def ls(self, path: str = ".") -> list[str]: ...
```

### 验证辅助

#### Option

类型注解的每个参数的 CLI 元数据。

```python
from typing import Annotated
from agenticli import Option

def cmd(
    file: Annotated[str, Option(
        short='f',           # 短标志
        description='输入文件',
        positional=True,      # 是否为位置参数
        value_name='FILE',    # 用法中的占位符
        example='data.txt',   # 示例值
        order=1,              # 排序顺序
        position=0,           # 位置索引
        hidden=False,         # 从帮助中隐藏
        repeatable=False,     # 可重复
        nargs=None,           # 值数量
        requires=(),         # 必需的其他参数
        excludes=(),          # 互斥的其他参数
    )]
) -> None:
    pass
```

#### Injected / Callback / State

将参数标记为内部注入。

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

### 内置工具

#### ExecTool

提供由回调驱动的 `exec` 风格 schema 工具。`ExecTool` 本身不会执行
shell；回调函数决定命令字符串的具体含义。

```python
from agenticli import ExecTool

async def execute_callback(command: str, **kwargs):
    return {"command": command, "timeout": kwargs.get("timeout", 60)}

exec_tool = ExecTool(callback=execute_callback)
result = await exec_tool.execute(command="search docs", timeout=30)
```

---

## 错误处理

### CommandError

带代码、消息、提示和建议的结构化错误。

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

用于日志记录、监控和审计的生命周期回调。

```python
def before(ctx):
    print(f"正在执行: {ctx.command}")

def after(ctx):
    print(f"结果: {ctx.result}")

def on_error(ctx):
    print(f"错误: {ctx.error.code}")

registry = CommandRegistry(
    callbacks=ExecutionCallbacks(
        before_execute=before,
        after_execute=after,
        on_error=on_error,
    )
)
```

---

## 链式执行

使用操作符执行多个命令：

```python
# 顺序：执行所有
registry.execute("cmd1 ; cmd2", chain=True)

# AND：任何一个失败则停止
registry.execute("cmd1 && cmd2", chain=True)

# OR：任何一个成功则停止
registry.execute("cmd1 || cmd2", chain=True)

# 引号内的操作符会作为参数文本处理
registry.execute('cmd1 "literal && text" ; cmd2', chain=True)
```

---

## 帮助语法

推荐形式：
```bash
calc --help
calc add --help
```

兼容形式：
```bash
--help
--help calc
```
