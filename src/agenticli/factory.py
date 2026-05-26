"""Conversion from supported command targets to CommandSpec objects."""

from __future__ import annotations

import inspect
from typing import Any

from agenticli.adapters import wrap_tool
from agenticli.commands import CliCommand
from agenticli.types import CommandSpec


class CommandFactory:
    """Build CommandSpec objects from supported registration targets."""

    @staticmethod
    def from_target(target: Any) -> CommandSpec:
        """Convert a decorated function, CliCommand, or schema tool to CommandSpec."""
        if isinstance(target, CliCommand):
            return target.to_command_spec()

        if inspect.isclass(target) and issubclass(target, CliCommand):
            return target().to_command_spec()

        if hasattr(target, "__command_spec__"):
            return target.__command_spec__

        if hasattr(target, "execute") and hasattr(target, "parameters"):
            return wrap_tool(target)

        raise TypeError(f"Unsupported command target: {target!r}")
