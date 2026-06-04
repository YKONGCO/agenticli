"""User commands — discovered by example.discover, context-bound by provider."""
from __future__ import annotations

from typing import Annotated

from agenticli import Option, command, command_group


@command_group(name="user", description="User operations")
class UserService:
    def __init__(self, user_id: str, tenant_id: str) -> None:
        self._user_id = user_id
        self._tenant_id = tenant_id

    @command(name="whoami", description="Show current user info")
    def whoami(self) -> dict[str, str]:
        return {"user_id": self._user_id, "tenant_id": self._tenant_id}

    @command(name="greet", description="Greet the current user")
    def greet(self, name: Annotated[str, Option(positional=True, description="Name to greet")] = "World") -> dict[str, str]:
        return {"message": f"Hello {name} from {self._user_id} (tenant: {self._tenant_id})"}
