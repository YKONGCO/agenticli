"""Argument parser for CLI-style command strings.

This module provides the CommandParser class which parses CLI-style command
strings into structured arguments, handling both short and long options,
positional arguments, and various argument patterns.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Any, Literal

from agenticli.types import ArgSpec, ParseResult


ChainOperator = Literal[";", "&&", "||"]


@dataclass(frozen=True)
class ChainSegment:
    """A command segment in a chain and the operator that follows it."""

    command: str
    operator_after: ChainOperator | None = None


class CommandLineParser:
    """Parses command-line text before command-specific argument parsing."""

    OPERATORS = {";", "&&", "||"}

    def parse(self, command_str: str, *, chain: bool = False) -> str | list[ChainSegment]:
        """Preprocess command text, optionally splitting it as a command chain."""
        command_str = self.preprocess(command_str)
        if chain:
            return self.split_chain(command_str)
        return command_str

    @classmethod
    def split_chain(cls, command_str: str) -> list[ChainSegment]:
        """Split command chains on operators while respecting shell-style quotes."""
        tokens = cls.split_chain_tokens(command_str)
        if not tokens:
            return []

        segments: list[ChainSegment] = []
        pending_cmd = tokens[0]
        i = 1

        while i < len(tokens):
            token = tokens[i]
            if token in cls.OPERATORS:
                if pending_cmd:
                    segments.append(ChainSegment(pending_cmd, token))  # type: ignore[arg-type]
                pending_cmd = ""
                i += 1
                continue
            pending_cmd = f"{pending_cmd} {token}".strip()
            i += 1

        if pending_cmd:
            segments.append(ChainSegment(pending_cmd))
        return segments

    @staticmethod
    def parser_parts(command_name: str, parts: list[str]) -> list[str]:
        """Prepare tokenized input for CommandParser."""
        command_parts = command_name.split()
        consumed = len(command_parts)
        return [command_parts[-1], *parts[consumed:]]

    @staticmethod
    def preprocess(command_str: str) -> str:
        """Apply command-level preprocessing before parsing or chain splitting."""
        return CommandLineParser.preprocess_backslash(command_str)

    @staticmethod
    def preprocess_backslash(command_str: str) -> str:
        """Handle backslash line continuations."""
        if "\\\n" not in command_str and "\\\r" not in command_str:
            return command_str

        result: list[str] = []
        i = 0

        while i < len(command_str):
            ch = command_str[i]

            if ch == "\\" and i + 1 < len(command_str):
                next_ch = command_str[i + 1]

                if next_ch == "\n":
                    result.append(" ")
                    i += 2
                    continue

                if next_ch == "\r":
                    result.append(" ")
                    i += 2
                    if i < len(command_str) and command_str[i] == "\n":
                        i += 1
                    continue

            result.append(ch)
            i += 1

        return "".join(result)

    @staticmethod
    def split_chain_tokens(command_str: str) -> list[str]:
        """Split command chains on operators while respecting shell-style quotes."""
        tokens: list[str] = []
        current: list[str] = []
        quote: str | None = None
        escaped = False
        i = 0

        while i < len(command_str):
            ch = command_str[i]

            if escaped:
                current.append(ch)
                escaped = False
                i += 1
                continue

            if ch == "\\":
                current.append(ch)
                escaped = True
                i += 1
                continue

            if quote:
                current.append(ch)
                if ch == quote:
                    quote = None
                i += 1
                continue

            if ch in {"'", '"'}:
                current.append(ch)
                quote = ch
                i += 1
                continue

            if command_str.startswith("&&", i) or command_str.startswith("||", i):
                command = "".join(current).strip()
                if command:
                    tokens.append(command)
                tokens.append(command_str[i : i + 2])
                current = []
                i += 2
                continue

            if ch == ";":
                command = "".join(current).strip()
                if command:
                    tokens.append(command)
                tokens.append(";")
                current = []
                i += 1
                continue

            current.append(ch)
            i += 1

        command = "".join(current).strip()
        if command:
            tokens.append(command)
        return tokens


class CommandParser:
    """Parses CLI-style command strings into structured arguments.

    Handles parsing of both short options (e.g., -v) and long options (e.g.,
    --verbose), positional arguments, flags, and multi-value arguments (nargs).

    Attributes:
        args: List of ArgSpec objects defining valid arguments.

    Example:
        >>> spec = [
        ...     ArgSpec(name="command", type=str, required=True, positional=True),
        ...     ArgSpec(name="timeout", type=int, default=60, short="t"),
        ... ]
        >>> parser = CommandParser(spec)
        >>> result = parser.parse("ls --timeout 30")
    """

    def __init__(self, args: list[ArgSpec]):
        """Initialize parser with argument specifications.

        Args:
            args: List of ArgSpec defining valid command arguments.
        """
        self.args = args
        self._named_args = {arg.name: arg for arg in args}
        self._short_args = {arg.short: arg for arg in args if arg.short}
        indexed = list(enumerate(args))
        ordered = [
            arg
            for _, arg in sorted(
                indexed,
                key=lambda item: (
                    item[1].position is None,
                    item[1].position if item[1].position is not None else 10_000,
                    item[1].order is None,
                    item[1].order if item[1].order is not None else 10_000,
                    item[0],
                ),
            )
        ]
        self._positional_args = [arg for arg in ordered if not arg.is_flag]
        self.args = args
        self._named_args = {arg.name: arg for arg in args}
        self._short_args = {arg.short: arg for arg in args if arg.short}
        indexed = list(enumerate(args))
        ordered = [
            arg
            for _, arg in sorted(
                indexed,
                key=lambda item: (
                    item[1].position is None,
                    item[1].position if item[1].position is not None else 10_000,
                    item[1].order is None,
                    item[1].order if item[1].order is not None else 10_000,
                    item[0],
                ),
            )
        ]
        self._positional_args = [arg for arg in ordered if not arg.is_flag]

    def parse(self, command_str: str) -> ParseResult:
        """Parse a command string into structured arguments.

        Supports:
            - Long options: --option value
            - Short options: -o value
            - Inline values: --option=value or -ovalue
            - Flags: --flag (sets boolean to True)
            - Positional arguments
            - Repeated options with list accumulation

        Args:
            command_str: The command string to parse.

        Returns:
            ParseResult containing parsed command name, arguments, and any errors.

        Example:
            >>> parser = CommandParser([
            ...     ArgSpec(name="name", required=True, positional=True),
            ...     ArgSpec(name="verbose", is_flag=True),
            ... ])
            >>> result = parser.parse("john --verbose")
            >>> result.command
            'john'
            >>> result.args['verbose']
            True
        """
        parts = shlex.split(command_str.strip())
        return self.parse_tokens(parts, raw=command_str)

    def parse_tokens(self, parts: list[str], *, raw: str | None = None) -> ParseResult:
        """Parse pre-tokenized command parts into structured arguments.

        Args:
            parts: Shell-style tokens, including the local command name at index 0.
            raw: Original command string, if available.

        Returns:
            ParseResult containing parsed command name, arguments, and any errors.
        """
        raw_text = raw if raw is not None else shlex.join(parts)
        if not parts:
            return ParseResult(command="", args={}, raw=raw_text)

        command = parts[0]
        tokens = parts[1:]
        args: dict[str, Any] = {}
        positional_values: list[str] = []
        errors: list[str] = []
        index = 0

        while index < len(tokens):
            token = tokens[index]

            if token.startswith("--"):
                key, inline_value = self._parse_long_option(token)
                arg_spec = self._named_args.get(key)
                if not arg_spec:
                    errors.append(f"unknown option: --{key}")
                    if inline_value is None and index + 1 < len(tokens) and not tokens[index + 1].startswith("-"):
                        index += 1
                    index += 1
                    continue
                if inline_value is not None:
                    self._store_value(args, arg_spec, inline_value)
                elif arg_spec.is_flag:
                    self._store_value(args, arg_spec, True)
                elif arg_spec.nargs and arg_spec.nargs > 1:
                    values, consumed = self._collect_nargs(tokens, index + 1, arg_spec.nargs)
                    if values is None:
                        errors.append(f"missing value for option: --{key}")
                    else:
                        self._store_value(args, arg_spec, values)
                        index += consumed
                elif index + 1 < len(tokens):
                    self._store_value(args, arg_spec, tokens[index + 1])
                    index += 1
                else:
                    errors.append(f"missing value for option: --{key}")
                index += 1
                continue

            if token.startswith("-") and token != "-":
                short_name, inline_value = self._parse_short_option(token)
                arg_spec = self._short_args.get(short_name)
                if not arg_spec:
                    errors.append(f"unknown option: -{short_name}")
                    if inline_value is None and index + 1 < len(tokens) and not tokens[index + 1].startswith("-"):
                        index += 1
                    index += 1
                    continue
                if inline_value is not None:
                    self._store_value(args, arg_spec, inline_value)
                elif arg_spec.is_flag:
                    self._store_value(args, arg_spec, True)
                elif arg_spec.nargs and arg_spec.nargs > 1:
                    values, consumed = self._collect_nargs(tokens, index + 1, arg_spec.nargs)
                    if values is None:
                        errors.append(f"missing value for option: -{short_name}")
                    else:
                        self._store_value(args, arg_spec, values)
                        index += consumed
                elif index + 1 < len(tokens):
                    self._store_value(args, arg_spec, tokens[index + 1])
                    index += 1
                else:
                    errors.append(f"missing value for option: -{short_name}")
                index += 1
                continue

            positional_values.append(token)
            index += 1

        positional_index = 0
        for arg in self._positional_args:
            if arg.name in args:
                continue
            if positional_index >= len(positional_values):
                break
            if arg.nargs and arg.nargs > 1:
                if positional_index + arg.nargs > len(positional_values):
                    break
                args[arg.name] = positional_values[positional_index : positional_index + arg.nargs]
                positional_index += arg.nargs
                continue
            if arg.repeatable or arg.type == list:
                args[arg.name] = positional_values[positional_index:]
                positional_index = len(positional_values)
                continue
            args[arg.name] = positional_values[positional_index]
            positional_index += 1

        if positional_index < len(positional_values):
            for value in positional_values[positional_index:]:
                errors.append(f"unexpected positional argument: {value}")

        return ParseResult(command=command, args=args, raw=raw_text, errors=errors)

    @staticmethod
    def _parse_long_option(token: str) -> tuple[str, str | None]:
        """Parse a long option token (e.g., --option or --option=value).

        Args:
            token: The token to parse (without leading whitespace).

        Returns:
            Tuple of (option_name, inline_value) where inline_value is None
            if not present in --option=value format.
        """
        if "=" in token:
            key, value = token[2:].split("=", 1)
            return key, value
        return token[2:], None

    @staticmethod
    def _parse_short_option(token: str) -> tuple[str, str | None]:
        """Parse a short option token (e.g., -o or -oval).

        Args:
            token: The token to parse (without leading whitespace).

        Returns:
            Tuple of (short_name, inline_value) where inline_value is the
            remaining characters after the short flag, or None if single char.
        """
        if len(token) > 2:
            return token[1], token[2:] if token[2] != "=" else token[3:]
        return token[1], None

    @staticmethod
    def _collect_nargs(tokens: list[str], start: int, nargs: int) -> tuple[list[str] | None, int]:
        """Collect multiple argument values for nargs.

        Args:
            tokens: List of remaining tokens to consume from.
            start: Starting index in tokens.
            nargs: Number of values to collect.

        Returns:
            Tuple of (collected_values, number_consumed) or (None, 0) if
            insufficient tokens or hit a flag marker.
        """
        values: list[str] = []
        offset = start
        while offset < len(tokens) and len(values) < nargs:
            token = tokens[offset]
            if token.startswith("-"):
                break
            values.append(token)
            offset += 1
        if len(values) != nargs:
            return None, 0
        return values, len(values)

    @staticmethod
    def _store_value(args: dict[str, Any], arg_spec: ArgSpec, value: Any) -> None:
        """Store a value for an argument, handling repeatables.

        Args:
            args: The arguments dictionary to store value in.
            arg_spec: The argument specification.
            value: The value to store.
        """
        if arg_spec.repeatable:
            current = args.get(arg_spec.name)
            if current is None:
                args[arg_spec.name] = value if isinstance(value, list) else [value]
            else:
                if not isinstance(current, list):
                    current = [current]
                if isinstance(value, list):
                    current.extend(value)
                else:
                    current.append(value)
                args[arg_spec.name] = current
            return
        args[arg_spec.name] = value
