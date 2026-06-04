"""Property-based fuzz tests and side-effect detection for agenticli.

This file drives the public surface with randomized inputs and asserts
invariants that the library must always satisfy:

* Idempotency — calling the same public function twice with the same
  input produces the same output.
* No mutation — passing an object to a public function does not change
  the caller's view of that object.
* State isolation — operations on one registry do not affect another.
* Re-registration safety — unregister→register leaves no stale state.
* No uncaught exceptions — fuzz inputs that don't form a valid command
  still return a structured ``ExecutionResult`` or ``ParseResult``
  rather than raising out of the registry.

These properties are checked across many random seeds to give the test
suite a fighting chance of catching subtle regressions.
"""

from __future__ import annotations

import asyncio
import gc
import json
import random
import string
import sys
import threading
import weakref
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

import pytest

from agenticli import (
    ArgSpec,
    CliCommand,
    CommandError,
    CommandRegistry,
    CommandSpec,
    ExecutionCallbacks,
    ExecutionContext,
    ExecutionResult,
    Option,
    ParseResult,
    command,
    command_from_method,
    command_from_model,
    command_group,
)


# Deterministic randomness so failures are reproducible.
random.seed(0x5EED)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


SAFE_CHARS = string.ascii_letters + string.digits + "-_."


def random_word(min_len: int = 1, max_len: int = 8) -> str:
    n = random.randint(min_len, max_len)
    return "".join(random.choice(SAFE_CHARS) for _ in range(n))


def random_words(n: int, min_len: int = 1, max_len: int = 6) -> list[str]:
    return [random_word(min_len, max_len) for _ in range(n)]


def _make_unique_names(n: int, prefix: str = "fuzz") -> list[str]:
    """Generate n unique names, guaranteed not to collide."""
    seen: set[str] = set()
    out: list[str] = []
    while len(out) < n:
        candidate = f"{prefix}_{random_word(3, 6)}"
        if candidate not in seen:
            seen.add(candidate)
            out.append(candidate)
    return out


# ---------------------------------------------------------------------------
# Idempotency properties
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(10))
def test_execute_is_idempotent_within_a_registry(seed):
    """The same command string should produce the same result on every
    call. We register a single deterministic command and re-execute
    many random commands derived from it."""
    rng = random.Random(seed)
    registry = CommandRegistry()

    @command(name="fuzz_idem")
    def fuzz_idem(value: Annotated[int, Option(positional=True)]) -> int:
        return value * 2

    registry.register(fuzz_idem)
    for _ in range(50):
        v = rng.randint(-1000, 1000)
        r1 = registry.execute(f"fuzz_idem {v}")
        r2 = registry.execute(f"fuzz_idem {v}")
        assert r1.ok == r2.ok
        assert r1.value == r2.value
        assert r1.command == r2.command


@pytest.mark.parametrize("seed", range(5))
def test_parse_is_idempotent(seed):
    """Parsing the same string twice produces equivalent ParseResults."""
    rng = random.Random(seed)
    registry = CommandRegistry()

    @command(name="fuzz_p")
    def fuzz_p(
        a: Annotated[int, Option(positional=True)],
        b: Annotated[int, Option(short="b")] = 0,
    ) -> int:
        return a + b

    registry.register(fuzz_p)
    for _ in range(30):
        a = rng.randint(0, 100)
        b = rng.randint(0, 100)
        cmd = f"fuzz_p {a} -b {b}"
        r1 = registry.parse(cmd)
        r2 = registry.parse(cmd)
        assert r1 is not None and r2 is not None
        assert r1.command == r2.command
        assert r1.args == r2.args
        assert r1.errors == r2.errors


# ---------------------------------------------------------------------------
# No-mutation properties
# ---------------------------------------------------------------------------


def test_register_does_not_mutate_input_function():
    """Registering a decorated function does not mutate its spec."""

    @command(name="mut1")
    def mut1(value: Annotated[str, Option(positional=True)]) -> str:
        return value

    spec_before = mut1.__command_spec__
    snapshot = (
        spec_before.name,
        spec_before.description,
        tuple(spec_before.aliases),
        spec_before.hidden,
        spec_before.deprecated,
        spec_before.include_in_prompt,
    )
    registry = CommandRegistry()
    registry.register(mut1)
    spec_after = mut1.__command_spec__
    assert spec_after is spec_before
    assert (
        spec_after.name,
        spec_after.description,
        tuple(spec_after.aliases),
        spec_after.hidden,
        spec_after.deprecated,
        spec_after.include_in_prompt,
    ) == snapshot


