from __future__ import annotations

import argparse
import asyncio
import ctypes
import gc
import os
import sys
import time
import tracemalloc
from ctypes import wintypes
from pathlib import Path
from typing import Annotated

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agenticli import CommandRegistry, Option, command
from agenticli.parser import CommandParser
from agenticli.types import ArgSpec, CommandSpec


class ProcessMemoryCountersEx(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


def process_memory_mb() -> tuple[float, float]:
    if os.name != "nt":
        return float("nan"), float("nan")
    psapi = ctypes.WinDLL("psapi.dll")
    kernel32 = ctypes.WinDLL("kernel32.dll")
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ProcessMemoryCountersEx),
        wintypes.DWORD,
    ]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    counters = ProcessMemoryCountersEx()
    counters.cb = ctypes.sizeof(counters)
    handle = kernel32.GetCurrentProcess()
    ok = psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
    if not ok:
        return float("nan"), float("nan")
    return counters.WorkingSetSize / 1024 / 1024, counters.PrivateUsage / 1024 / 1024


def percentile(values: list[float], pct: float) -> float:
    values = sorted(values)
    if not values:
        return 0.0
    index = (len(values) - 1) * pct / 100
    low = int(index)
    high = min(low + 1, len(values) - 1)
    if low == high:
        return values[low]
    return values[low] + (values[high] - values[low]) * (index - low)


def report(message: str) -> None:
    print(message, flush=True)


@command(name="add")
def add(a: int, b: int, verbose: bool = False) -> int:
    return a + b


@command(name="echo")
def echo(text: str, upper: bool = False) -> str:
    return text.upper() if upper else text


@command(name="collect")
def collect(items: Annotated[list[str], Option(positional=True)]) -> list[str]:
    return items


@command(name="await0")
async def await0(value: int = 1) -> int:
    await asyncio.sleep(0)
    return value


@command(name="sleepy")
async def sleepy(ms: int = 5) -> int:
    await asyncio.sleep(ms / 1000)
    return ms


def make_registry(extra_commands: int = 0) -> CommandRegistry:
    registry = CommandRegistry()
    registry.register(add)
    registry.register(echo)
    registry.register(collect)
    registry.register(await0)
    registry.register(sleepy)

    for index in range(extra_commands):
        async def synthetic(x: int = 1, _index: int = index) -> int:
            return x + _index

        registry.register_spec(
            CommandSpec(
                name=f"cmd{index:04d}",
                description="synthetic benchmark command",
                func=synthetic,
                args=[ArgSpec(name="x", type=int, default=1, short="x")],
                usage=f"cmd{index:04d} [--x <x>]",
            )
        )
    return registry


def bench_sync(label: str, iterations: int, func) -> None:
    if iterations <= 0:
        report(f"{label}: skipped")
        return
    gc.collect()
    start = time.perf_counter()
    for _ in range(iterations):
        func()
    elapsed = time.perf_counter() - start
    report(
        f"{label}: n={iterations} total_s={elapsed:.4f} "
        f"ops_s={iterations / elapsed:,.0f} avg_us={elapsed / iterations * 1_000_000:.2f}"
    )


async def bench_async_seq(label: str, iterations: int, coro_factory) -> None:
    if iterations <= 0:
        report(f"{label}: skipped")
        return
    gc.collect()
    start = time.perf_counter()
    for _ in range(iterations):
        await coro_factory()
    elapsed = time.perf_counter() - start
    report(
        f"{label}: n={iterations} total_s={elapsed:.4f} "
        f"ops_s={iterations / elapsed:,.0f} avg_us={elapsed / iterations * 1_000_000:.2f}"
    )


async def bench_concurrent(label: str, registry: CommandRegistry, command: str, total: int, concurrency: int) -> None:
    if total <= 0:
        report(f"{label}: skipped")
        return
    semaphore = asyncio.Semaphore(concurrency)
    latencies_ms: list[float] = []

    async def one() -> None:
        async with semaphore:
            start = time.perf_counter()
            result = await registry.execute_async(command)
            latencies_ms.append((time.perf_counter() - start) * 1000)
            if not result.ok:
                raise RuntimeError(result.error.render() if result.error else "unknown error")

    gc.collect()
    start = time.perf_counter()
    await asyncio.gather(*(one() for _ in range(total)))
    elapsed = time.perf_counter() - start
    report(
        f"{label}: total={total} concurrency={concurrency} total_s={elapsed:.4f} "
        f"throughput_ops_s={total / elapsed:,.0f} "
        f"p50_ms={percentile(latencies_ms, 50):.3f} "
        f"p95_ms={percentile(latencies_ms, 95):.3f} "
        f"p99_ms={percentile(latencies_ms, 99):.3f} "
        f"max_ms={max(latencies_ms):.3f}"
    )


