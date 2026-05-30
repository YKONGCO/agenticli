"""Demo: inject business context via class __init__ at registration time.

This approach binds user context when creating the command class instance,
so all commands in the class share the same context without needing State().
No global variables - everything is local to build_registry().
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from agenticli import CommandRegistry, Option, command, command_group


class UserCommands:
    """User commands with context bound at instantiation."""

    def __init__(self, user_id: str, tenant_id: str, roles: list[str]):
        self._user_id = user_id
        self._tenant_id = tenant_id
        self._roles = roles

    @command(name="info", description="Show current user info and context")
    def info(self) -> dict[str, Any]:
        return {
            "user_id": self._user_id,
            "tenant_id": self._tenant_id,
            "roles": self._roles,
        }

    @command(name="greet", description="Greet the current user")
    def greet(self, name: Annotated[str, Option(positional=True, description="Name to greet")] = "World") -> dict[str, str]:
        return {
            "message": f"Hello, {name}! You are logged in as {self._user_id} (tenant: {self._tenant_id})"
        }

    @command(name="check-permission", description="Check if user has a specific role")
    def check_permission(
        self, role: Annotated[str, Option(positional=True, description="Role to check")] = "admin"
    ) -> dict[str, Any]:
        has_role = role in self._roles
        return {
            "user_id": self._user_id,
            "role_checked": role,
            "has_role": has_role,
        }


def create_user_commands() -> UserCommands:
    """Factory function to create a configured UserCommands instance."""
    return UserCommands(
        user_id="user_123",
        tenant_id="tenant_abc",
        roles=["admin", "developer"],
    )


def build_registry() -> CommandRegistry:
    """Build registry with user commands bound to specific context."""
    from agenticli import command_from_method

    registry = CommandRegistry()
    instance = create_user_commands()

    registry.register_spec(command_from_method(
        "user info", instance, "info",
        description="Show current user info"
    ))
    registry.register_spec(command_from_method(
        "user greet", instance, "greet",
        description="Greet the current user"
    ))
    registry.register_spec(command_from_method(
        "user check-permission", instance, "check_permission",
        description="Check if user has a specific role"
    ))
    return registry


def execute_value(registry: CommandRegistry, command_text: str) -> Any:
    result = registry.execute(command_text)
    if isinstance(result, list):
        return result
    return result.value if result.ok else result.error.render()


def main() -> None:
    registry = build_registry()

    print("=== Business Context via Class __init__ Demo ===\n")
    print("Context is bound when creating UserCommands instance\n")

    for command_text in (
        "user info",
        "user greet Alice",
        "user check-permission admin",
        "user check-permission superuser",
    ):
        print(f"$ {command_text}")
        print(json.dumps(execute_value(registry, command_text), indent=2, ensure_ascii=False))
        print()


if __name__ == "__main__":
    main()