def test_execute_does_not_mutate_registry_commands_list():
    """``registry.commands`` returns a fresh list each call; mutating it
    does not affect future calls."""

    @command(name="m1")
    def m1() -> str:
        return "1"

    @command(name="m2")
    def m2() -> str:
        return "2"

    registry = CommandRegistry()
    registry.register(m1)
    registry.register(m2)
    cmds1 = registry.commands
    cmds1.append("__bogus__")  # caller-side mutation
    cmds2 = registry.commands
    assert "__bogus__" not in cmds2
    assert "m1" in cmds2 and "m2" in cmds2


def test_execute_does_not_mutate_user_args_dict():
    """A fuzzed call to ``registry.execute`` does not mutate any object
    the user passed via the command's logic path."""
    seen_payloads: list[Any] = []

    @command(name="capture")
    def capture(payload: Annotated[str, Option(positional=True)]) -> str:
        seen_payloads.append(payload)
        return payload

    registry = CommandRegistry()
    registry.register(capture)
    # Use only inputs that round-trip cleanly through shlex.
    inputs = ["abc", "with space", "normal-text", "another"]
    for s in inputs:
        r = registry.execute(f"capture {s!r}" if " " in s else f"capture {s}")
        # Some inputs may fail to parse (e.g. embedded quote); that's
        # not a mutation issue, but we only assert non-mutation on the
        # ones the handler actually saw.
        if r.ok:
            assert r.value == s
    # All values the handler saw are exactly the strings we passed.
    for s, seen in zip(inputs, seen_payloads):
        assert seen == s


def test_to_dict_does_not_mutate_injections_dict():
    """The to_dict path filters unsafe injection values; it must not
    mutate the spec's injections dict in place."""
    unsafe = object()
    safe = {"a": 1, "b": "two", "c": [1, 2], "d": None}

    def my_func(**kwargs):
        return kwargs

    spec = CommandSpec(
        name="tm",
        description="d",
        func=my_func,
        injections={"safe": safe, "unsafe": unsafe},
    )
    original_injections = dict(spec.injections)
    spec.to_dict()
    # The spec's injections dict is unchanged (both safe and unsafe present).
    assert spec.injections == original_injections
    assert "safe" in spec.injections
    assert "unsafe" in spec.injections


# ---------------------------------------------------------------------------
# State isolation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(5))
def test_two_registries_do_not_share_state(seed):
    """Operations on registry A do not affect registry B."""
    rng = random.Random(seed)
    n = rng.randint(1, 20)
    names = _make_unique_names(n)

    reg_a = CommandRegistry()
    reg_b = CommandRegistry()
    for i, name in enumerate(names):
        if i % 2 == 0:
            reg_a.register(_make_echo(name))
        else:
            reg_b.register(_make_echo(name))

    a_cmds = set(reg_a.commands)
    b_cmds = set(reg_b.commands)
    assert a_cmds.isdisjoint(b_cmds), f"shared: {a_cmds & b_cmds}"
    assert len(a_cmds) == (n + 1) // 2
    assert len(b_cmds) == n // 2


def _make_echo(name: str):
    """Build a fresh @command-decorated function with a unique name."""
    def echo(value: Annotated[str, Option(positional=True)]) -> str:
        return value
    echo.__name__ = name
    return command(name=name)(echo)


def test_unregister_then_register_yields_clean_state():
    """After unregister+register, no stale entry should remain."""
    @command(name="swap")
    def swap() -> str:
        return "1"

    @command(name="swap")
    def swap2() -> str:
        return "2"

    registry = CommandRegistry()
    registry.register(swap)
    registry.unregister("swap")
    registry.register(swap2)
    assert registry.execute("swap").value == "2"
    # No leftover alias or duplicate — only one entry for "swap".
    spec = registry.get("swap")
    assert spec is swap2.__command_spec__


# ---------------------------------------------------------------------------
# No uncaught exceptions: fuzz random command strings
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(20))
def test_random_command_strings_never_raise_out_of_execute(seed):
    """``registry.execute`` must always return an ExecutionResult —
    it must never raise. We fuzz 50 random strings per seed."""
    rng = random.Random(seed)
    registry = CommandRegistry()

    @command(name="fuzz_e")
    def fuzz_e(value: Annotated[str, Option(positional=True)]) -> str:
        return value

    registry.register(fuzz_e)

    for _ in range(50):
        n_words = rng.randint(0, 6)
        words = [rng.choice(["fuzz_e", "echo", "ls", "cat", "calc", "frob", ""])]
        for _ in range(n_words):
            words.append(rng.choice([
                random_word(0, 8),
                "--" + random_word(0, 6),
                "-" + random.choice(string.ascii_lowercase),
                str(rng.randint(-100, 100)),
                "&&", "||", ";",
            ]))
        cmd_str = " ".join(w for w in words if w is not None)
        # Execute must not raise.
        r = registry.execute(cmd_str)
        assert isinstance(r, ExecutionResult), f"got {type(r).__name__} for {cmd_str!r}"


