"""Tool adapters and inheritance-based command APIs.

This module provides alternative ways to define CLI commands beyond decorators,
including class inheritance and wrapping existing tools.
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import is_dataclass
from typing import Any

from agenticli.types import CommandSpec
from agenticli.validation import build_adapter

try:
    from pydantic import BaseModel
except Exception:  # pragma: no cover - optional dependency
    BaseModel = None  # type: ignore[assignment]


class CliCommand:
    """Inheritance-based command definition.

    Subclass this to define a command using class attributes and the run()
    method. Automatically generates CommandSpec from class metadata and
    the args_model type annotation.

    Attributes:
        name: Command name, defaults to lowercase class name without 'Command' suffix.
        description: Command description for help text.
        aliases: List of alternative command names.
        args_model: Type (dataclass or Pydantic model) defining command arguments.
        hidden: Whether to hide from command list.
        deprecated: Deprecation message if command is deprecated.

    Example:
        class ListFilesCommand(CliCommand):
            name = "ls"
            description = "List files in a directory"
            args_model = ListFilesArgs

            async def run(self, path: str, verbose: bool = False) -> list[str]:
                files = os.listdir(path)
                if verbose:
                    for f in files:
                        print(f)
                    return []
                return files
    """

    name: str = ""
    description: str = ""
    aliases: list[str] = []
    args_model: type | None = None
    hidden: bool = False
    deprecated: str | None = None

    async def run(self, **kwargs: Any) -> Any:
        """Execute the command with given arguments.

        Override this method in subclasses to implement command logic.

        Args:
            **kwargs: Command arguments as defined by args_model.

        Returns:
            Command execution result.

        Raises:
            NotImplementedError: If not overridden in subclass.
        """
        raise NotImplementedError

    def to_command_spec(self) -> CommandSpec:
        """Convert class to CommandSpec for registration.

        Uses args_model to infer argument specifications and generates
        help text automatically.

        Returns:
            CommandSpec ready for registration in CommandRegistry.
        """
        adapter = build_adapter(self.args_model)

        async def invoke(**kwargs: Any) -> Any:
            return await self.run(**kwargs)

        name = self.name or self.__class__.__name__.replace("Command", "").lower()
        return CommandSpec(
            name=name,
            description=self.description or (self.__class__.__doc__ or "").strip(),
            func=invoke,
            args=adapter.args,
            usage=adapter.usage(name),
            aliases=list(self.aliases),
            validator=adapter,
            source="class",
            help_text=adapter.help_text(name, self.description or ""),
            hidden=self.hidden,
            deprecated=self.deprecated,
            injections=dict(adapter.injections),
            injection_factories=dict(adapter.injection_factories),
        )


def wrap_tool(
    tool: Any,
    *,
    name: str | None = None,
    description: str | None = None,
    aliases: list[str] | None = None,
    hidden: bool = False,
    deprecated: str | None = None,
) -> CommandSpec:
    """Wrap a schema-based tool object as an agenticli command.

    Converts an object with execute() method and parameters schema into
    a CommandSpec that can be registered in CommandRegistry.

    Args:
        tool: Object with execute() method and optional parameters schema.
        name: Override command name.
        description: Override command description.
        aliases: List of alternative names.
        hidden: Whether to hide from command list.
        deprecated: Deprecation message.

    Returns:
        CommandSpec wrapping the tool.

    Raises:
        TypeError: If tool does not have execute() method.
    """
    if not hasattr(tool, "execute"):
        raise TypeError("Wrapped tool must expose an execute method")

    schema = getattr(tool, "parameters", None)
    if callable(schema):
        schema = schema()
    adapter = build_adapter(schema=schema)
    cmd_name = name or getattr(tool, "name", tool.__class__.__name__.lower())
    cmd_description = description or getattr(tool, "description", "") or ""

    async def invoke(**kwargs: Any) -> Any:
        result = tool.execute(**kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    return CommandSpec(
        name=cmd_name,
        description=cmd_description,
        func=invoke,
        args=adapter.args,
        usage=adapter.usage(cmd_name),
        aliases=list(aliases or []),
        validator=adapter,
        source="wrapped-tool",
        help_text=adapter.help_text(cmd_name, cmd_description),
        hidden=hidden,
        deprecated=deprecated,
        injections=dict(adapter.injections),
        injection_factories=dict(adapter.injection_factories),
    )


def command_from_model(
    name: str,
    model: type,
    handler: Any,
    *,
    description: str = "",
    aliases: list[str] | None = None,
    hidden: bool = False,
    deprecated: str | None = None,
) -> CommandSpec:
    """Build a command from a dataclass or Pydantic model plus a handler.

    Creates a CommandSpec where the model defines argument structure and
    the handler function implements the logic.

    Args:
        name: Command name.
        model: Dataclass or Pydantic BaseModel type defining arguments.
        handler: Function to call with parsed arguments.
        description: Command description.
        aliases: List of alternative names.
        hidden: Whether to hide from command list.
        deprecated: Deprecation message.

    Returns:
        CommandSpec ready for registration.

    Raises:
        TypeError: If model is not a dataclass or Pydantic model.
    """
    if not (is_dataclass(model) or (BaseModel and inspect.isclass(model) and issubclass(model, BaseModel))):
        raise TypeError("model must be a dataclass or Pydantic BaseModel")

    adapter = build_adapter(model)

    async def invoke(**kwargs: Any) -> Any:
        result = handler(**kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    return CommandSpec(
        name=name,
        description=description or (handler.__doc__ or "").strip(),
        func=invoke,
        args=adapter.args,
        usage=adapter.usage(name),
        aliases=list(aliases or []),
        validator=adapter,
        source="model",
        help_text=adapter.help_text(name, description or ""),
        hidden=hidden,
        deprecated=deprecated,
        injections=dict(adapter.injections),
        injection_factories=dict(adapter.injection_factories),
    )


def command_from_method(
    name: str,
    target: Any,
    method_name: str = "run",
    *,
    description: str = "",
    aliases: list[str] | None = None,
    hidden: bool = False,
    deprecated: str | None = None,
) -> CommandSpec:
    """Build a command from a single method on a class or instance.

    Creates a CommandSpec using a specific method's signature for argument
    parsing and the method itself for execution.

    Args:
        name: Command name.
        target: Class or instance containing the method.
        method_name: Name of the method to use (default "run").
        description: Command description.
        aliases: List of alternative names.
        hidden: Whether to hide from command list.
        deprecated: Deprecation message.

    Returns:
        CommandSpec ready for registration.

    Raises:
        AttributeError: If target doesn't have the specified method.
        TypeError: If method is not callable.
    """
    if inspect.isclass(target):
        instance = target()
    else:
        instance = target

    if not hasattr(instance, method_name):
        raise AttributeError(f"{instance!r} has no method '{method_name}'")

    method = getattr(instance, method_name)
    if not callable(method):
        raise TypeError(f"{method_name!r} is not callable")

    adapter = build_adapter(method)

    async def invoke(**kwargs: Any) -> Any:
        result = method(**kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    return CommandSpec(
        name=name,
        description=description or (method.__doc__ or "").strip(),
        func=invoke,
        args=adapter.args,
        usage=adapter.usage(name),
        aliases=list(aliases or []),
        validator=adapter,
        source="method",
        help_text=adapter.help_text(name, description or ""),
        hidden=hidden,
        deprecated=deprecated,
        injections=dict(adapter.injections),
        injection_factories=dict(adapter.injection_factories),
    )


def run_sync(awaitable: Any) -> Any:
    """Run an awaitable in synchronous contexts.

    If the value is already not awaitable, returns it unchanged.
    Otherwise creates a new event loop and runs the awaitable to completion.

    Args:
        awaitable: Any value, possibly an awaitable (coroutine, task, future).

    Returns:
        The resolved value if awaitable, otherwise the original value.

    Note:
        This function creates a new event loop each call, which has overhead.
        For repeated synchronous calls, consider running an explicit event loop.
    """
    if not inspect.isawaitable(awaitable):
        return awaitable
    return asyncio.run(awaitable)
