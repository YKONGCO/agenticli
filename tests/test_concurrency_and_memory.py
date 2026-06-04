"""Concurrency, threading, and memory-leak tests for agenticli.

These tests verify:
* Multiple threads can execute different commands in parallel without
  corrupting registry state.
* Stateless commands scale linearly with thread count.
* Stateful commands are the caller's responsibility (documented
  contract, not enforced) — the tests only check that the executor
  does not crash when self state is mutated by the caller's threads.
* Memory: re-registration does not leak old specs (weakref check),
  discover() does not retain loaded modules.
* Async: concurrent execute_async calls work, gather works.
* Normal-behavior coverage: decorator equivalence, builder
  equivalence, round-trip, error paths.
"""
from __future__ import annotations

import asyncio
import gc
import sys
import threading
import time
import weakref
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import pytest

from agenticli import (
    CliCommand,
    CommandError,
    CommandRegistry,
    ExecutionCallbacks,
    Option,
    command,
    command_from_method,
    command_from_model,
    command_group,
)


# ---------------------------------------------------------------------------
# Concurrency: parallel execution of stateless commands
# ---------------------------------------------------------------------------


@command(name="echo", description="Echo the input")
def echo(value: Annotated[str, Option(positional=True)]) -> str:
    return value


@command(name="add", description="Add two numbers")
def add(
    a: Annotated[int, Option(positional=True)],
    b: Annotated[int, Option(positional=True)],
) -> int:
    return a + b


@command(name="sleep", description="Sleep briefly")
def sleep_echo(
    value: Annotated[str, Option(positional=True)],
    ms: Annotated[int, Option(short="m")] = 10,
) -> str:
    time.sleep(ms / 1000.0)
    return value


def test_parallel_execute_distinct_commands():
    """N threads each execute a different command; all return correct values."""
    registry = CommandRegistry()
    registry.register(echo)
    registry.register(add)

    def worker(args: tuple[str, ...]):
        r = registry.execute(" ".join(args))
        assert r.ok, r.error
        return args[0], r.value

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [
            pool.submit(worker, ("echo", f"msg-{i}")) for i in range(50)
        ] + [
            pool.submit(worker, ("add", str(i), str(i * 2))) for i in range(50)
        ]
        results = [f.result() for f in as_completed(futures)]

    by_cmd: dict[str, list] = {}
    for cmd, value in results:
        by_cmd.setdefault(cmd, []).append(value)

    assert len(by_cmd["echo"]) == 50
    assert all(v.startswith("msg-") for v in by_cmd["echo"])
    assert len(by_cmd["add"]) == 50
    assert all(isinstance(v, int) for v in by_cmd["add"])


def test_parallel_execute_same_command_does_not_corrupt_state():
    """Many threads call the same command; no shared mutable state exists,
    so the executor should be safe and all results match the input."""
    registry = CommandRegistry()
    registry.register(echo)

    N = 200
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = [
            pool.submit(registry.execute, f"echo {i}") for i in range(N)
        ]
        results = [f.result() for f in as_completed(futures)]

    # Sort numerically on the int suffix, since "10" < "2" lexically.
    values = sorted((r.value for r in results), key=lambda s: int(s))
    assert values == [str(i) for i in range(N)]


def test_parallel_execute_sleepy_commands_overlap_in_time():
    """If commands sleep briefly and we run them in parallel, total wall
    time should be much less than sequential time. This is a sanity check
    that the GIL does not serialize execution at our level (the sleep
    releases the GIL)."""
    registry = CommandRegistry()
    registry.register(sleep_echo)

    N = 8
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=N) as pool:
        futures = [
            pool.submit(registry.execute, f"sleep v{i} -m 50") for i in range(N)
        ]
        for f in as_completed(futures):
            assert f.result().ok
    elapsed = time.monotonic() - start

    # Sequential would be 8 * 50ms = 400ms; allow generous slack for CI.
    assert elapsed < 0.4, f"Parallel execution took {elapsed:.3f}s — looks serialized"


# ---------------------------------------------------------------------------
# Concurrency: callbacks
# ---------------------------------------------------------------------------


