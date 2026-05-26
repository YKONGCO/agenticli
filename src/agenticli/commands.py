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
    """Build a command from a dataclass or Pydantic model plus a handler."""
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
    """Build a command from a single method on a class or instance."""
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
