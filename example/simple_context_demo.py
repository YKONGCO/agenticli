"""Simple demo: register a command group instance with user context."""

from __future__ import annotations

import json
from typing import Annotated, Any

from agenticli import CommandRegistry, Option, command, command_group


@command_group(name="user", description="User operations")
class UserService:
    def __init__(self, user_id: str, tenant_id: str):
        self._user_id = user_id
        self._tenant_id = tenant_id

    @command(name="whoami", description="Show current user info")
    def whoami(self) -> dict[str, str]:
        return {"user_id": self._user_id, "tenant_id": self._tenant_id}

    @command(name="greet", description="Greet user")
    def greet(self, name: Annotated[str, Option(positional=True, description="Name")] = "World") -> dict[str, str]:
        return {"message": f"Hello {name} from {self._user_id}"}


def main() -> None:
    # Create instance with context
    service = UserService(user_id="alice", tenant_id="company-x")

    # Register instance directly with registry
    registry = CommandRegistry()
    registry.register(service)  # now supports @command_group instance!

    # Test commands
    for cmd in ("user whoami", "user greet Bob"):
        print(f"$ {cmd}")
        result = registry.execute(cmd)
        print(json.dumps(result.value if result.ok else result.error.render(), indent=2))
        print()


if __name__ == "__main__":
    main()