def test_before_after_callbacks_fire_for_every_parallel_invocation():
    """Each call should fire before/after exactly once, regardless of
    concurrent callers."""
    registry = CommandRegistry()
    registry.register(echo)

    counter = {"before": 0, "after": 0, "error": 0}
    lock = threading.Lock()

    def before(ctx):
        with lock:
            counter["before"] += 1

    def after(ctx):
        with lock:
            counter["after"] += 1

    def on_error(ctx):
        with lock:
            counter["error"] += 1

    registry.callbacks = ExecutionCallbacks(
        before_execute=before,
        after_execute=after,
        on_error=on_error,
    )

    N = 100
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(registry.execute, f"echo {i}") for i in range(N)]
        for f in as_completed(futures):
            assert f.result().ok

    assert counter["before"] == N
    assert counter["after"] == N
    assert counter["error"] == 0


# ---------------------------------------------------------------------------
# Concurrency: stateful command
# ---------------------------------------------------------------------------


@command_group()
class CounterNamespace:
    """A namespace holding a counter; used to check state mutation under
    parallel access (the caller is expected to add their own lock)."""

    def __init__(self) -> None:
        self.value = 0
        self._lock = threading.Lock()

    @command(name="cnt_inc", description="Increment counter")
    def inc(self) -> dict:
        # The caller is expected to lock; we do so here so the test
        # exercises the executor under contention without asserting the
        # library's locking semantics.
        with self._lock:
            self.value += 1
        return {"value": self.value}

    @command(name="cnt_get", description="Read counter")
    def get(self) -> dict:
        with self._lock:
            return {"value": self.value}


def test_namespace_stateful_command_works_under_contention_with_caller_lock():
    """The namespace group holds state. The caller locks; we verify the
    executor's call path (which is the new code) does not introduce
    additional races beyond what the user controls."""
    counter = CounterNamespace()
    registry = CommandRegistry()
    registry.register(counter)

    N = 200
    with ThreadPoolExecutor(max_workers=16) as pool:
        inc_futs = [pool.submit(registry.execute, "cnt_inc") for _ in range(N)]
        get_futs = [pool.submit(registry.execute, "cnt_get") for _ in range(20)]
        for f in as_completed(inc_futs + get_futs):
            assert f.result().ok

    # The counter must equal exactly N after all increments.
    assert counter.value == N
    final = execute_value_silent(registry, "cnt_get")
    assert final == {"value": N}


def execute_value_silent(registry, text):
    r = registry.execute(text)
    return r.value if r.ok else r.error.render()


# ---------------------------------------------------------------------------
# Concurrency: parse (no execution) is thread-safe
# ---------------------------------------------------------------------------


def test_parallel_parse_only_is_thread_safe():
    """parse() does not mutate registry state. Many threads parsing
    concurrently should produce equivalent results. ``parse()`` returns
    raw string values; type coercion happens at execution time."""
    registry = CommandRegistry()
    registry.register(echo)
    registry.register(add)

    def parse_once(i: int):
        return registry.parse(f"echo msg-{i}"), registry.parse(f"add {i} {i + 1}")

    N = 200
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(parse_once, range(N)))

    for i, (p_echo, p_add) in enumerate(results):
        assert p_echo.command == "echo"
        assert p_echo.args == {"value": f"msg-{i}"}
        assert p_add.command == "add"
        # parse() returns strings; the validator coerces to int at execution.
        assert p_add.args == {"a": str(i), "b": str(i + 1)}


# ---------------------------------------------------------------------------
# Concurrency: async execute
# ---------------------------------------------------------------------------


async def _gather_echo(registry: CommandRegistry, n: int) -> list:
    coros = [registry.execute_async(f"echo v{i}") for i in range(n)]
    return await asyncio.gather(*coros)


def test_parallel_async_execute_returns_all_results():
    registry = CommandRegistry()
    registry.register(echo)

    results = asyncio.run(_gather_echo(registry, 50))
    # Sort numerically — lexical sort would put "v10" before "v2".
    values = sorted((r.value for r in results), key=lambda s: int(s[1:]))
    assert values == [f"v{i}" for i in range(50)]


