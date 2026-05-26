"""Builtin tools for agenticli.

This module provides built-in command tools that ship with agenticli,
including the ExecTool callback bridge for command strings.
"""

from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable


class ExecTool:
    """Minimal schema-based exec tool backed by a callback.

    Provides a schema-based command tool that delegates to a user-provided
    callback function. The callback receives the command string and any
    additional arguments. ExecTool does not execute a shell by itself.

    Attributes:
        name: Command name, defaults to "exec".
        description: Human-readable description of the command.
        parameters: JSON schema describing the command arguments.

    Example:
        >>> def execute_cmd(cmd: str, timeout: int = 60):
        ...     return subprocess.run(cmd, shell=True, timeout=timeout)
        ...
        >>> tool = ExecTool(callback=execute_cmd)
        >>> spec = wrap_tool(tool)
    """

    name = "exec"
    description = "Execute a command string through a callback."
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Command text to execute",
            },
            "timeout": {
                "type": "integer",
                "description": "Execution timeout in seconds",
                "default": 60,
            },
        },
        "required": ["command"],
    }

    def __init__(self, callback: Callable[..., Any] | Callable[..., Awaitable[Any]]):
        """Initialize ExecTool with execution callback.

        Args:
            callback: Function to execute with command. Can be sync or async.
        """
        self._callback = callback

    async def execute(self, **kwargs: Any) -> Any:
        """Execute the command via callback.

        Args:
            **kwargs: Arguments from parsed command, must include 'command'.

        Returns:
            Result from the callback function.
        """
        command = kwargs.pop("command", None)
        if command is not None:
            result = self._callback(command, **kwargs)
        else:
            result = self._callback(**kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    def to_schema(self) -> dict[str, Any]:
        """Convert tool to OpenAI function schema format.

        Returns:
            Dictionary with type "function" and function definition.
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
