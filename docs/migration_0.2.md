# Migration Guide: 0.1.x to 0.2.0

agenticli 0.2.0 simplifies `CommandRegistry` by replacing several specialized
methods with parameterized core methods.

## CommandRegistry API Changes

| 0.1.x | 0.2.0 |
|---|---|
| `parse_and_execute(command)` | `execute(command)` and read `result.value` or `result.error` |
| `parse_and_execute_async(command)` | `execute_async(command)` and read `result.value` or `result.error` |
| `chain_execute(command)` | `execute(command, chain=True)` |
| `chain_execute_async(command)` | `execute_async(command, chain=True)` |
| `chain_hit(command)` | `match(command, chain=True)` |
| `chain_has(command)` | `all(hit.command for hit in registry.match(command, chain=True))` |
| `render_help(command)` | `help(command)` |
| `detect(text)` | `match(text, mode="natural")` |
| `match_command(text)` | `match(text)` |
| `is_command(text)` | `registry.match(text).confidence > 0` |
| `get_llm_prompt(detailed=True)` | `render_llm_context(detailed=True)` |

## Execution Results

`execute()` now remains the single sync execution entry point. It returns an
`ExecutionResult` for a single command:

```python
result = registry.execute("weather Beijing")
if result.ok:
    print(result.value)
else:
    print(result.error.render())
```

For command chains, pass `chain=True`. Chain execution returns a list of command
values or rendered error strings:

```python
items = registry.execute("cmd1 ; cmd2", chain=True)
```

Async code uses the same shape:

```python
result = await registry.execute_async("weather Beijing")
items = await registry.execute_async("cmd1 ; cmd2", chain=True)
```

## Matching

Command matching is now consolidated under `match()`:

```python
registry.match("weather Beijing")
registry.match("weather Beijing ; missing", chain=True)
registry.match("please run weather for beijing", mode="natural")
```

## Module Moves

The old `agenticli.tooling` compatibility module was removed.

Use these imports instead:

```python
from agenticli.commands import CliCommand, command_from_method, command_from_model
from agenticli.adapters import wrap_tool, wrap_langchain_tool, wrap_autogen_tool, wrap_openai_tool_schema
```

Top-level imports from `agenticli` still work for the common helpers:

```python
from agenticli import CliCommand, CommandRegistry, command, wrap_tool
```

## ExecTool Callback

If you previously passed `registry.parse_and_execute` to `ExecTool`, replace it
with a small callback:

```python
def run_command(command: str, **kwargs):
    result = registry.execute(command)
    return result.value if result.ok else result.error.render()

exec_tool = ExecTool(callback=run_command)
```
