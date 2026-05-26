"""Runtime helpers for sync and async command execution."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any


def run_sync(awaitable: Any) -> Any:
    """Run an awaitable in synchronous contexts."""
    if not inspect.isawaitable(awaitable):
        return awaitable
    return asyncio.run(awaitable)