@pytest.mark.parametrize("seed", range(10))
def test_random_command_strings_never_raise_out_of_parse(seed):
    """``registry.parse`` must always return None or a ParseResult."""
    rng = random.Random(seed)
    registry = CommandRegistry()

    @command(name="fuzz_p")
    def fuzz_p(value: Annotated[str, Option(positional=True)]) -> str:
        return value

    registry.register(fuzz_p)

    for _ in range(30):
        n = rng.randint(0, 5)
        words = [rng.choice(["fuzz_p", "ls", "echo", "weird"])]
        for _ in range(n):
            words.append(random_word(0, 6))
        cmd_str = " ".join(words)
        # Parse must not raise.
        r = registry.parse(cmd_str)
        assert r is None or isinstance(r, ParseResult)


# ---------------------------------------------------------------------------
# Round-trip stability
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(10))
def test_to_dict_from_dict_round_trip_stable(seed):
    """Round-tripping a spec through to_dict/from_dict preserves all
    public fields across many random shapes."""
    rng = random.Random(seed)

    for _ in range(20):
        n_args = rng.randint(0, 4)
        args = []
        for i in range(n_args):
            args.append(ArgSpec(
                name=f"a{i}",
                type=rng.choice([str, int, float, bool]),
                default=rng.choice([None, 0, "", False]),
                required=rng.random() < 0.3,
                description=random_word(0, 12),
                short=random.choice([None, "x", "y"]),
                is_flag=rng.random() < 0.3,
                positional=rng.random() < 0.5,
                hidden=rng.random() < 0.1,
            ))
        n_aliases = rng.randint(0, 3)
        aliases = [random_word(2, 5) for _ in range(n_aliases)]

        def my_func(**kw):
            return kw

        spec = CommandSpec(
            name=random_word(2, 8),
            description=random_word(0, 20),
            func=my_func,
            args=args,
            usage="usage",
            aliases=aliases,
            parent=None,
            source=random.choice(["function", "class", "model", "method"]),
            hidden=rng.random() < 0.2,
            deprecated=None if rng.random() < 0.5 else "old",
            include_in_prompt=rng.random() < 0.8,
        )
        data = spec.to_dict()
        rebuilt = CommandSpec.from_dict(data)
        assert rebuilt.name == spec.name
        assert rebuilt.description == spec.description
        assert rebuilt.usage == spec.usage
        assert rebuilt.aliases == spec.aliases
        assert rebuilt.parent == spec.parent
        assert rebuilt.source == spec.source
        assert rebuilt.hidden == spec.hidden
        assert rebuilt.deprecated == spec.deprecated
        assert rebuilt.include_in_prompt == spec.include_in_prompt
        # Args preserved (modulo JSON-safe type string vs Python type).
        assert len(rebuilt.args) == len(spec.args)
        for orig_arg, new_arg in zip(spec.args, rebuilt.args):
            assert orig_arg.name == new_arg.name
            assert orig_arg.required == new_arg.required
            assert orig_arg.hidden == new_arg.hidden


# ---------------------------------------------------------------------------
# Registry-level state properties
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(5))
def test_registry_registers_unique_names_only(seed):
    """Two commands with the same name → second register raises."""
    rng = random.Random(seed)
    name = "uniq"
    registry = CommandRegistry()

    @command(name=name)
    def a() -> str:
        return "1"

    @command(name=name)
    def b() -> str:
        return "2"

    registry.register(a)
    with pytest.raises(ValueError):
        registry.register(b)
    # The first one is still in the registry.
    assert registry.execute(name).value == "1"


@pytest.mark.parametrize("seed", range(5))
def test_registry_registers_unique_aliases_only(seed):
    rng = random.Random(seed)
    alias = f"alias_{random_word(2, 4)}"

    @command(name=f"n1_{random_word(2, 4)}", aliases=[alias])
    def a() -> str:
        return "1"

    @command(name=f"n2_{random_word(2, 4)}", aliases=[alias])
    def b() -> str:
        return "2"

    registry = CommandRegistry()
    registry.register(a)
    with pytest.raises(ValueError):
        registry.register(b)