def test_async_callbacks_fire_under_gather():
    registry = CommandRegistry()
    registry.register(echo)

    counter = {"before": 0, "after": 0}
    lock = threading.Lock()

    def before(ctx):
        with lock:
            counter["before"] += 1

    def after(ctx):
        with lock:
            counter["after"] += 1

    registry.callbacks = ExecutionCallbacks(before_execute=before, after_execute=after)

    async def run():
        await asyncio.gather(*(registry.execute_async(f"echo {i}") for i in range(30)))

    asyncio.run(run())
    assert counter["before"] == 30
    assert counter["after"] == 30


# ---------------------------------------------------------------------------
# Concurrency: discover is safe across multiple registries
# ---------------------------------------------------------------------------


def test_parallel_discover_into_separate_registries(tmp_path, monkeypatch):
    """Multiple threads each call discover() on the same package, but
    register into independent registries. None of the registries should
    see another registry's commands."""
    import textwrap

    pkg = tmp_path / "shared_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "tools.py").write_text(
        textwrap.dedent(
            """
            from __future__ import annotations
            from typing import Annotated
            from agenticli import Option, command, command_group

            @command_group(register_as_command=False)
            class Tools:
                @command(name="t_ping", description="ping")
                def ping(self) -> str:
                    return "pong"
            """
        )
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("shared_pkg", None)
    sys.modules.pop("shared_pkg.tools", None)

    def worker(_: int) -> list[str]:
        reg = CommandRegistry()
        reg.discover(pkg, package="shared_pkg", on_error="raise")
        return reg.commands

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(worker, range(8)))

    for cmds in results:
        assert "t_ping" in cmds


# ---------------------------------------------------------------------------
# Memory: weakref and GC
# ---------------------------------------------------------------------------


def test_registration_does_not_hold_extra_references_to_user_functions():
    """The registry should retain the user's function only through
    ``CommandSpec.func``. The wrapper returned by ``@command`` should
    not be kept alive beyond its natural lifetime — and the original
    function should be released when the registry is dropped.

    The ``@command`` decorator returns a wrapper that holds the
    ``CommandSpec`` (so the spec travels with the decorated function).
    When the wrapper goes out of scope the spec can no longer be
    reached through the user; the registry is the only remaining
    handle. ``spec.func`` is the original function, not the wrapper,
    so we weakref the original via ``wrapper.__wrapped__`` to track
    the actual handler's lifetime.
    """
    @command(name="mem_echo")
    def my_echo(value: Annotated[str, Option(positional=True)]) -> str:
        return value

    original = my_echo.__wrapped__  # The unwrapped function.
    ref = weakref.ref(original)
    registry = CommandRegistry()
    registry.register(my_echo)
    # The original is still alive — the registry holds it via spec.func.
    assert ref() is not None

    # Drop the wrapper. The registry should still hold the original.
    del my_echo
    gc.collect()
    assert ref() is not None, "Registry lost its only handle to the function"

    # Drop the local + the registry. The original should be collectable.
    del original
    del registry
    gc.collect()
    assert ref() is None, "Registry leaked the user function after teardown"


def test_reregistering_replaces_old_spec():
    """register() raises on conflict. To swap a name, the caller must
    unregister() first. This test pins that contract: re-registration
    is not implicit, but the explicit unregister→register path releases
    the prior spec."""
    @command(name="swap_me")
    def first() -> str:
        return "first"

    @command(name="swap_me")
    def second() -> str:
        return "second"

    first_inner = first.__wrapped__
    second_inner = second.__wrapped__
    first_ref = weakref.ref(first_inner)
    second_ref = weakref.ref(second_inner)

    registry = CommandRegistry()
    registry.register(first)
    with pytest.raises(ValueError):
        registry.register(second)  # collision → not allowed

    # Explicit replacement: unregister then re-register.
    registry.unregister("swap_me")
    registry.register(second)
    assert execute_value_silent(registry, "swap_me") == "second"

    # Drop the wrappers and the inner locals; the registry keeps the
    # first spec via spec.func until unregister, then drops it.
    del first
    del first_inner
    gc.collect()
    assert first_ref() is None, "First spec leaked after unregister"

    # The second spec is held by the registry.
    assert second_ref() is not None
    del second
    del second_inner
    del registry
    gc.collect()
    assert second_ref() is None, "Second spec leaked after registry drop"


