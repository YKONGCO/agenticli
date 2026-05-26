"""Command matching and hit detection."""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable, Mapping

from agenticli.parser import CommandLineParser
from agenticli.types import CommandSpec, HitResult


class CommandMatcher:
    """Matches raw text against registered commands."""

    def __init__(
        self,
        commands: Mapping[str, CommandSpec],
        resolve_command: Callable[[list[str]], tuple[str, CommandSpec | None]],
        ensure_help_command: Callable[[], None],
    ):
        self._commands = commands
        self._resolve_command = resolve_command
        self._ensure_help_command = ensure_help_command
        self._line_parser = CommandLineParser()

    def match(self, text: str, *, chain: bool = False, mode: str = "command") -> HitResult | list[HitResult]:
        """Match text as a command, natural-language mention, or command chain."""
        if chain:
            segments = self._line_parser.split_chain(self._line_parser.preprocess(text))
            results: list[HitResult] = []
            for segment in segments:
                hit = self.match_cli_text(segment.command)
                results.append(hit)
                if not hit.command and segment.operator_after in {"&&", "||"}:
                    break
            return results
        if mode == "natural":
            return self.match_natural(text)
        if mode != "command":
            raise ValueError("mode must be 'command' or 'natural'")
        return self.match_cli_text(text)

    def match_natural(self, text: str) -> HitResult:
        """Detect if text mentions a registered command."""
        self._ensure_help_command()
        text_lower = text.lower()
        for name, spec in self._commands.items():
            if name.startswith("--"):
                continue
            if name in text_lower:
                suggested_args = {}
                for arg in spec.args:
                    patterns = [
                        rf"{arg.name}\s+is\s+([^\s]+)",
                        rf"{arg.name}:\s*([^\s]+)",
                        rf"for\s+([^\s]+)",
                    ]
                    for pattern in patterns:
                        match = re.search(pattern, text_lower)
                        if match:
                            suggested_args[arg.name] = match.group(1)
                            break
                return HitResult(command=name, confidence=0.9, suggested_args=suggested_args or None)
        return HitResult(command=None, confidence=0.0)

    def match_cli_text(self, text: str) -> HitResult:
        """Match text against registered command names."""
        self._ensure_help_command()
        text = text.strip()
        if not text:
            return HitResult(command=None, confidence=0.0)

        try:
            parts = shlex.split(text)
        except ValueError:
            parts = text.split()

        command_name, spec = self._resolve_command(parts)
        if spec:
            args_str = text[len(command_name):].strip() or None
            match_type = "exact" if parts and parts[0] == command_name.split()[0] else "prefix"
            return HitResult(command=command_name, confidence=1.0 if match_type == "exact" else 0.8, args_str=args_str, match_type=match_type)

        if text.startswith("/"):
            slash_parts = text[1:].split()
            if not slash_parts:
                return HitResult(command=None, confidence=0.0)
            candidate = slash_parts[0]
            for name in self._commands:
                if name.startswith(candidate):
                    return HitResult(command=name, confidence=0.7, match_type="slash")
        return HitResult(command=None, confidence=0.0)