def report_memory(label: str) -> None:
    current, peak = tracemalloc.get_traced_memory()
    working_set, private = process_memory_mb()
    report(
        f"{label}: tracemalloc_current_mb={current / 1024 / 1024:.3f} "
        f"tracemalloc_peak_mb={peak / 1024 / 1024:.3f} "
        f"working_set_mb={working_set:.2f} private_mb={private:.2f}"
    )


async def run_async_benches(args: argparse.Namespace, registry: CommandRegistry) -> None:
    await bench_async_seq(
        "async_execute_sequential",
        args.async_iterations,
        lambda: registry.execute_async("add 1 2 --verbose"),
    )

    for concurrency in args.concurrency:
        await bench_concurrent(
            "concurrent_await0",
            registry,
            "await0 --value 7",
            args.concurrent_total,
            concurrency,
        )

    for concurrency in args.concurrency:
        await bench_concurrent(
            "concurrent_sleep",
            registry,
            f"sleepy --ms {args.sleep_ms}",
            args.sleep_total,
            concurrency,
        )


def run(args: argparse.Namespace) -> None:
    tracemalloc.start()
    report(f"python={sys.version.split()[0]} pid={os.getpid()}")

    registry = make_registry()
    report_memory("after_5_command_registry")

    parser = CommandParser(add.__command_spec__.args)
    bench_sync("parser_only", args.parse_iterations, lambda: parser.parse("add 1 2 --verbose"))
    bench_sync("registry_parse", args.parse_iterations, lambda: registry.parse("add 1 2 --verbose"))
    bench_sync(
        "registry_parse_quoted",
        args.parse_iterations,
        lambda: registry.parse('echo "hello world" --upper'),
    )
    bench_sync(
        "registry_parse_backslash_lf",
        args.parse_iterations,
        lambda: registry.parse("collect hello \\\nworld"),
    )
    bench_sync(
        "registry_parse_backslash_crlf",
        args.parse_iterations,
        lambda: registry.parse("collect hello \\\r\nworld"),
    )
    bench_sync(
        "chain_split_quoted_operator",
        args.chain_iterations,
        lambda: CommandRegistry._split_chain_tokens('echo "hello && world" ; echo done'),
    )
    bench_sync(
        "chain_hit_quoted_operator",
        args.chain_iterations,
        lambda: registry.chain_hit('echo "hello ; world" ; echo done'),
    )
    bench_sync("sync_execute", args.sync_iterations, lambda: registry.execute("add 1 2 --verbose"))

    asyncio.run(run_async_benches(args, registry))

    for extra in args.registry_sizes:
        large_registry = make_registry(extra)
        target = f"cmd{extra - 1:04d} --x 3" if extra else "add 1 2"
        bench_sync(
            f"registry_parse_with_{extra + 5}_commands",
            args.large_registry_iterations,
            lambda large_registry=large_registry, target=target: large_registry.parse(target),
        )
        if extra:
            prefix_target = f"cmd{extra - 1:04d}"[:-1]
            bench_sync(
                f"registry_parse_prefix_with_{extra + 5}_commands",
                args.large_registry_iterations,
                lambda large_registry=large_registry, prefix_target=prefix_target: large_registry.parse(prefix_target),
            )
            bench_sync(
                f"registry_parse_unknown_with_{extra + 5}_commands",
                args.large_registry_iterations,
                lambda large_registry=large_registry: large_registry.parse("missing-command"),
            )

    large_registry = make_registry(args.memory_commands)
    report_memory(f"after_{args.memory_commands + 5}_command_registry")
    if args.sync_iterations > 0:
        bench_sync(
            f"execute_with_{args.memory_commands + 5}_commands",
            args.large_registry_iterations,
            lambda: large_registry.execute(f"cmd{args.memory_commands - 1:04d} --x 3"),
        )
    else:
        report(f"execute_with_{args.memory_commands + 5}_commands: skipped")
    report_memory("final")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local agenticli performance benchmarks.")
    parser.add_argument("--parse-iterations", type=int, default=20_000)
    parser.add_argument("--sync-iterations", type=int, default=2_000)
    parser.add_argument("--async-iterations", type=int, default=10_000)
    parser.add_argument("--chain-iterations", type=int, default=5_000)
    parser.add_argument("--concurrent-total", type=int, default=5_000)
    parser.add_argument("--sleep-total", type=int, default=500)
    parser.add_argument("--sleep-ms", type=int, default=5)
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 10, 50, 100])
    parser.add_argument("--registry-sizes", type=int, nargs="+", default=[10, 100, 1000])
    parser.add_argument("--large-registry-iterations", type=int, default=2_000)
    parser.add_argument("--memory-commands", type=int, default=2_000)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
