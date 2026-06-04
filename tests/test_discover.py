"""Tests for CommandRegistry.discover() and the internal agenticli.discover module."""
from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Annotated

import pytest

from agenticli import CliCommand, CommandRegistry, Option, command, command_group
from agenticli.discover import (
    DiscoverError,
    DiscoverResult,
    build_target,
    discover,
    iter_command_classes,
    iter_module_specs,
)


def execute_value(registry: CommandRegistry, command_text: str):
    result = registry.execute(command_text)
    assert not isinstance(result, list)
    return result.value if result.ok else result.error.render()


def _write(tmp_path: Path, name: str, source: str) -> Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(source).lstrip("\n"))
    return path


def test_finds_decorated_command_group(tmp_path: Path):
    _write(
        tmp_path,
        "calc.py",
        """
        from agenticli import command_group, command

        @command_group(name="calc", description="Calculator")
        class Calc:
            @command(name="add", description="Add numbers")
            def add(self, a: int, b: int) -> dict:
                return {"result": a + b}
        """,
    )
    registry = CommandRegistry()
    result = registry.discover(tmp_path)

    assert isinstance(result, DiscoverResult)
    assert result.errors == []
    assert "calc add" in registry.commands
    assert execute_value(registry, "calc add 2 3") == {"result": 5}


def test_finds_cli_command_subclass(tmp_path: Path):
    _write(
        tmp_path,
        "ping.py",
        """
        from agenticli import CliCommand

        class Ping(CliCommand):
            name = "ping"
            description = "Ping endpoint"

            async def run(self, **kwargs):
                return {"pong": True}
        """,
    )
    registry = CommandRegistry()
    result = registry.discover(tmp_path)

    assert result.errors == []
    assert "ping" in registry.commands
    assert execute_value(registry, "ping") == {"pong": True}


def test_context_provider_called_per_class(tmp_path: Path):
    _write(
        tmp_path,
        "a.py",
        """
        from agenticli import command_group, command

        @command_group(name="alpha", description="A")
        class Alpha:
            @command(name="go", description="Go")
            def go(self) -> dict:
                return {"who": "alpha"}
        """,
    )
    _write(
        tmp_path,
        "b.py",
        """
        from agenticli import CliCommand

        class Beta(CliCommand):
            name = "beta"
            description = "B"
            async def run(self, **kwargs):
                return {"who": "beta"}
        """,
    )

    called: list[type] = []

    def provider(cls):
        called.append(cls)
        return cls()

    registry = CommandRegistry()
    result = registry.discover(tmp_path, context_provider=provider)

    assert result.errors == []
    assert len(called) == 2
    assert {c.__name__ for c in called} == {"Alpha", "Beta"}
    assert "alpha go" in registry.commands
    assert "beta" in registry.commands


def test_skips_underscore_and_dunder_files(tmp_path: Path):
    _write(
        tmp_path,
        "_private.py",
        """
        from agenticli import command_group, command

        @command_group(name="private", description="Should not appear")
        class Private:
            @command(name="noop", description="noop")
            def noop(self) -> dict:
                return {}
        """,
    )
    _write(
        tmp_path,
        "__init__.py",
        """
        from agenticli import command_group, command

        @command_group(name="dunder", description="Should not appear")
        class Dunder:
            @command(name="noop", description="noop")
            def noop(self) -> dict:
                return {}
        """,
    )
    _write(
        tmp_path,
        "public.py",
        """
        from agenticli import command_group, command

        @command_group(name="public", description="Public")
        class Public:
            @command(name="hi", description="hi")
            def hi(self) -> dict:
                return {"ok": True}
        """,
    )

    registry = CommandRegistry()
    result = registry.discover(tmp_path)

    assert result.errors == []
    assert "public hi" in registry.commands
    assert "private noop" not in registry.commands
    assert "dunder noop" not in registry.commands


def test_recursive_false_stays_in_top_dir(tmp_path: Path):
    subdir = tmp_path / "sub"
    subdir.mkdir()
    _write(
        subdir,
        "hidden.py",
        """
        from agenticli import command_group, command

        @command_group(name="hidden", description="Should not appear")
        class Hidden:
            @command(name="go", description="go")
            def go(self) -> dict:
                return {}
        """,
    )
    _write(
        tmp_path,
        "visible.py",
        """
        from agenticli import command_group, command

        @command_group(name="visible", description="Public")
        class Visible:
            @command(name="go", description="go")
            def go(self) -> dict:
                return {"ok": True}
        """,
    )

    registry = CommandRegistry()
    result = registry.discover(tmp_path, recursive=False)

    assert result.errors == []
    assert "visible go" in registry.commands
    assert "hidden go" not in registry.commands