def test_repeated_unregister_is_idempotent():
    """unregister() of the same name multiple times is a no-op."""
    @command(name="repu")
    def repu() -> str:
        return "1"

    registry = CommandRegistry()
    registry.register(repu)
    for _ in range(5):
        registry.unregister("repu")
    # No exception raised; subsequent unregister on absent name also fine.
    registry.unregister("repu")
    assert not registry.has("repu")


def test_repeated_register_replace_keeps_no_orphans():
    """unregister then re-register the same name → only one entry."""
    @command(name="rep2")
    def a() -> str:
        return "1"

    registry = CommandRegistry()
    registry.register(a)
    registry.unregister("rep2")
    registry.register(a)
    # Both the canonical and any aliases map to the same spec.
    spec = registry.get("rep2")
    assert spec is a.__command_spec__
    # And the internal map has exactly one visible entry.
    visible = [n for n in registry._commands if not n.startswith("--")]
    assert visible.count("rep2") == 1


# ---------------------------------------------------------------------------
# Concurrency-side-effect properties
# ---------------------------------------------------------------------------


def test_parallel_register_does_not_lose_commands():
    """Many threads registering distinct commands → all are visible."""
    n = 50
    names = _make_unique_names(n, prefix="par")
    registry = CommandRegistry()
    lock = threading.Lock()

    def worker(name: str):
        cmd = _make_echo(name)
        with lock:
            registry.register(cmd)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(worker, names))

    # All n commands are visible.
    for name in names:
        assert registry.has(name), f"missing: {name}"


def test_parallel_execute_does_not_corrupt_shared_counter():
    """Many threads increment a shared counter via a stateful command.
    No increments are lost (the caller locks; we verify the executor
    doesn't introduce additional races)."""
    state = {"v": 0, "lock": threading.Lock()}

    @command_group(register_as_command=False)
    class Counter:
        @command(name="inc")
        def inc(self) -> int:
            with state["lock"]:
                state["v"] += 1
            return state["v"]

    instance = Counter()
    registry = CommandRegistry()
    registry.register(instance)
    N = 200
    with ThreadPoolExecutor(max_workers=16) as pool:
        futs = [pool.submit(registry.execute, "inc") for _ in range(N)]
        for f in futs:
            assert f.result().ok
    assert state["v"] == N


# ---------------------------------------------------------------------------
# Memory / GC properties
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(5))
def test_repeated_register_unregister_cycles_do_not_leak(seed):
    """A cycle of register→execute→unregister should leave no spec
    lingering in the registry after each cycle."""
    rng = random.Random(seed)
    n_cycles = 30
    registry = CommandRegistry()

    def make_cmd(name: str):
        @command(name=name)
        def cmd() -> str:
            return name
        return cmd

    refs = []
    for i in range(n_cycles):
        name = f"cycle_{i}_{random_word(2, 4)}"
        cmd = make_cmd(name)
        inner = cmd.__wrapped__
        ref = weakref.ref(inner)
        refs.append(ref)
        registry.register(cmd)
        assert registry.execute(name).value == name
        registry.unregister(name)
        del cmd
        del inner
        gc.collect()
    # After all cycles, all inner funcs are collectable.
    gc.collect()
    live = [r for r in refs if r() is not None]
    assert live == [], f"leaked {len(live)} commands across cycles"


def test_registry_drop_releases_all_specs():
    """Dropping the registry releases every spec/func it held."""
    n = 20
    names = _make_unique_names(n, prefix="drop")
    registry = CommandRegistry()
    refs: list[weakref.ref] = []

    def _register_one(name: str) -> None:
        cmd = _make_echo(name)
        refs.append(weakref.ref(cmd.__wrapped__))
        registry.register(cmd)
        # Drop the local strong reference so the wrapper becomes eligible
        # for collection as soon as the registry releases it.

    for name in names:
        _register_one(name)
    # All are alive while the registry exists.
    assert all(r() is not None for r in refs)
    del registry
    # Force collection to release any references held by the spec.
    gc.collect()
    leaked = [r for r in refs if r() is not None]
    assert leaked == [], f"registry leaked {len(leaked)} command functions"


