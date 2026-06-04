"""Demo: auto-discover and register command classes from a directory.

Shows how :meth:`agenticli.CommandRegistry.discover` finds:

* classes decorated with ``@command_group`` (``calc.py``, ``user.py``)
* subclasses of :class:`agenticli.CliCommand` (``ping.py``)

The ``context_provider`` callback binds request-scoped context to
instances of ``@command_group`` classes — here, simulating an
authenticated request as ``alice`` in tenant ``acme``. The ``package=``
argument makes ``discover()`` reuse ``sys.modules`` so the classes it
loads are the same objects the runner imported (the ``is UserService``
check in ``provide_context`` relies on this).

Run with::

    python -m example.discover
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agenticli import CommandRegistry
from example.discover_cmds.user import UserService


def provide_context(cls: type) -> Any:
    """Map each discovered class to a context-bound target.

    For ``UserService`` we supply the user id and tenant. Other classes
    use their default no-arg construction. Returning the instance for a
    class that already has a default constructor would also work; the
    registry handles either.
    """
    if cls is UserService:
        return cls(user_id="alice", tenant_id="acme")
    return cls()


def execute_value(registry: CommandRegistry, command_text: str) -> Any:
    result = registry.execute(command_text)
    if isinstance(result, list):
        return result
    return result.value if result.ok else result.error.render()


def build_registry() -> CommandRegistry:
    commands_dir = Path(__file__).parent / "discover_cmds"
    registry = CommandRegistry()
    # package= makes discover() reuse sys.modules so the classes it loads
    # are the same objects the runner imported (the `is UserService` check
    # in provide_context relies on this). When you don't need identity
    # matching — e.g. when context_provider dispatches by class name —
    # you can omit package= and the loader will use filesystem specs.
    result = registry.discover(
        commands_dir,
        context_provider=provide_context,
        package="example.discover_cmds",
    )
    print(f"Discovered {len(result.registered)} commands: {result.registered}")
    if result.errors:
        print(f"Encountered {len(result.errors)} errors:")
        for err in result.errors:
            print(f"  - {err.path.name}: [{err.stage}] {err.exception}")
    return registry


def main() -> None:
    registry = build_registry()
    for cmd in (
        "calc add 2 3",
        "calc multiply 4 5",
        "user whoami",
        'user greet "Bob"',
        "ping",
    ):
        print(f"\n$ {cmd}")
        print(json.dumps(execute_value(registry, cmd), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
