"""Decorators for defining CLI commands.

This module provides decorators for registering functions and classes
as CLI commands, supporting both standalone commands and command groups
with subcommands.

Decorators attach metadata to the wrapped target; they do not maintain
any global registry. Pass decorated functions/classes to
``CommandRegistry.register()`` to make them executable.
"""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from agenticli.types import CommandSpec
from agenticli.validation import build_adapter


def command(
    _func: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    description: str = "",
    aliases: list[str] | None = None,
    hidden: bool = False,
    deprecated: str | None = None,
    include_in_prompt: bool = True,
):
    """Decorator to register a function as a CLI command.

    Wraps a function and attaches a ``CommandSpec`` as
    ``wrapper.__command_spec__``. The wrapped function is not added to
    any global state — pass it to ``CommandRegistry.register()`` to make
    it executable.

    The command's arguments are inferred from the function signature.

    Usable bare (``@command``) or with arguments (``@command(...)``).
    The parentheses are not required when all defaults are acceptable.

    Args:
        _func: Internal — the decorated function when used as ``@command``.
            Ignored when ``@command(...)`` is used.
        name: Command name, defaults to function name.
        description: Command description for help text.
        aliases: List of alternative names for the command.
        hidden: Whether to hide from command list.
        deprecated: Deprecation message if command is deprecated.
        include_in_prompt: Whether to expose this command to the LLM via
            ``render_llm_context()``. Defaults to True. Set False to keep
            the command available to CLI users but invisible to the LLM
            (e.g., admin-only or interactive commands).

    Returns:
        The wrapped function, or a decorator awaiting the function,
        depending on the call style.

    Example:
        @command
        def ls(path: Annotated[str, Option(description="Directory path")]) -> list[str]:
            return os.listdir(path)

        @command(description="Get the weather for a city", aliases=["wx"])
        def weather(city: Annotated[str, Option(positional=True)]) -> str:
            ...
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
            include_in_prompt=include_in_prompt,
            injections=dict(adapter.injections),
            injection_factories=dict(adapter.injection_factories),
        )

        @wraps(func)
        def wrapper(*args_inner: Any, **kwargs: Any) -> Any:
            return func(*args_inner, **kwargs)

        wrapper.__command_spec__ = spec
        return wrapper

    if _func is not None:
        return decorator(_func)
    return decorator


def command_group(name: str, description: str = "", *, include_in_prompt: bool = True):
    """Decorator for a class that contains subcommands.

    Marks a class as a command group, where public methods decorated with
    @command become subcommands of the group. The group itself is registered
    as a parent command.

    Args:
        name: Group name, used as the parent command name.
        description: Group description for help text.
        include_in_prompt: Whether to expose this group to the LLM via
            ``render_llm_context()``. Defaults to True. Set False to keep
            the group available to CLI users but invisible to the LLM
            (e.g., admin-only operations). Subcommands retain their own
            setting and are not affected by the group's flag.

    Returns:
        Decorator function that marks the class with ``__command_group__``.

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
        cls.__command_group__ = {
            "name": name,
            "description": description,
            "include_in_prompt": include_in_prompt,
        }
        return cls

    return decorator
