"""Decorators for defining CLI commands.

This module provides decorators for registering functions and classes
as CLI commands, supporting both standalone commands and command groups
with subcommands.
"""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from llmcli.types import CommandSpec
from llmcli.validation import build_adapter


_COMMAND_REGISTRY: list[CommandSpec] = []


def command(
    name: str | None = None,
    description: str = "",
    aliases: list[str] | None = None,
    hidden: bool = False,
    deprecated: str | None = None,
):
    """Decorator to register a function as a CLI command.

    Wraps a function and registers it as a command in the global registry.
    The command's arguments are inferred from the function signature.

    Args:
        name: Command name, defaults to function name.
        description: Command description for help text.
        aliases: List of alternative names for the command.
        hidden: Whether to hide from command list.
        deprecated: Deprecation message if command is deprecated.

    Returns:
        Decorator function that wraps and registers the target.

    Example:
        @command(description="List files")
        def ls(path: Annotated[str, Option(description="Directory path")]) -> list[str]:
            return os.listdir(path)
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        cmd_name = name or func.__name__
        adapter = build_adapter(func)
        spec = CommandSpec(
            name=cmd_name,
            description=description or (func.__doc__ or "").strip(),
            func=func,
            args=adapter.args,
            usage=adapter.usage(cmd_name),
            aliases=aliases or [],
            validator=adapter,
            source="function",
            help_text=adapter.help_text(cmd_name, description or (func.__doc__ or "")),
            hidden=hidden,
            deprecated=deprecated,
            injections=dict(adapter.injections),
            injection_factories=dict(adapter.injection_factories),
        )
        _COMMAND_REGISTRY.append(spec)

        @wraps(func)
        def wrapper(*args_inner: Any, **kwargs: Any) -> Any:
            return func(*args_inner, **kwargs)

        wrapper.__command_spec__ = spec
        return wrapper

    return decorator


def command_group(name: str, description: str = ""):
    """Decorator for a class that contains subcommands.

    Marks a class as a command group, where public methods decorated with
    @command become subcommands of the group. The group itself is registered
    as a parent command.

    Args:
        name: Group name, used as the parent command name.
        description: Group description for help text.

    Returns:
        Decorator function that marks and configures the class.

    Example:
        @command_group("db", description="Database operations")
        class DatabaseCommands:
            @command(description="Create a new database")
            def create(self, name: str) -> None:
                ...

            @command(description="Drop a database")
            def drop(self, name: str) -> None:
                ...
    """

    def decorator(cls: type) -> type:
        for attr_name in dir(cls):
            if attr_name.startswith("_"):
                continue
            attr = getattr(cls, attr_name)
            if callable(attr) and hasattr(attr, "__command_spec__"):
                spec: CommandSpec = attr.__command_spec__
                spec.parent = name
                if spec in _COMMAND_REGISTRY:
                    _COMMAND_REGISTRY.remove(spec)

        cls.__command_group__ = {"name": name, "description": description}
        return cls

    return decorator


def get_registered_commands() -> list[CommandSpec]:
    """Get all registered command specs.

    Returns:
        List of all CommandSpec objects currently in the registry.

    Note:
        This returns a copy, modifications won't affect the internal registry.
    """
    return list(_COMMAND_REGISTRY)


def clear_commands() -> None:
    """Clear all registered commands.

    Useful for testing to reset state between test cases.
    """
    _COMMAND_REGISTRY.clear()