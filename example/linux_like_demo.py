"""Linux-like command demo for common read-only filesystem operations.

The demo intentionally implements a small, safe subset of familiar commands
instead of executing arbitrary shell commands. It is meant to show how an LLM
can emit compact command strings such as `ls -a -l example` while your Python
code keeps control over validation, execution, and output shape.
"""

from __future__ import annotations

import fnmatch
import json
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from agenticli import CommandRegistry, Option, command_from_method


@dataclass
class ShellState:
    cwd: Path


def _resolve(cwd: Path, path: str) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = cwd / candidate
    return candidate.resolve()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


class LinuxLikeCommands:
    """Small read-only command set with `cd` state shared by one registry."""

    def __init__(self, root: Path | None = None) -> None:
        self.state = ShellState(cwd=(root or Path.cwd()).resolve())

    def pwd(self) -> dict[str, str]:
        """Print the current working directory."""
        return {"cwd": str(self.state.cwd)}

    def cd(
        self,
        path: Annotated[
            str,
            Option(positional=True, value_name="path", description="Directory to enter", example="cd example"),
        ],
    ) -> dict[str, str]:
        """Change the demo shell's current working directory."""
        target = _resolve(self.state.cwd, path)
        if not target.exists():
            raise FileNotFoundError(path)
        if not target.is_dir():
            raise NotADirectoryError(path)
        self.state.cwd = target
        return {"cwd": str(self.state.cwd)}

    def ls(
        self,
        path: Annotated[
            str,
            Option(positional=True, value_name="path", description="File or directory to list", example="ls -a -l example"),
        ] = ".",
        all: Annotated[bool, Option(short="a", description="Include dotfiles")] = False,
        long: Annotated[bool, Option(short="l", description="Return mode, size, and modified time")] = False,
    ) -> dict[str, Any]:
        """List files, similar to a structured `ls`."""
        target = _resolve(self.state.cwd, path)
        if not target.exists():
            raise FileNotFoundError(path)

        paths = [target] if target.is_file() else sorted(target.iterdir(), key=lambda item: item.name.lower())
        visible = [item for item in paths if all or not item.name.startswith(".")]
        if not long:
            return {"path": str(target), "entries": [item.name for item in visible]}

        entries = []
        for item in visible:
            info = item.stat()
            entries.append(
                {
                    "name": item.name,
                    "type": "dir" if item.is_dir() else "file",
                    "size": info.st_size,
                    "mode": stat.filemode(info.st_mode),
                    "modified": datetime.fromtimestamp(info.st_mtime).isoformat(timespec="seconds"),
                }
            )
        return {"path": str(target), "entries": entries}

    def cat(
        self,
        path: Annotated[
            str,
            Option(positional=True, value_name="file", description="File to print", example="cat README.md"),
        ],
    ) -> dict[str, str]:
        """Return a file's text content."""
        target = _resolve(self.state.cwd, path)
        if not target.is_file():
            raise FileNotFoundError(path)
        return {"path": str(target), "content": _read_text(target)}

    def head(
        self,
        path: Annotated[
            str,
            Option(positional=True, value_name="file", description="File to read", example="head README.md -n 5"),
        ],
        lines: Annotated[int, Option(short="n", description="Number of lines")] = 10,
    ) -> dict[str, Any]:
        """Return the first N lines of a file."""
        target = _resolve(self.state.cwd, path)
        if lines < 0:
            raise ValueError("lines must be >= 0")
        content = _read_text(target).splitlines()
        return {"path": str(target), "lines": content[:lines]}

    def grep(
        self,
        pattern: Annotated[
            str,
            Option(positional=True, value_name="pattern", description="Substring or glob pattern to find"),
        ],
        paths: Annotated[
            list[str],
            Option(positional=True, value_name="file", description="Files to search", example="grep agenticli README.md README_zh.md"),
        ],
        ignore_case: Annotated[bool, Option(short="i", description="Case-insensitive match")] = False,
        glob: Annotated[bool, Option(short="g", description="Treat pattern as a shell glob")] = False,
    ) -> dict[str, Any]:
        """Search files, similar to a small structured `grep`."""
        needle = pattern.lower() if ignore_case else pattern
        matches: list[dict[str, Any]] = []
        for raw_path in paths:
            target = _resolve(self.state.cwd, raw_path)
            for line_no, line in enumerate(_read_text(target).splitlines(), start=1):
                haystack = line.lower() if ignore_case else line
                hit = fnmatch.fnmatch(haystack, needle) if glob else needle in haystack
                if hit:
                    matches.append({"path": str(target), "line": line_no, "text": line})
        return {"pattern": pattern, "matches": matches}

    def wc(
        self,
        path: Annotated[
            str,
            Option(positional=True, value_name="file", description="File to count", example="wc README.md -l -w"),
        ],
        lines: Annotated[bool, Option(short="l", description="Include line count")] = False,
        words: Annotated[bool, Option(short="w", description="Include word count")] = False,
        bytes: Annotated[bool, Option(short="c", description="Include byte count")] = False,
    ) -> dict[str, Any]:
        """Count lines, words, and bytes for a text file."""
        target = _resolve(self.state.cwd, path)
        content = _read_text(target)
        include_all = not (lines or words or bytes)
        result: dict[str, Any] = {"path": str(target)}
        if include_all or lines:
            result["lines"] = len(content.splitlines())
        if include_all or words:
            result["words"] = len(content.split())
        if include_all or bytes:
            result["bytes"] = len(content.encode("utf-8"))
        return result


def build_registry(root: Path | str | None = None) -> CommandRegistry:
    commands = LinuxLikeCommands(Path(root) if root is not None else None)
    registry = CommandRegistry()
    for name in ("pwd", "cd", "ls", "cat", "head", "grep", "wc"):
        registry.register_spec(
            command_from_method(
                name=name,
                target=commands,
                method_name=name,
                description=getattr(commands, name).__doc__ or "",
            )
        )
    return registry


def execute_value(registry: CommandRegistry, command_text: str) -> Any:
    result = registry.execute(command_text)
    if isinstance(result, list):
        return result
    return result.value if result.ok else result.error.render()


def main() -> None:
    registry = build_registry()
    examples = [
        "pwd",
        "ls example",
        "ls -a -l example",
        "head README.md -n 5",
        "grep agenticli README.md README_zh.md -i",
        "wc README.md -l -w -c",
        "cd example ; pwd ; ls",
    ]

    for command_text in examples:
        print(f"\n$ {command_text}")
        output = registry.execute(command_text, chain=";" in command_text)
        if isinstance(output, list):
            print(json.dumps(output, indent=2, ensure_ascii=False))
        else:
            value = output.value if output.ok else output.error.render()
            print(json.dumps(value, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
