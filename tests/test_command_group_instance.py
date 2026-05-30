"""Tests for command group instance registration with injected context."""

from __future__ import annotations

from typing import Annotated, Literal

from agenticli import (
    CommandRegistry,
    ExecutionCallbacks,
    Option,
    State,
    command,
    command_group,
)


def execute_value(registry: CommandRegistry, command_text: str):
    result = registry.execute(command_text)
    assert not isinstance(result, list)
    return result.value if result.ok else result.error.render()


def test_register_instance_with_context():
    """Register a command group instance with bound context."""

    @command_group(name="user", description="User operations")
    class UserService:
        def __init__(self, user_id: str, tenant_id: str):
            self._user_id = user_id
            self._tenant_id = tenant_id

        @command(name="whoami", description="Show current user info")
        def whoami(self) -> dict:
            return {"user_id": self._user_id, "tenant_id": self._tenant_id}

        @command(name="greet", description="Greet user")
        def greet(self, name: Annotated[str, Option(positional=True, description="Name")]) -> dict:
            return {"message": f"Hello {name} from {self._user_id}"}

    registry = CommandRegistry()
    service = UserService(user_id="alice", tenant_id="company-x")
    registry.register(service)

    assert execute_value(registry, "user whoami") == {"user_id": "alice", "tenant_id": "company-x"}
    assert execute_value(registry, "user greet Bob") == {"message": "Hello Bob from alice"}


def test_multiple_instances_raises_conflict():
    """Registering two instances of same class raises conflict - commands already registered."""

    @command_group(name="user", description="User operations")
    class UserService:
        def __init__(self, user_id: str, tenant_id: str):
            self._user_id = user_id
            self._tenant_id = tenant_id

        @command(name="whoami", description="Show current user info")
        def whoami(self) -> dict:
            return {"user_id": self._user_id, "tenant_id": self._tenant_id}

    registry = CommandRegistry()

    alice = UserService(user_id="alice", tenant_id="company-x")
    bob = UserService(user_id="bob", tenant_id="company-y")

    registry.register(alice)

    # Second registration of same group name should raise ValueError
    try:
        registry.register(bob)
    except ValueError as exc:
        assert "command already registered: user" in str(exc)


def test_instance_help_text_shows_commands():
    """Help for instance-based command group should work."""

    @command_group(name="user", description="User operations")
    class UserService:
        def __init__(self, user_id: str):
            self._user_id = user_id

        @command(name="info", description="Show info")
        def info(self) -> dict:
            return {"user_id": self._user_id}

    registry = CommandRegistry()
    service = UserService(user_id="alice")
    registry.register(service)

    help_text = execute_value(registry, "user --help")
    assert "Subcommands:" in help_text
    assert "info:" in help_text


def test_instance_subcommand_help():
    """Help for subcommand in instance-based group should work."""

    @command_group(name="user", description="User operations")
    class UserService:
        def __init__(self, user_id: str):
            self._user_id = user_id

        @command(name="info", description="Show info")
        def info(self) -> dict:
            return {"user_id": self._user_id}

    registry = CommandRegistry()
    service = UserService(user_id="alice")
    registry.register(service)

    help_text = execute_value(registry, "user info --help")
    assert "Command: user info" in help_text


def test_instance_callback_receives_correct_context():
    """Callbacks should see instance's context in args."""

    @command_group(name="user", description="User operations")
    class UserService:
        def __init__(self, user_id: str):
            self._user_id = user_id

        @command(name="info", description="Show info")
        def info(self) -> dict:
            return {"user_id": self._user_id}

    observed_contexts = []

    def capture_context(ctx):
        observed_contexts.append({"command": ctx.command, "args": dict(ctx.args)})

    registry = CommandRegistry(callbacks=ExecutionCallbacks(before_execute=capture_context))
    service = UserService(user_id="alice")
    registry.register(service)

    execute_value(registry, "user info")

    assert observed_contexts[0]["command"] == "user info"


