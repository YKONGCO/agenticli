"""Command definition helpers for agenticli-native commands."""

from __future__ import annotations

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
    """Inheritance-based command definition."""

    name: str = ""
    description: str = ""
    aliases: list[str] = []
    args_model: type | None = None
    hidden: bool = False
    deprecated: str | None = None
    include_in_prompt: bool = True

    async def run(self, **kwargs: Any) -> Any:
        """Execute the command with parsed arguments."""
        raise NotImplementedError

    def to_command_spec(self) -> CommandSpec:
        """Convert this command object to a CommandSpec."""
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
            include_in_prompt=self.include_in_prompt,
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
    include_in_prompt: bool = True,
) -> CommandSpec:
    """Expose a dataclass or Pydantic model plus a handler as a command.

    This helper is useful when your tool input is already described by a typed
    model and you want to keep that model as the single source of truth for the
    command arguments. agenticli inspects the model fields to build CLI parsing,
    validation, help text, and JSON Schema. After validation, the parsed values
    are passed to ``handler`` as keyword arguments.

    Supported models:
        - ``@dataclass`` classes from the Python standard library.
        - Pydantic ``BaseModel`` subclasses when Pydantic is installed.

    Field behavior:
        - Required model fields become required command arguments.
        - Fields with defaults become optional command arguments.
        - ``Annotated[..., Option(...)]`` can customize CLI metadata such as
          short flags, positional arguments, value names, examples, visibility,
          repeatability, and dependency constraints.
        - Basic Python types, lists, tuples, dictionaries, booleans, and
          ``Literal`` values are coerced and validated before the handler runs.

    The ``handler`` may be sync or async. It should accept keyword arguments
    matching the model field names. Its return value becomes the command result.

    Args:
        name: Command name used by ``CommandRegistry.execute()``, such as
            ``"multiply"`` or ``"user create"``.
        model: Dataclass or Pydantic model class used to define command input.
        handler: Function or callable invoked as ``handler(**validated_args)``.
        description: Help text and LLM context summary. If omitted, the handler
            docstring is used.
        aliases: Alternative command names that invoke the same handler.
        hidden: Hide the command from command listings while keeping it callable.
        deprecated: Optional deprecation message shown in help output.
        include_in_prompt: Whether to expose this command to the LLM via
            ``render_llm_context()``. Defaults to True. Set False to keep
            the command available to CLI users but invisible to the LLM.

    Returns:
        A ``CommandSpec`` that can be registered with
        ``CommandRegistry.register_spec()``.

    Raises:
        TypeError: If ``model`` is not a dataclass and is not a Pydantic
            ``BaseModel`` subclass.

    Example:
        >>> from dataclasses import dataclass
        >>> from typing import Annotated
        >>> from agenticli import CommandRegistry, Option, command_from_model
        >>>
        >>> @dataclass
        ... class MultiplyInput:
        ...     left: Annotated[float, Option(short="l")]
        ...     right: Annotated[float, Option(short="r")]
        ...     precision: Annotated[int, Option(short="p")] = 2
        ...
        >>> def multiply(left: float, right: float, precision: int = 2) -> dict:
        ...     return {"result": round(left * right, precision)}
        ...
        >>> registry = CommandRegistry()
        >>> registry.register_spec(
        ...     command_from_model(
        ...         "multiply",
        ...         MultiplyInput,
        ...         multiply,
        ...         description="Multiply two numbers",
        ...     )
        ... )
        >>> result = registry.execute("multiply -l 1.234 -r 10 -p 1")
        >>> result.value
        {'result': 12.3}

    Positional example:
        >>> @dataclass
        ... class SumInput:
        ...     values: Annotated[list[float], Option(positional=True)]
        ...
        >>> def sum_values(values: list[float]) -> dict:
        ...     return {"result": sum(values)}
        ...
        >>> registry = CommandRegistry()
        >>> registry.register_spec(command_from_model("sum", SumInput, sum_values))
        >>> registry.execute("sum 1 2 3").value
        {'result': 6.0}
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
        include_in_prompt=include_in_prompt,
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
    include_in_prompt: bool = True,
) -> CommandSpec:
    """Expose one method on a class or instance as an agenticli command.

    This helper is useful when you already have a small service/tool object and
    want to expose one of its methods without adding decorators to the class.
    The method signature is inspected with the same rules as ``@command``:
    parameters become CLI options or positional arguments, ``Annotated[..., Option(...)]``
    adds CLI metadata, async methods are supported, and the method return value
    becomes the command result.

    If ``target`` is a class, agenticli creates one instance with ``target()``.
    If ``target`` is already an instance, that exact instance is reused. Reusing
    an instance is useful for stateful command sets, for example a shell-like
    object where ``cd`` changes the current directory used by later commands.

    Args:
        name: Command name used by ``CommandRegistry.execute()``, such as
            ``"ls"`` or ``"user create"``.
        target: A class or instance containing the method to expose.
        method_name: Name of the method to expose. Defaults to ``"run"``.
        description: Help text and LLM context summary. If omitted, the method
            docstring is used.
        aliases: Alternative command names that invoke the same method.
        hidden: Hide the command from command listings while keeping it callable.
        deprecated: Optional deprecation message shown in help output.
        include_in_prompt: Whether to expose this command to the LLM via
            ``render_llm_context()``. Defaults to True. Set False to keep
            the command available to CLI users but invisible to the LLM.

    Returns:
        A ``CommandSpec`` that can be registered with
        ``CommandRegistry.register_spec()``.

    Raises:
        AttributeError: If ``target`` does not have ``method_name``.
        TypeError: If the named attribute exists but is not callable.

    Example:
        >>> from typing import Annotated
        >>> from agenticli import CommandRegistry, Option, command_from_method
        >>>
        >>> class Files:
        ...     def ls(
        ...         self,
        ...         path: Annotated[str, Option(positional=True)] = ".",
        ...         all: Annotated[bool, Option(short="a")] = False,
        ...     ) -> dict:
        ...         return {"path": path, "all": all}
        ...
        >>> registry = CommandRegistry()
        >>> registry.register_spec(command_from_method("ls", Files(), "ls"))
        >>> result = registry.execute("ls -a example")
        >>> result.ok
        True
        >>> result.value
        {'path': 'example', 'all': True}
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
        include_in_prompt=include_in_prompt,
        injections=dict(adapter.injections),
        injection_factories=dict(adapter.injection_factories),
    )
