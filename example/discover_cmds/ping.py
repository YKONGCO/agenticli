"""Single ping command — CliCommand subclass, discovered by example.discover."""
from __future__ import annotations

from typing import Any

from agenticli import CliCommand


class Ping(CliCommand):
    name = "ping"
    description = "Ping endpoint"

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        return {"pong": True, "from": "ping"}