def test_register_non_command_group_instance_raises_error():
    """Registering a non-decorated class instance should fail."""

    @command_group(name="user", description="User operations")
    class UserService:
        def __init__(self, user_id: str):
            self._user_id = user_id

        @command(name="info", description="Show info")
        def info(self) -> dict:
            return {"user_id": self._user_id}

    class PlainService:
        def method(self):
            return "hello"

    registry = CommandRegistry()
    service = UserService(user_id="alice")
    registry.register(service)

    try:
        registry.register(PlainService())
        assert False, "Expected TypeError"
    except TypeError as exc:
        assert "Unsupported command target" in str(exc)


def test_instance_with_optional_init_args():
    """Instance with optional __init__ args should work."""

    @command_group(name="opt", description="Optional init")
    class OptionalService:
        def __init__(self, value: str = "fallback"):
            self._value = value

        @command(name="show", description="Show value")
        def show(self) -> str:
            return self._value

    registry = CommandRegistry()
    registry.register(OptionalService())

    result = registry.execute("opt show")
    assert result.ok is True
    assert result.value == "fallback"


def test_instance_command_with_various_arg_types():
    """Subcommand with various arg types in instance-based group."""

    @command_group(name="args", description="Args test")
    class ArgsService:
        def __init__(self, prefix: str):
            self._prefix = prefix

        @command(name="complex", description="Complex args")
        def complex(
            self,
            name: Annotated[str, Option(positional=True, description="name")],
            count: Annotated[int, Option(short="c", description="count")] = 1,
            flag: Annotated[bool, Option(short="f", description="flag")] = False,
            mode: Literal["a", "b"] = "a",
        ) -> dict:
            return {
                "prefix": self._prefix,
                "name": name,
                "count": count,
                "flag": flag,
                "mode": mode,
            }

    registry = CommandRegistry()
    registry.register(ArgsService(prefix="P"))

    result = execute_value(registry, "args complex test -c 5 -f --mode b")
    assert result == {
        "prefix": "P",
        "name": "test",
        "count": 5,
        "flag": True,
        "mode": "b",
    }


def test_instance_command_returns_error_on_execution_failure():
    """Command execution failure should return proper error."""

    @command_group(name="fail", description="Failing group")
    class FailService:
        def __init__(self, should_fail: bool = False):
            self._should_fail = should_fail

        @command(name="risky", description="Risky command")
        def risky(self) -> str:
            if self._should_fail:
                raise ValueError("intentional failure")
            return "success"

    registry = CommandRegistry()
    registry.register(FailService(should_fail=True))

    result = registry.execute("fail risky")
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "execution_error"
    assert "intentional failure" in result.error.message


def test_async_command_in_instance_group():
    """Async commands in instance-based group should work."""
    import asyncio

    @command_group(name="async", description="Async group")
    class AsyncService:
        def __init__(self, tag: str):
            self._tag = tag

        @command(name="ping", description="Async ping")
        async def ping(self) -> str:
            await asyncio.sleep(0)
            return f"pong:{self._tag}"

    registry = CommandRegistry()
    registry.register(AsyncService(tag="async-tag"))

    assert execute_value(registry, "async ping") == "pong:async-tag"


def test_injection_still_works_with_instance_group():
    """State injection should work with instance-based groups."""

    @command_group(name="ctx", description="Context injection test")
    class CtxService:
        def __init__(self, prefix: str):
            self._prefix = prefix

        @command(name="check", description="Check state injection")
        def check(
            self,
            state: Annotated[
                dict,
                State(factory=lambda ctx: {"cmd": ctx.command}),
            ] = None,
        ) -> dict:
            return {"prefix": self._prefix, "state": state}

    captured_states = []

    @command_group(name="ctx2", description="Context injection test 2")
    class CtxService2:
        def __init__(self, prefix: str):
            self._prefix = prefix

        @command(name="check", description="Check state injection")
        def check(
            self,
            state: Annotated[
                dict,
                State(factory=lambda ctx: {"cmd": ctx.command}),
            ] = None,
        ) -> dict:
            captured_states.append(state)
            return {"prefix": self._prefix, "state": state}

    registry = CommandRegistry()
    service = CtxService2(prefix="test")
    registry.register(service)

    execute_value(registry, "ctx2 check")

    assert len(captured_states) == 1
    assert captured_states[0]["cmd"] == "ctx2 check"
    assert execute_value(registry, "ctx2 check")["prefix"] == "test"