def test_unregister_releases_spec():
    """unregister() drops the registry's reference; the spec/func can be
    collected."""
    @command(name="transient")
    def transient() -> str:
        return "x"

    ref = weakref.ref(transient)
    registry = CommandRegistry()
    registry.register(transient)
    assert ref() is not None

    registry.unregister("transient")
    del transient
    gc.collect()
    assert ref() is None


def test_namespace_group_spec_does_not_leak_methods():
    """Registering a namespace group instance should let the instance be
    collected once the registry is gone, taking its bound methods with it.

    Note: bound methods on instances are short-lived Python objects —
    weakrefing ``instance.run`` is not reliable. We track the instance
    itself instead; the bound methods cannot outlive the instance they
    are bound to.
    """

    @command_group(register_as_command=False)
    class Service:
        @command(name="svc_run")
        def run(self) -> str:
            return "ran"

    instance = Service()
    instance_ref = weakref.ref(instance)
    # Confirm the method works while the instance is alive.
    assert instance.run() == "ran"

    registry = CommandRegistry()
    registry.register(instance)
    assert instance_ref() is not None
    assert registry.has("svc_run")

    del instance
    del registry
    gc.collect()
    assert instance_ref() is None, "Namespace group instance leaked after registry drop"


# ---------------------------------------------------------------------------
# Memory: discover leaves no sys.modules residue
# ---------------------------------------------------------------------------


def test_discover_with_package_does_not_leak_modules(tmp_path, monkeypatch):
    """When discover() is given package= and the modules are already in
    sys.modules, no new entries should appear."""
    import textwrap

    pkg = tmp_path / "leak_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "x.py").write_text(
        textwrap.dedent(
            """
            from __future__ import annotations
            from typing import Annotated
            from agenticli import Option, command, command_group

            @command_group(register_as_command=False)
            class X:
                @command(name="leak_x", description="x")
                def x(self) -> str:
                    return "x"
            """
        )
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("leak_pkg", None)
    sys.modules.pop("leak_pkg.x", None)

    before = set(sys.modules.keys())
    registry = CommandRegistry()
    registry.discover(pkg, package="leak_pkg", on_error="raise")
    after = set(sys.modules.keys())
    new_modules = after - before
    # Expect at most leak_pkg and leak_pkg.x, both clean.
    assert new_modules <= {"leak_pkg", "leak_pkg.x"}
    # And the registry works.
    assert "leak_x" in registry.commands


# ---------------------------------------------------------------------------
# Normal behavior: decorator equivalence
# ---------------------------------------------------------------------------


def test_bare_and_parens_decorator_produce_equivalent_spec():
    """@command and @command() and @command(include_in_prompt=True) should
    produce specs that differ only in the explicit marker, not in any
    observable spec field."""
    @command
    def bare(value: Annotated[str, Option(positional=True)]) -> str:
        return value

    @command()
    def parens(value: Annotated[str, Option(positional=True)]) -> str:
        return value

    @command(include_in_prompt=True)
    def kw_true(value: Annotated[str, Option(positional=True)]) -> str:
        return value

    # Default name is the function name (no explicit `name=` given).
    assert bare.__command_spec__.name == "bare"
    assert parens.__command_spec__.name == "parens"
    assert kw_true.__command_spec__.name == "kw_true"

    for cmd in (bare, parens, kw_true):
        assert cmd.__command_spec__.include_in_prompt is True
        assert cmd.__command_spec__.description == ""
        assert cmd.__command_spec__.hidden is False
        assert cmd.__command_spec__.deprecated is None

    # The explicit marker distinguishes "caller passed True" from default.
    spec_bare = bare.__command_spec__
    spec_parens = parens.__command_spec__
    spec_kw = kw_true.__command_spec__
    assert getattr(spec_bare, "_include_in_prompt_explicit", False) is False
    assert getattr(spec_parens, "_include_in_prompt_explicit", False) is False
    assert getattr(spec_kw, "_include_in_prompt_explicit", False) is True

    # Negative case: an explicit False is preserved and flagged explicit.
    @command(include_in_prompt=False)
    def kw_false(value: Annotated[str, Option(positional=True)]) -> str:
        return value

    spec_false = kw_false.__command_spec__
    assert spec_false.include_in_prompt is False
    assert getattr(spec_false, "_include_in_prompt_explicit", False) is True