def test_import_error_collected(tmp_path: Path):
    _write(
        tmp_path,
        "broken.py",
        """
        import agenticli.this_module_definitely_does_not_exist_xyz123
        """,
    )
    _write(
        tmp_path,
        "good.py",
        """
        from agenticli import command_group, command

        @command_group(name="ok", description="OK")
        class Ok:
            @command(name="hi", description="hi")
            def hi(self) -> dict:
                return {"ok": True}
        """,
    )

    registry = CommandRegistry()
    result = registry.discover(tmp_path)

    assert "ok hi" in registry.commands
    assert len(result.errors) == 1
    err = result.errors[0]
    assert err.path.name == "broken.py"
    assert err.stage == "import"
    assert isinstance(err.exception, ImportError)


def test_reexported_class_excluded(tmp_path: Path):
    _write(
        tmp_path,
        "reexport.py",
        """
        from agenticli import CliCommand  # re-export, not defined here

        class Local(CliCommand):
            name = "local"
            description = "Local command"
            async def run(self, **kwargs):
                return {"src": "local"}
        """,
    )

    registry = CommandRegistry()
    result = registry.discover(tmp_path)

    assert result.errors == []
    assert "local" in registry.commands
    # CliCommand itself must not be registered
    assert "CliCommand" not in registry.commands
    assert "Command" not in registry.commands


def test_name_conflict_recorded_as_error(tmp_path: Path):
    _write(
        tmp_path,
        "clash.py",
        """
        from agenticli import command_group, command

        @command_group(name="clash", description="Clashing group")
        class Clash:
            @command(name="go", description="go")
            def go(self) -> dict:
                return {"src": "disk"}
        """,
    )

    registry = CommandRegistry()
    registry.register_spec(
        type("FakeSpec", (), {
            "name": "clash",
            "description": "Pre-existing",
            "func": lambda: "fake",
            "args": [],
            "usage": "clash",
            "aliases": [],
            "parent": None,
            "validator": None,
            "source": "function",
            "help_text": "",
            "hidden": False,
            "deprecated": None,
            "include_in_prompt": True,
            "injections": {},
            "injection_factories": {},
        })()
    )

    result = registry.discover(tmp_path)

    assert len(result.errors) == 1
    err = result.errors[0]
    assert err.path.name == "clash.py"
    assert err.class_name == "Clash"
    assert err.stage == "register"
    assert isinstance(err.exception, ValueError)


# ---- Internal module unit tests (sanity checks for the pure functions) ----


def test_iter_module_specs_skips_dunder_and_pycache(tmp_path: Path):
    (tmp_path / "a.py").write_text("")
    (tmp_path / "_b.py").write_text("")
    (tmp_path / "__init__.py").write_text("")
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "x.cpython-310.pyc").write_bytes(b"")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.py").write_text("")

    specs = list(iter_module_specs(tmp_path, recursive=True, package=None))
    names = sorted(p.name for p, _ in specs)
    assert names == ["a.py", "c.py"]


def test_iter_command_classes_excludes_reexports():
    import types
    fake = types.ModuleType("fake_mod")

    class LocalCmd(CliCommand):
        async def run(self, **kwargs):
            return None

    LocalCmd.__module__ = "fake_mod"
    fake.LocalCmd = LocalCmd
    fake.CliCommand = CliCommand  # re-export, __module__ is "agenticli.commands"

    found = list(iter_command_classes(fake))
    assert [c.__name__ for c in found] == ["LocalCmd"]


def test_build_target_uses_provider_when_given():
    class WithCtx:
        pass

    captured: list[type] = []

    def provider(cls):
        captured.append(cls)
        return "instance-handle"

    result = build_target(WithCtx, provider)
    assert result == "instance-handle"
    assert captured == [WithCtx]


def test_build_target_falls_back_to_class():
    class NoCtx:
        pass

    assert build_target(NoCtx, None) is NoCtx
