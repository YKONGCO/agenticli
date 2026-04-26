# agenticli 文档

欢迎使用 agenticli 文档。本页提供 agenticli 包的概述。

## 目录

- [快速开始](#快速开始)
- [核心概念](#核心概念)
- [命令定义](#命令定义)
- [API 参考](#api-参考)

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

print(registry.get_llm_prompt())
print(registry.parse_and_execute("calc add 10 20 30"))
```

---

## 核心概念

### CommandRegistry

`CommandRegistry` 是 agenticli 的核心组件。它管理命令的注册、解析、执行和帮助生成。

主要职责：
- 注册命令和命令组
- 命令命中检测和匹配
- 解析位置参数、长参数、短参数、布尔 flag 和紧凑参数形式
- 自动生成 usage/help/LLM prompt
- 参数验证和默认值填充
- 执行函数、类命令和包装后的 tool
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
| `unregister(name)` | 移除命令 |
| `get(name)` | 按名称获取 CommandSpec |
| `has(name)` | 检查命令是否存在 |
| `parse(command_str)` | 解析但不执行 |
| `parse_and_execute(command_str)` | 解析并执行，返回值或错误 |
| `execute(command_str)` | 执行并返回 ExecutionResult |
| `render_help(command)` | 获取帮助文本 |
| `get_llm_prompt(detailed)` | 生成 LLM 上下文字符串 |

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

将函数注册为 CLI 命令。

```python
@command(
    name=None,           # 命令名，默认为函数名
    description="",     # 命令描述
    aliases=None,       # 别名列表
    hidden=False,       # 从命令列表中隐藏
    deprecated=None,    # 弃用消息
)
def my_command(arg1: str, arg2: int = 10) -> str:
    pass
```

#### @command_group

将类标记为命令组。

```python
@command_group(name="group", description="组描述")
class MyGroup:
    @command(description="子命令")
    def sub(self, arg: str) -> None:
        pass
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

通过回调执行命令。

```python
from agenticli import ExecTool, CommandRegistry

def execute_callback(command: str, **kwargs):
    return subprocess.run(command, shell=True, timeout=kwargs.get("timeout", 60))

exec_tool = ExecTool(callback=execute_callback)
result = exec_tool.execute(command="ls -la")
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
registry.chain_execute("cmd1 ; cmd2")

# AND：任何一个失败则停止
registry.chain_execute("cmd1 && cmd2")

# OR：任何一个成功则停止
registry.chain_execute("cmd1 || cmd2")
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