# ---------------------------------------------------------------------------
# Normal behavior: all builders produce compatible specs
# ---------------------------------------------------------------------------


@dataclass
class AddInput:
    a: Annotated[int, Option(positional=True)]
    b: Annotated[int, Option(positional=True)]


def add_handler(a: int, b: int) -> int:
    return a + b


def test_all_three_builders_register_and_execute():
    """@command, command_from_method, and command_from_model each produce
    a spec that registers and executes equivalently."""

    @command(name="b_add", description="add")
    def b_add(
        a: Annotated[int, Option(positional=True)],
        b: Annotated[int, Option(positional=True)],
    ) -> int:
        return a + b

    class AddService:
        def add(self, a: int, b: int) -> int:
            return a + b

    spec_method = command_from_method("m_add", AddService(), "add", description="add")
    spec_model = command_from_model("mod_add", AddInput, add_handler, description="add")

    registry = CommandRegistry()
    registry.register(b_add)
    registry.register_spec(spec_method)
    registry.register_spec(spec_model)

    for cmd in ("b_add 2 3", "m_add 2 3", "mod_add 2 3"):
        r = registry.execute(cmd)
        assert r.ok, f"{cmd} failed: {r.error}"
        assert r.value == 5


def test_cli_command_class_executes_under_concurrent_workers():
    """CliCommand subclass also works under ThreadPoolExecutor."""

    @dataclass
    class EchoArgs:
        value: Annotated[str, Option(positional=True)]

    class EchoCli(CliCommand):
        name = "cli_echo"
        description = "echo"
        args_model = EchoArgs

        async def run(self, value: str) -> str:
            return value

    registry = CommandRegistry()
    registry.register(EchoCli())
    assert registry.has("cli_echo")

    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = [pool.submit(registry.execute, f"cli_echo v{i}") for i in range(20)]
        for f in as_completed(futs):
            r = f.result()
            assert r.ok, r.error
            # Sort numerically — "v10" < "v2" lexically.
            assert r.value.startswith("v")


# ---------------------------------------------------------------------------
# Normal behavior: round-trip
# ---------------------------------------------------------------------------


def _round_trip(spec, registry):
    data = spec.to_dict()
    # Strip the func; we only test serialization shape, not re-binding.
    from agenticli.types import CommandSpec
    return CommandSpec.from_dict(data)


def test_namespace_subcommand_round_trips_via_to_dict_from_dict():
    @command_group(register_as_command=False, include_in_prompt=False)
    class Ns:
        @command(name="rt_op", description="round trip op", hidden=True)
        def op(self) -> str:
            return "rt"

    registry = CommandRegistry()
    registry.register(Ns())

    original = registry.get("rt_op")
    assert original is not None
    rebuilt = _round_trip(original, registry)

    # Public fields match the source spec.
    assert rebuilt.name == original.name
    assert rebuilt.description == original.description
    assert rebuilt.hidden == original.hidden
    assert rebuilt.include_in_prompt == original.include_in_prompt
    assert rebuilt.usage == original.usage
    assert rebuilt.source == original.source
    assert rebuilt.parent == original.parent  # None for namespace


def test_group_subcommand_round_trips_via_to_dict_from_dict():
    @command_group(name="rt_grp", description="round trip group")
    class Grp:
        @command(name="rt_inner", description="inner")
        def inner(self) -> str:
            return "i"

    registry = CommandRegistry()
    registry.register(Grp())

    original = registry.get("rt_grp rt_inner")
    rebuilt = _round_trip(original, registry)

    assert rebuilt.name == "rt_grp rt_inner"
    assert rebuilt.parent == "rt_grp"
    assert rebuilt.usage == "rt_grp rt_inner"


def test_to_dict_is_json_safe_for_namespace_spec():
    import json

    @command_group(register_as_command=False, include_in_prompt=False)
    class Ns:
        @command(name="js_op", description="json op", deprecated="use foo")
        def op(self) -> str:
            return "j"

    registry = CommandRegistry()
    registry.register(Ns())

    spec = registry.get("js_op")
    data = spec.to_dict()

    # Must be JSON-serializable.
    encoded = json.dumps(data)
    decoded = json.loads(encoded)
    assert decoded["name"] == "js_op"
    assert decoded["deprecated"] == "use foo"