# ---------------------------------------------------------------------------
# Cross-builder equivalence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(5))
def test_all_three_builders_produce_equivalent_runtime_behavior(seed):
    """The three builder paths (@command, command_from_method,
    command_from_model) all accept the same input and produce the same
    output for a randomly-generated signature."""
    rng = random.Random(seed)
    a_val = rng.randint(0, 100)
    b_val = rng.randint(0, 100)
    expected = a_val + b_val

    @command(name="eq_add")
    def via_dec(
        a: Annotated[int, Option(positional=True)],
        b: Annotated[int, Option(positional=True)],
    ) -> int:
        return a + b

    class Calc:
        def add(self, a: int, b: int) -> int:
            return a + b

    @dataclass
    class AddArgs:
        a: Annotated[int, Option(positional=True)]
        b: Annotated[int, Option(positional=True)]

    def add_handler(a: int, b: int) -> int:
        return a + b

    spec_method = command_from_method("m_add", Calc(), "add")
    spec_model = command_from_model("ml_add", AddArgs, add_handler)

    for builder_spec in (via_dec.__command_spec__, spec_method, spec_model):
        registry = CommandRegistry()
        registry.register_spec(builder_spec)
        # Use a name that the spec carries.
        r = registry.execute(f"{builder_spec.name} {a_val} {b_val}")
        assert r.ok, r.error
        assert r.value == expected, f"{builder_spec.name} returned {r.value}"


# ---------------------------------------------------------------------------
# Random namespace/group interactions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(5))
def test_random_namespace_groups_do_not_collide(seed):
    rng = random.Random(seed)
    n_classes = rng.randint(1, 5)
    n_methods_per = rng.randint(1, 4)

    registry = CommandRegistry()
    all_method_names: set[str] = set()
    for c in range(n_classes):
        # Dynamically build a unique @command_group class.
        method_names = []
        for m in range(n_methods_per):
            name = f"c{c}_m{m}_{random_word(2, 4)}"
            while name in all_method_names:
                name = f"c{c}_m{m}_{random_word(2, 4)}"
            all_method_names.add(name)
            method_names.append(name)

        ns = type(
            f"Ns{random_word(2, 4)}",
            (),
            {"__annotations__": {}},
        )
        ns = command_group(register_as_command=False)(ns)
        for name in method_names:
            setattr(ns, name, _make_method_command(name))
        registry.register(ns())

    # All methods are registered at top level.
    for n in all_method_names:
        assert registry.has(n), f"missing: {n}"


def _make_method_command(name: str):
    @command(name=name)
    def m() -> str:
        return name
    return m


# ---------------------------------------------------------------------------
# Random discover round-trips
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(5))
def test_random_discover_round_trip_isolated(seed, tmp_path, monkeypatch):
    rng = random.Random(seed)
    n = rng.randint(1, 5)
    registry = CommandRegistry()
    # Build a valid Python package name (letters/digits/underscore, leading letter).
    pkg_suffix = "".join(rng.choice(string.ascii_letters + string.digits) for _ in range(rng.randint(3, 6)))
    pkg_name = f"fuzzpkg_{pkg_suffix}"
    pkg = tmp_path / pkg_name
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    file_names: list[str] = []
    for i in range(n):
        # Each file name must be a valid Python module identifier.
        file_suffix = "".join(rng.choice(string.ascii_letters + string.digits) for _ in range(rng.randint(3, 6)))
        file_name = f"d{i}_{file_suffix}"
        file_names.append(file_name)
        (pkg / f"{file_name}.py").write_text(
            f"from agenticli import command, command_group\n"
            f"@command_group(register_as_command=False)\n"
            f"class G:\n"
            f"    @command(name='{file_name}')\n"
            f"    def x(self): return 'x'\n"
        )
    monkeypatch.syspath_prepend(str(tmp_path))
    result = registry.discover(pkg, package=pkg_name, on_error="raise")
    assert len(result.errors) == 0, result.errors
    for file_name in file_names:
        assert file_name in result.registered, result.registered


# ---------------------------------------------------------------------------
# Random long-input stress: parser must not hang
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(5))
def test_parser_handles_long_random_input_quickly(seed):
    """A very long command string with many random tokens must parse
    in a reasonable time and not raise. Result may be a parse error
    because the fuzz words include unknown options — that's fine, the
    property is "no uncaught exception + reasonable time"."""
    rng = random.Random(seed)
    registry = CommandRegistry()

    @command(name="longp")
    def longp() -> str:
        return "x"

    registry.register(longp)
    words = ["longp"] + [random_word(0, 6) for _ in range(2000)]
    cmd_str = " ".join(words)
    import time
    start = time.monotonic()
    r = registry.execute(cmd_str)
    elapsed = time.monotonic() - start
    # No uncaught exception; result is a structured ExecutionResult.
    assert isinstance(r, ExecutionResult)
    # Reasonable upper bound — generous for slow CI.
    assert elapsed < 5.0, f"parse took {elapsed:.2f}s on 2000-word input"
