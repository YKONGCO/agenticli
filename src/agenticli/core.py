"""Core registry for parsing, validating, and executing CLI commands.

This module provides the CommandRegistry class which is the central component
for managing CLI commands, handling parsing, execution, chain execution with
operators (&&, ||, ;), and help text generation.
"""

from __future__ import annotations

import difflib
import inspect
import shlex
from typing import Any

from agenticli.factory import CommandFactory
from agenticli.matcher import CommandMatcher
from agenticli.parser import CommandLineParser, CommandParser
from agenticli.runtime import run_sync
from agenticli.types import ArgSpec, CommandError, CommandSpec, ExecutionCallbacks, ExecutionContext, ExecutionResult, HitResult, ParseResult


class CommandRegistry:
    """Registry for CLI commands with parsing and execution capabilities.

    Central component for managing command registration, parsing, and execution.
    Supports command groups, aliases, prefix matching, and lifecycle callbacks.

    Attributes:
        strict: If True, parsing errors prevent execution. Defaults to True.
        allow_prefix_match: If True, prefix matching resolves commands. Defaults to True.
        callbacks: Optional ExecutionCallbacks for lifecycle events.

    Example:
        >>> registry = CommandRegistry()
        >>> registry.register_spec(my_command_spec)
        >>> result = registry.execute("my_command --arg value")
        >>> print(result.value)
    """

    def __init__(
        self,
        *,
        strict: bool = True,
        allow_prefix_match: bool = True,
        callbacks: ExecutionCallbacks | None = None,
    ):
        """Initialize CommandRegistry.

        Args:
            strict: If True, parsing errors prevent command execution.
            allow_prefix_match: If True, allow prefix matching for commands.
            callbacks: Optional ExecutionCallbacks for lifecycle events.
        """
        self._commands: dict[str, CommandSpec] = {}
        self._help_added = False
        self.strict = strict
        self.allow_prefix_match = allow_prefix_match
        self.callbacks = callbacks or ExecutionCallbacks()
        self._line_parser = CommandLineParser()
        self._matcher = CommandMatcher(self._commands, self._resolve_command, self._ensure_help_command)

    def register(self, target: Any) -> None:
        """Register a decorated function, command class/instance, or schema-based tool.

        Automatically detects the target type and routes to appropriate registration.

        Args:
            target: Function decorated with @command, CliCommand class/instance,
                or object with __command_spec__, execute, and parameters.

        Raises:
            TypeError: If target is not a supported command type.
        """
        if hasattr(target, "__command_group__"):
            self._register_command_group(target)
            return

        self.register_spec(CommandFactory.from_target(target))

    def _register_command_group(self, cls: type) -> None:
        """Register a command group class with its subcommands.

        Args:
            cls: Class decorated with @command_group.
        """
        group_info = cls.__command_group__
        group_name = group_info["name"]
        self._check_conflicts(
            CommandSpec(
                name=group_name,
                description=group_info["description"],
                func=cls,
            )
        )

        group_spec = CommandSpec(
            name=group_name,
            description=group_info["description"],
            func=cls,
            args=[],
            usage=group_name,
            source="group",
            help_text=group_info["description"],
        )
        self._commands[group_name] = group_spec

        for attr_name in dir(cls):
            if attr_name.startswith("_"):
                continue
            attr = getattr(cls, attr_name)
            if callable(attr) and hasattr(attr, "__command_spec__"):
                spec: CommandSpec = attr.__command_spec__
                nested_name = f"{group_name} {spec.name}"
                if nested_name in self._commands:
                    raise ValueError(f"command already registered: {nested_name}")
                nested = CommandSpec(
                    name=nested_name,
                    description=spec.description,
                    func=spec.func,
                    args=[arg for arg in spec.args if arg.name != "self"],
                    usage=f"{group_name} {spec.usage}",
                    aliases=[],
                    parent=group_name,
                    validator=spec.validator,
                    source=spec.source,
                    help_text=spec.help_text.replace(f"Command: {spec.name}", f"Command: {group_name} {spec.name}"),
                )
                nested._group_class = cls  # type: ignore[attr-defined]
                nested._method_name = attr_name  # type: ignore[attr-defined]
                self._commands[nested.name] = nested

    def register_spec(self, spec: CommandSpec) -> None:
        """Register a CommandSpec in the registry.

        Also registers any aliases defined in the spec.

        Args:
            spec: CommandSpec to register.

        Raises:
            ValueError: If command name or alias is already registered.
        """
        self._check_conflicts(spec)
        self._commands[spec.name] = spec
        for alias in spec.aliases:
            self._commands[alias] = spec

    def _check_conflicts(self, spec: CommandSpec) -> None:
        """Check for naming conflicts before registration.

        Args:
            spec: CommandSpec to check.

        Raises:
            ValueError: If name or alias conflicts with existing command.
        """
        existing = self._commands.get(spec.name)
        if existing and existing is not spec:
            raise ValueError(f"command already registered: {spec.name}")
        for alias in spec.aliases:
            existing_alias = self._commands.get(alias)
            if existing_alias and existing_alias is not spec:
                raise ValueError(f"alias already registered: {alias}")

    def unregister(self, name: str) -> None:
        """Unregister a command and its aliases.

        Args:
            name: Command name to remove.
        """
        self._commands.pop(name, None)
        for alias in list(self._commands.keys()):
            if self._commands[alias].name == name:
                self._commands.pop(alias, None)

    def get(self, name: str) -> CommandSpec | None:
        """Get CommandSpec by name.

        Args:
            name: Command name.

        Returns:
            CommandSpec if found, None otherwise.
        """
        return self._commands.get(name)

    def has(self, name: str) -> bool:
        """Check if command is registered.

        Args:
            name: Command name.

        Returns:
            True if command exists, False otherwise.
        """
        return name in self._commands

    def _ensure_help_command(self) -> None:
        """Ensure --help command is registered."""
        if self._help_added:
            return

        async def help_handler(command: str | None = None) -> str:
            return self.help(command)

        help_spec = CommandSpec(
            name="--help",
            description="Show help for a command or list all commands",
            func=help_handler,
            args=[ArgSpec(name="command", type=str, required=False, description="Command to describe")],
            usage="--help [command]",
            source="builtin",
            help_text="Command: --help\nUsage: --help [command]",
        )
        self._commands["--help"] = help_spec
        self._help_added = True

    def parse(self, command_str: str, *, chain: bool = False) -> ParseResult | list[ParseResult | None] | None:
        """Parse a command string without executing.

        Args:
            command_str: Raw command string to parse.

        Returns:
            ParseResult if command found, None if not recognized.
        """
        if chain:
            segments = self._line_parser.split_chain(self._line_parser.preprocess(command_str))
            return [self.parse(segment.command) for segment in segments]

        self._ensure_help_command()
        command_str = self._line_parser.parse(command_str)  # type: ignore[assignment]
        try:
            parts = shlex.split(command_str.strip())
        except ValueError as exc:
            return ParseResult(command="", args={}, raw=command_str, errors=[str(exc)])
        if not parts:
            return None
        help_target = self._extract_help_target(parts)
        if help_target is not False:
            return ParseResult(command="--help", args={"command": help_target}, raw=command_str)
        command_name, spec = self._resolve_command(parts)
        if not spec:
            return None
        parser = CommandParser(spec.args)
        return parser.parse_tokens(self._line_parser.parser_parts(command_name, parts), raw=command_str)

    def match(self, text: str, *, chain: bool = False, mode: str = "command") -> HitResult | list[HitResult]:
        """Match text against registered commands.

        Args:
            text: Text to match.
            chain: If True, split text as a command chain before matching.
            mode: "command" for CLI command matching, "natural" for mention detection.

        Returns:
            HitResult for single input, or a list of HitResult for chain input.
        """
        return self._matcher.match(text, chain=chain, mode=mode)

    def execute(self, command_str: str, *, chain: bool = False) -> ExecutionResult | list[Any]:
        """Parse and execute a command string.

        Args:
            command_str: Command string to execute.

        Returns:
            ExecutionResult with ok status, value or error.
        """
        return run_sync(self.execute_async(command_str, chain=chain))

    async def execute_async(self, command_str: str, *, chain: bool = False) -> ExecutionResult | list[Any]:
        """Asynchronously parse and execute a command string.

        Args:
            command_str: Command string to execute.

        Returns:
            ExecutionResult with ok status, value or error.
        """
        if chain:
            return await self._execute_chain_async(command_str)

        self._ensure_help_command()
        command_str = self._line_parser.parse(command_str)  # type: ignore[assignment]
        stripped = command_str.strip()
        if not stripped:
            error = CommandError(code="empty_command", message="Empty command")
            await self._run_error_callback_async(ExecutionContext(command="", raw=command_str, error=error))
            return ExecutionResult(ok=False, error=error)
        try:
            parts = shlex.split(stripped)
        except ValueError as exc:
            error = CommandError(code="parse_error", message=str(exc), subject=command_str)
            await self._run_error_callback_async(ExecutionContext(command="", raw=command_str, error=error))
            return ExecutionResult(ok=False, command="", error=error)

        if parts[0].startswith('/'):
            parts[0] = parts[0][1:]

        help_target = self._extract_help_target(parts)
        if help_target is not False:
            return ExecutionResult(ok=True, command="--help", value=self.help(help_target))
        command_name, spec = self._resolve_command(parts)
        if not spec:
            suggestion = self._suggest_command(parts[0])
            if suggestion:
                error = CommandError(
                    code="unknown_command",
                    message="Unknown command.",
                    suggestion=suggestion,
                    subject=parts[0],
                )
                await self._run_error_callback_async(ExecutionContext(command=parts[0], raw=command_str, error=error))
                return ExecutionResult(
                    ok=False,
                    command=parts[0],
                    error=error,
                )
            error = CommandError(code="unknown_command", message="Unknown command", subject=parts[0])
            await self._run_error_callback_async(ExecutionContext(command=parts[0], raw=command_str, error=error))
            return ExecutionResult(
                ok=False,
                command=parts[0],
                error=error,
            )

        if command_name == "--help":
            command = parts[1] if len(parts) > 1 else None
            return ExecutionResult(ok=True, command="--help", value=self.help(command))
        if spec.source == "group":
            if len(parts) > 1:
                subject = f"{parts[0]} {parts[1]}"
                suggestion = self._suggest_group_subcommand(parts[0], parts[1])
                error = CommandError(
                    code="unknown_command",
                    message="Unknown command",
                    hint=f"Use '{parts[0]} --help' to inspect available subcommands.",
                    suggestion=suggestion,
                    subject=subject,
                )
                await self._run_error_callback_async(ExecutionContext(command=subject, raw=command_str, error=error))
                return ExecutionResult(ok=False, command=subject, error=error)
            return ExecutionResult(ok=True, command=command_name, value=self.help(command_name))

        parser = CommandParser(spec.args)
        parsed = parser.parse_tokens(self._line_parser.parser_parts(command_name, parts), raw=command_str)
        if self.strict and parsed.errors:
            error = self._build_parse_error(spec, parsed.errors)
            await self._run_error_callback_async(
                ExecutionContext(command=command_name, raw=command_str, args=parsed.args, error=error)
            )
            return ExecutionResult(ok=False, command=command_name, error=self._build_parse_error(spec, parsed.errors))
        value = await self._execute_spec_async(spec, parsed.args, raw=command_str)
        if isinstance(value, CommandError):
            await self._run_error_callback_async(
                ExecutionContext(command=command_name, raw=command_str, args=parsed.args, error=value)
            )
            return ExecutionResult(ok=False, command=command_name, error=value)
        return ExecutionResult(ok=True, command=command_name, value=value)

    async def _execute_chain_async(self, command_str: str) -> list[Any]:
        """Execute a command chain and return values or rendered errors."""
        segments = self._line_parser.split_chain(self._line_parser.preprocess(command_str))
        if not segments:
            return []

        results: list[Any] = []
        for segment in segments:
            result = await self.execute_async(segment.command)
            value = result.value if result.ok else result.error.render() if result.error else "Error: Unknown error"
            results.append(value)

            if segment.operator_after == "&&" and not result.ok:
                return results
            if segment.operator_after == "||" and result.ok:
                return results

        return results

    @staticmethod
    def _parser_input(command_name: str, parts: list[str]) -> str:
        """Prepare input string for CommandParser.

        Args:
            command_name: Name of the resolved command.
            parts: Tokenized command parts.

        Returns:
            String suitable for CommandParser.parse().
        """
        return shlex.join(CommandLineParser.parser_parts(command_name, parts))

    @staticmethod
    def _parser_parts(command_name: str, parts: list[str]) -> list[str]:
        """Prepare tokenized input for CommandParser."""
        return CommandLineParser.parser_parts(command_name, parts)

    @staticmethod
    def _preprocess_command_input(command_str: str) -> str:
        """Apply command-level preprocessing before parsing or chain splitting."""
        return CommandLineParser.preprocess(command_str)

    @staticmethod
    def _preprocess_backslash(command_str: str) -> str:
        """Handle backslash line continuations."""
        return CommandLineParser.preprocess_backslash(command_str)

    @staticmethod
    def _split_chain_tokens(command_str: str) -> list[str]:
        """Split command chains on operators while respecting shell-style quotes."""
        return CommandLineParser.split_chain_tokens(command_str)

    def _resolve_command(self, parts: list[str]) -> tuple[str, CommandSpec | None]:
        """Resolve command name from parts.

        Args:
            parts: Tokenized command parts.

        Returns:
            Tuple of (command_name, CommandSpec) or (name, None).
        """
        if not parts or not parts[0]:
            return "", None
        if parts[0] in {"--help", "-h"}:
            return "--help", self._commands.get("--help")
        if len(parts) >= 2:
            nested = f"{parts[0]} {parts[1]}"
            if nested in self._commands:
                return nested, self._commands[nested]
        if parts[0] in self._commands:
            return parts[0], self._commands[parts[0]]
        if self.allow_prefix_match:
            token = parts[0]
            if not token:
                return parts[0], None
            token_initial = token[0]
            for name, spec in self._commands.items():
                if not name or name[0] != token_initial:
                    continue
                if name.startswith(token) or token.startswith(name):
                    return name, spec
        return parts[0], None

    def _extract_help_target(self, parts: list[str]) -> str | None | bool:
        """Extract help target from command parts.

        Args:
            parts: Tokenized command parts.

        Returns:
            Command name for help, None for general help, False if not help.
        """
        if not parts:
            return False
        if parts[0] in {"--help", "-h"}:
            return parts[1] if len(parts) > 1 else None
        if parts[-1] not in {"--help", "-h"}:
            return False
        if len(parts) >= 2:
            nested = f"{parts[0]} {parts[1]}"
            if nested in self._commands and parts[-1] in {"--help", "-h"}:
                return nested
        return parts[0]

    def _execute_spec(self, spec: CommandSpec, raw_args: dict[str, Any], *, raw: str) -> Any:
        """Execute a CommandSpec with given arguments.

        Args:
            spec: Command specification to execute.
            raw_args: Parsed arguments.
            raw: Original command string.

        Returns:
            Command result or CommandError if execution fails.
        """
        return run_sync(self._execute_spec_async(spec, raw_args, raw=raw))

    async def _execute_spec_async(self, spec: CommandSpec, raw_args: dict[str, Any], *, raw: str) -> Any:
        """Asynchronously execute a CommandSpec with given arguments.

        Args:
            spec: Command specification to execute.
            raw_args: Parsed arguments.
            raw: Original command string.

        Returns:
            Command result or CommandError if execution fails.
        """
        try:
            validator = spec.validator
            sig_args = validator.validate(raw_args) if validator else raw_args
            context = ExecutionContext(command=spec.name, raw=raw, args=dict(sig_args))
            for key, value in spec.injections.items():
                sig_args[key] = value
            for key, factory in spec.injection_factories.items():
                produced = factory(context)
                if inspect.isawaitable(produced):
                    produced = await produced
                sig_args[key] = produced
            context.args = dict(sig_args)
            await self._run_before_callback_async(context)

            if hasattr(spec, "_group_class") and hasattr(spec, "_method_name"):
                instance = spec._group_class()  # type: ignore[attr-defined]
                method = getattr(instance, spec._method_name)  # type: ignore[attr-defined]
                result = await self._resolve_result_async(method(**sig_args))
                context.result = result
                await self._run_after_callback_async(context)
                return result

            result = await self._resolve_result_async(spec.func(**sig_args))
            context.result = result
            await self._run_after_callback_async(context)
            return result
        except Exception as exc:
            return CommandError(code="execution_error", message=f"executing {spec.name}: {exc}", subject=spec.name)

    def _suggest_command(self, token: str) -> str | None:
        """Suggest similar command for unknown token.

        Args:
            token: Unknown command token.

        Returns:
            Suggested command name or None.
        """
        candidates = [
            name for name, spec in self._commands.items()
            if not name.startswith("--") and not spec.parent and not spec.hidden
        ]
        matches = difflib.get_close_matches(token, candidates, n=1, cutoff=0.5)
        return matches[0] if matches else None

    def _suggest_group_subcommand(self, group_name: str, token: str) -> str | None:
        """Suggest a similar subcommand within a command group."""
        prefix = f"{group_name} "
        candidates = [
            name[len(prefix):]
            for name, spec in self._commands.items()
            if name.startswith(prefix) and spec.parent == group_name and not spec.hidden
        ]
        matches = difflib.get_close_matches(token, candidates, n=1, cutoff=0.5)
        return f"{group_name} {matches[0]}" if matches else None

    def _format_parse_error_hint(self, spec: CommandSpec, errors: list[str]) -> str:
        """Format hint for parse errors.

        Args:
            spec: Command specification.
            errors: List of error messages.

        Returns:
            Formatted hint string.
        """
        for error in errors:
            if error.startswith("unknown option:"):
                token = error.split(":", 1)[1].strip()
                suggestion = self._suggest_option(spec, token)
                if suggestion:
                    return f" Did you mean '{suggestion}'? Use '{spec.name} --help' to inspect valid options."
                return f" Use '{spec.name} --help' to inspect valid options."
            if error.startswith("missing value for option:"):
                return f" Use '{spec.name} --help' to inspect expected values."
            if error.startswith("unexpected positional argument:"):
                return f" Usage: {spec.usage}"
        return ""

    def _build_parse_error(self, spec: CommandSpec, errors: list[str]) -> CommandError:
        """Build CommandError from parse errors.

        Args:
            spec: Command specification.
            errors: List of error messages.

        Returns:
            CommandError with all error details.
        """
        suggestion = None
        hint = None
        message = "; ".join(errors)
        for error in errors:
            if error.startswith("unknown option:"):
                token = error.split(":", 1)[1].strip()
                suggestion = self._suggest_option(spec, token)
                hint = f"Use '{spec.name} --help' to inspect valid options."
                break
            if error.startswith("missing value for option:"):
                hint = f"Use '{spec.name} --help' to inspect expected values."
                break
            if error.startswith("unexpected positional argument:"):
                hint = f"Usage: {spec.usage}"
                break
        return CommandError(
            code="parse_error",
            message=message,
            hint=hint,
            suggestion=suggestion,
            subject=spec.name,
            details={"errors": errors},
        )

    def _run_before_callback(self, context: ExecutionContext) -> None:
        """Run before_execute callback if configured.

        Args:
            context: Execution context.
        """
        callback = self.callbacks.before_execute
        if callback:
            result = callback(context)
            if inspect.isawaitable(result):
                run_sync(result)

    async def _run_before_callback_async(self, context: ExecutionContext) -> None:
        """Asynchronously run before_execute callback if configured."""
        callback = self.callbacks.before_execute
        if callback:
            result = callback(context)
            if inspect.isawaitable(result):
                await result

    def _run_after_callback(self, context: ExecutionContext) -> None:
        """Run after_execute callback if configured.

        Args:
            context: Execution context.
        """
        callback = self.callbacks.after_execute
        if callback:
            result = callback(context)
            if inspect.isawaitable(result):
                run_sync(result)

    async def _run_after_callback_async(self, context: ExecutionContext) -> None:
        """Asynchronously run after_execute callback if configured."""
        callback = self.callbacks.after_execute
        if callback:
            result = callback(context)
            if inspect.isawaitable(result):
                await result

    def _run_error_callback(self, context: ExecutionContext) -> None:
        """Run on_error callback if configured.

        Args:
            context: Execution context.
        """
        callback = self.callbacks.on_error
        if callback:
            result = callback(context)
            if inspect.isawaitable(result):
                run_sync(result)

    async def _run_error_callback_async(self, context: ExecutionContext) -> None:
        """Asynchronously run on_error callback if configured."""
        callback = self.callbacks.on_error
        if callback:
            result = callback(context)
            if inspect.isawaitable(result):
                await result

    def _suggest_option(self, spec: CommandSpec, token: str) -> str | None:
        """Suggest similar option for unknown token.

        Args:
            spec: Command specification.
            token: Unknown option token.

        Returns:
            Suggested option name or None.
        """
        candidates: list[str] = []
        for arg in spec.args:
            if arg.hidden:
                continue
            candidates.append(f"--{arg.name}")
            if arg.short:
                candidates.append(f"-{arg.short}")
        matches = difflib.get_close_matches(token, candidates, n=1, cutoff=0.5)
        return matches[0] if matches else None

    @staticmethod
    def _resolve_result(result: Any) -> Any:
        """Resolve awaitable result.

        Args:
            result: Value that may be awaitable.

        Returns:
            Resolved value.
        """
        if inspect.isawaitable(result):
            return run_sync(result)
        return result

    @staticmethod
    async def _resolve_result_async(result: Any) -> Any:
        """Asynchronously resolve a possibly awaitable result."""
        if inspect.isawaitable(result):
            return await result
        return result

    def help(self, command: str | None = None) -> str:
        """Render help text for a command or list all commands.

        Args:
            command: Command name for specific help, or None for list.

        Returns:
            Formatted help text.
        """
        self._ensure_help_command()
        if command:
            spec = self._commands.get(command)
            if not spec:
                for name, candidate in self._commands.items():
                    if name.startswith(command):
                        spec = candidate
                        break
            if not spec:
                return f"Unknown command: {command}"
            if spec.source == "group":
                return self._render_group_help(spec)
            help_text = spec.help_text or f"Command: {spec.name}\nUsage: {spec.usage}"
            if spec.deprecated:
                help_text = f"Deprecated: {spec.deprecated}\n\n{help_text}"
            if spec.aliases:
                help_text += "\n\nAliases:\n  " + ", ".join(spec.aliases)
            return help_text

        lines = ["Available commands:", ""]
        seen: set[str] = set()
        for name, spec in sorted(self._commands.items()):
            if name.startswith("--") or spec.parent or spec.name in seen or spec.hidden:
                continue
            seen.add(spec.name)
            summary = spec.description.splitlines()[0] if spec.description else ""
            if spec.deprecated:
                summary = f"{summary} [deprecated]"
            lines.append(f"  {spec.name}: {summary}".rstrip())
        lines.extend(["", "Use <command> --help for detailed help."])
        return "\n".join(lines)

    def _render_group_help(self, spec: CommandSpec) -> str:
        """Render help text for a command group.

        Args:
            spec: Command specification for the group.

        Returns:
            Formatted help text for group and its subcommands.
        """
        lines = [f"Command: {spec.name}", f"Usage: {spec.name} <subcommand> [args...]"]
        if spec.description:
            lines.extend(["", spec.description.strip()])

        subcommands: list[CommandSpec] = []
        seen: set[str] = set()
        for candidate in self._commands.values():
            if candidate.parent == spec.name and candidate.name not in seen and not candidate.hidden:
                seen.add(candidate.name)
                subcommands.append(candidate)

        if subcommands:
            lines.extend(["", "Subcommands:"])
            for sub in sorted(subcommands, key=lambda item: item.name):
                short_name = sub.name.split(" ", 1)[1]
                summary = sub.description.splitlines()[0] if sub.description else ""
                if sub.deprecated:
                    summary = f"{summary} [deprecated]"
                lines.append(f"  {short_name}: {summary}".rstrip())
            lines.extend(["", f"Use {spec.name} <subcommand> --help for detailed help."])
        return "\n".join(lines)

    def render_llm_context(self, detailed: bool = False) -> str:
        """Render available commands as LLM-readable context text."""
        self._ensure_help_command()
        if not self._commands:
            return "No commands registered."

        lines = ["You can use the following CLI commands:"]
        seen: set[str] = set()
        for _, spec in sorted(self._commands.items()):
            if spec.name.startswith("--") or spec.parent or spec.name in seen or spec.hidden:
                continue
            seen.add(spec.name)
            if detailed:
                lines.append(f"  {spec.usage}")
                if spec.description:
                    summary = spec.description.splitlines()[0]
                    if spec.deprecated:
                        summary = f"{summary} [deprecated]"
                    lines.append(f"    {summary}")
            else:
                summary = spec.description.splitlines()[0] if spec.description else ""
                if spec.deprecated:
                    summary = f"{summary} [deprecated]"
                lines.append(f"  {spec.name}: {summary}".rstrip())

        lines.extend(
            [
                "",
                "Use <command> --help when you need full argument details.",
                "Output a command string directly, for example: exec --command 'ls -la'",
            ]
        )
        return "\n".join(lines)

    @property
    def commands(self) -> list[str]:
        """List of registered command names (excluding --help).

        Returns:
            Sorted list of visible command names.
        """
        self._ensure_help_command()
        return sorted({spec.name for spec in self._commands.values() if not spec.name.startswith("--")})

    def __len__(self) -> int:
        """Return number of registered commands.

        Returns:
            Count of visible commands.
        """
        return len(self.commands)

    def __contains__(self, name: str) -> bool:
        """Check if command is registered.

        Args:
            name: Command name.

        Returns:
            True if command exists.
        """
        return name in self._commands