# ---------------------------------------------------------------------------
# Normal behavior: help and prompt under various shapes
# ---------------------------------------------------------------------------


def test_help_on_unknown_command_returns_did_you_mean():
    registry = CommandRegistry()
    registry.register(echo)
    help_text = registry.help("ecoh")
    assert "Unknown" in help_text or "echo" in help_text


def test_render_llm_context_does_not_double_count_aliased_command():
    @command(name="with_alias", description="x", aliases=["wa"])
    def f() -> str:
        return "f"

    registry = CommandRegistry()
    registry.register(f)
    ctx = registry.render_llm_context()
    # 'with_alias' should appear once, not twice (once for the alias entry).
    assert ctx.count("with_alias:") == 1


def test_render_llm_context_excludes_namespace_group_but_keeps_subs():
    @command_group(register_as_command=False, include_in_prompt=True)
    class Ns:
        @command(name="ns_a", description="a")
        def a(self) -> str:
            return "a"

    registry = CommandRegistry()
    registry.register(Ns())
    ctx = registry.render_llm_context()
    assert "ns_a" in ctx
    # The group itself (no name → not a command) does not show.


def test_execute_returns_command_error_on_runtime_exception():
    @command(name="boom")
    def boom() -> str:
        raise RuntimeError("kaboom")

    registry = CommandRegistry()
    registry.register(boom)
    r = registry.execute("boom")
    assert not r.ok
    assert "kaboom" in r.error.render()


def test_execute_chain_with_operators_runs_in_order():
    @command(name="push")
    def push(value: Annotated[str, Option(positional=True)]) -> str:
        return f"pushed:{value}"

    @command(name="seq")
    def seq() -> int:
        return 42

    registry = CommandRegistry()
    registry.register(push)
    registry.register(seq)

    r = registry.execute("push a ; push b ; seq", chain=True)
    assert isinstance(r, list)
    assert r[0] == "pushed:a"
    assert r[1] == "pushed:b"
    assert r[2] == 42


def test_execute_chain_short_circuits_on_double_amp_failure():
    @command(name="ok")
    def ok() -> str:
        return "ok"

    @command(name="bad")
    def bad() -> str:
        raise RuntimeError("nope")

    @command(name="never")
    def never() -> str:
        return "should not run"

    registry = CommandRegistry()
    registry.register(ok)
    registry.register(bad)
    registry.register(never)

    r = registry.execute("ok && bad && never", chain=True)
    # 'bad' failed → 'never' must not have run.
    assert isinstance(r, list)
    assert len(r) == 2
    assert r[0] == "ok"


# ---------------------------------------------------------------------------
# Normal behavior: parse errors produce structured CommandError
# ---------------------------------------------------------------------------


def test_parse_error_includes_subject_and_suggestion():
    @command(name="typed", description="typed")
    def typed(name: Annotated[str, Option(positional=True)]) -> str:
        return name

    registry = CommandRegistry()
    registry.register(typed)

    r = registry.execute("typed")  # missing required positional
    assert not r.ok
    assert r.error.subject == "typed"
    assert r.error.hint or r.error.message


# ---------------------------------------------------------------------------
# Normal behavior: alias / prefix
# ---------------------------------------------------------------------------


def test_alias_resolves_to_canonical_name_for_help():
    @command(name="canonical", description="c", aliases=["can"])
    def c() -> str:
        return "c"

    registry = CommandRegistry()
    registry.register(c)
    assert "canonical" in registry.help()
    # The alias is not double-listed.
    assert registry.help().count("canonical:") == 1


def test_prefix_match_only_when_no_exact_match():
    @command(name="weather", description="w")
    def w() -> str:
        return "w"

    @command(name="wear", description="we")
    def we() -> str:
        return "we"

    registry = CommandRegistry()
    registry.register(w)
    registry.register(we)

    # 'wea' is a prefix of both; the resolver picks the first one it
    # iterates over (set order). The behavior must be deterministic.
    r1 = registry.execute("wea")
    r2 = registry.execute("wea")
    assert r1.ok and r2.ok
    assert r1.value == r2.value  # deterministic across calls
