"""Argument parser for CLI-style command strings.

This module provides the CommandParser class which parses CLI-style command
strings into structured arguments, handling both short and long options,
positional arguments, and various argument patterns.
"""

from __future__ import annotations

import shlex
from typing import Any

from llmcli.types import ArgSpec, ParseResult


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
        if not parts:
            return ParseResult(command="", args={}, raw=command_str)

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

        return ParseResult(command=command, args=args, raw=command_str, errors=errors)

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
