"""agenticli - expose tools as lightweight CLI commands for LLMs.

This package provides a framework for defining CLI commands that can be
parsed and executed by LLMs. It supports multiple command definition styles
including decorators, class inheritance, and schema-based wrapping.

Typical usage:
    from agenticli import CommandRegistry, command

    registry = CommandRegistry()

    @command(description="List directory contents")
    def ls(path: Annotated[str, Option(description="Directory path")]) -> list[str]:
        import os
        return os.listdir(path)

    registry.register(ls)
    result = registry.execute("ls /tmp")

Exports:
    ArgSpec: Argument specification data class.
    CliCommand: Base class for inheritance-based commands.
    CommandError: Structured error with code, message, and hints.
    CommandRegistry: Central registry for command management.
    CommandSpec: Command specification data class.
    ExecutionCallbacks: Lifecycle callbacks for command execution.
    ExecutionContext: Context passed to lifecycle callbacks.
    ExecutionResult: Structured execution result with ok/value/error.
    ExecTool: Built-in callback bridge for command strings.
    HitResult: Command matching/detection result.
    Injected: Marker for injected (internal) parameters.
    ParseResult: Parsed command result with arguments.
    Callback: Alias for Injected for callback injection.
    State: Alias for Injected for state injection.
    command: Decorator to register a function as a command.
    command_from_method: Create command from a class method.
    command_from_model: Create command from model + handler.
    command_group: Decorator for command groups with subcommands.
    Option: Per-argument CLI metadata annotation.
    wrap_tool: Wrap a schema-based tool as a command.
"""

from agenticli.builtin import ExecTool
from agenticli.adapters import wrap_autogen_tool, wrap_langchain_tool, wrap_openai_tool_schema, wrap_tool
from agenticli.commands import CliCommand, command_from_method, command_from_model
from agenticli.core import CommandRegistry
from agenticli.decorators import command, command_group
from agenticli.types import ArgSpec, CommandError, CommandSpec, ExecutionCallbacks, ExecutionContext, ExecutionResult, HitResult, ParseResult
from agenticli.validation import Callback, Injected, Option, State

__all__ = [
    "ArgSpec",
    "CliCommand",
    "CommandError",
    "CommandRegistry",
    "CommandSpec",
    "ExecutionCallbacks",
    "ExecutionContext",
    "ExecutionResult",
    "ExecTool",
    "HitResult",
    "Injected",
    "ParseResult",
    "Callback",
    "State",
    "command",
    "command_from_method",
    "command_from_model",
    "command_group",
    "Option",
    "wrap_autogen_tool",
    "wrap_langchain_tool",
    "wrap_openai_tool_schema",
    "wrap_tool",
]
