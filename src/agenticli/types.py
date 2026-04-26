"""Type definitions for agenticli.

This module provides the core type definitions used throughout the agenticli package,
including data classes for arguments, commands, execution results, and error handling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ArgSpec:
    """Specification for a command argument.

    Defines the metadata for a command-line argument including name, type,
    default value, description, and validation constraints.

    Attributes:
        name: Argument name used to identify the parameter in command calls.
        type: Python type or type string, defaults to str.
        default: Default value for the parameter if not provided.
        required: Whether the parameter must be provided, defaults to False.
        description: Description text for documentation and help output.
        enum: List of allowed values; if specified, value must be in this list.
        short: Short name (single character) for quick invocation.
        is_flag: Whether the argument is a boolean flag, defaults to False.
        schema: JSON Schema definition for API documentation and validation.
        positional: Whether the argument is positional, defaults to False.
        value_name: Placeholder name for the value in usage help text.
        example: Example value for documentation and help text.
        order: Sorting order for argument display in help text.
        position: Position index for determining positional argument order.
        hidden: Whether to hide from help text, defaults to False.
        repeatable: Whether the argument can be provided multiple times.
        nargs: Number of values the argument accepts; None means any number.
        requires: List of argument names this argument depends on.
        excludes: List of argument names that cannot be used with this argument.
        raw_annotation: Original type annotation object.
    """

    name: str
    type: type | str = str
    default: Any = None
    required: bool = False
    description: str = ""
    enum: list[Any] | None = None
    short: str | None = None
    is_flag: bool = False
    schema: dict[str, Any] | None = None
    positional: bool = False
    value_name: str | None = None
    example: str | None = None
    order: int | None = None
    position: int | None = None
    hidden: bool = False
    repeatable: bool = False
    nargs: int | None = None
    requires: list[str] = field(default_factory=list)
    excludes: list[str] = field(default_factory=list)
    raw_annotation: Any = str


@dataclass
class CommandSpec:
    """Specification for a registered command.

    Defines the complete specification for a registered command including
    name, description, execution function, argument list, and metadata.

    Attributes:
        name: Unique command name used for invocation and registration.
        description: Command description explaining purpose and functionality.
        func: Execution function, can be sync or async.
        args: List of command argument specifications.
        usage: Usage format string for help text.
        aliases: List of command aliases for alternative invocation.
        parent: Parent command name for subcommand organization.
        validator: Argument validator for parsing and validating user input.
        source: Command source identifier (e.g., "function", "class", "wrapped-tool").
        help_text: Complete help text content.
        hidden: Whether to hide from command list, defaults to False.
        deprecated: If set, indicates command is deprecated with deprecation notice.
        injections: Dictionary of static values injected at execution time.
        injection_factories: Dictionary of factory functions for generating injected values.
    """

    name: str
    description: str
    func: Callable[..., Any]
    args: list[ArgSpec] = field(default_factory=list)
    usage: str = ""
    aliases: list[str] = field(default_factory=list)
    parent: str | None = None
    validator: Any = None
    source: str = "function"
    help_text: str = ""
    hidden: bool = False
    deprecated: str | None = None
    injections: dict[str, Any] = field(default_factory=dict)
    injection_factories: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParseResult:
    """Result of parsing a command string.

    Contains the parsed command name, arguments, and any errors encountered
    during parsing.

    Attributes:
        command: Parsed command name.
        args: Dictionary of parsed arguments keyed by parameter name.
        raw: Original command string.
        errors: List of errors encountered during parsing.
    """

    command: str
    args: dict[str, Any]
    raw: str
    errors: list[str] = field(default_factory=list)


@dataclass
class HitResult:
    """Result of hit detection.

    Represents the outcome of matching user input against registered commands.

    Attributes:
        command: Matched command name, or None if no match.
        confidence: Match confidence between 0.0 and 1.0; 1.0 is exact match.
        suggested_args: Suggested arguments extracted from user input.
        match_type: Type of match (e.g., "exact", "prefix", "slash").
        args_str: Remaining argument string after command match.
    """

    command: str | None
    confidence: float = 0.0
    suggested_args: dict[str, Any] | None = None
    match_type: str | None = None
    args_str: str | None = None


@dataclass
class CommandError:
    """Structured command error.

    Provides a unified error format with error code, message, optional
    suggestion, and hint information.

    Attributes:
        code: Error code for error type identification (e.g., "unknown_command", "parse_error").
        message: Error message describing what went wrong.
        hint: Optional hint information to help user fix the error.
        suggestion: Optional suggestion value such as spelling correction.
        subject: Error subject, typically the command or argument causing the error.
        details: Additional detail dictionary for extra error context.

    Example:
        >>> error = CommandError(
        ...     code="unknown_command",
        ...     message="Command 'foo' not found",
        ...     suggestion="bar",
        ...     subject="foo"
        ... )
        >>> print(error.render())
        Error: Command 'foo' not found Did you mean 'bar'?
    """

    code: str
    message: str
    hint: str | None = None
    suggestion: str | None = None
    subject: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def render(self) -> str:
        """Render the error as a human-readable string.

        Returns:
            Formatted error message with optional suggestion and hint.
        """
        text = f"Error: {self.message}"
        if self.suggestion:
            text += f" Did you mean '{self.suggestion}'?"
        if self.hint:
            text += f" {self.hint}"
        return text


@dataclass
class ExecutionResult:
    """Structured command execution result.

    Contains whether execution succeeded and associated data.

    Attributes:
        ok: Boolean indicating if execution was successful.
        command: Name of the executed command.
        value: Return value if command succeeded, None otherwise.
        error: CommandError object if execution failed, None otherwise.

    Example:
        >>> result = ExecutionResult(ok=True, command="exec", value="output")
        >>> if result.ok:
        ...     print(result.value)
    """

    ok: bool
    command: str | None = None
    value: Any = None
    error: CommandError | None = None


@dataclass
class ExecutionContext:
    """Lifecycle context for command execution callbacks.

    Passed to before_execute, after_execute, and on_error callbacks,
    allowing access to and modification of execution state.

    Attributes:
        command: Name of the command being executed.
        raw: Raw command string.
        args: Parsed argument dictionary.
        result: Command execution result.
        error: Error that occurred if execution failed.

    Note:
        In before_execute callbacks, both result and error will be None.
        In after_execute callbacks, result contains the return value if successful.
        In on_error callbacks, error contains the error details.
    """

    command: str
    raw: str
    args: dict[str, Any] = field(default_factory=dict)
    result: Any = None
    error: CommandError | None = None


@dataclass
class ExecutionCallbacks:
    """Lifecycle callbacks for command execution.

    Collection of lifecycle callbacks allowing custom logic to execute
    before, after, or on error during command execution. Useful for
    logging, monitoring, and auditing.

    Attributes:
        before_execute: Callback invoked before command execution. Receives
            ExecutionContext. If returns a coroutine, runs synchronously.
        after_execute: Callback invoked after command execution. Receives
            ExecutionContext. Can access result via context.result.
        on_error: Callback invoked when command execution fails. Receives
            ExecutionContext. context.error contains error details.

    Example:
        >>> def log_before(ctx):
        ...     print(f"Executing: {ctx.command}")
        ...
        >>> registry = CommandRegistry(callbacks=ExecutionCallbacks(
        ...     before_execute=log_before
        ... ))
    """

    before_execute: Callable[[ExecutionContext], Any] | None = None
    after_execute: Callable[[ExecutionContext], Any] | None = None
    on_error: Callable[[ExecutionContext], Any] | None = None
