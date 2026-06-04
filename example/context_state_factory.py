"""Demo: inject business context via State factory at execution time.

This approach uses State(factory=...) to dynamically inject context
when each command is executed. The factory is called with an ExecutionContext
so it can access command name, raw args, etc.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Annotated, Any

from agenticli import CommandRegistry, Option, State, command, command_group


@dataclass
class UserContext:
    user_id: str
    tenant_id: str
    roles: list[str]


def create_user_context() -> UserContext:
    """Simulate retrieving user context from auth middleware, request scope, etc."""
    return UserContext(
        user_id="user_123",
        tenant_id="tenant_abc",
        roles=["admin", "developer"],
    )


@command_group(name="user", description="User operations with injected context")
class UserCommands:
    @command(name="info", description="Show current user info and context")
    def info(
        self,
        ctx: Annotated[UserContext, State(factory=lambda _: create_user_context())],
    ) -> dict[str, Any]:
        return {
            "user_id": ctx.user_id,
            "tenant_id": ctx.tenant_id,
            "roles": ctx.roles,
        }

    @command(name="greet", description="Greet the current user")
    def greet(
        self,
        ctx: Annotated[UserContext, State(factory=lambda _: create_user_context())],
        name: Annotated[str, Option(positional=True, description="Name to greet")] = "World",
    ) -> dict[str, str]:
        return {
            "message": f"Hello, {name}! You are logged in as {ctx.user_id} (tenant: {ctx.tenant_id})"
        }

    @command(name="check-permission", description="Check if user has a specific role")
    def check_permission(
        self,
        ctx: Annotated[UserContext, State(factory=lambda _: create_user_context())],
        role: Annotated[str, Option(positional=True, description="Role to check")] = "admin",
    ) -> dict[str, Any]:
        has_role = role in ctx.roles
        return {
            "user_id": ctx.user_id,
            "role_checked": role,
            "has_role": has_role,
        }


def build_registry() -> CommandRegistry:
    registry = CommandRegistry()
    registry.register(UserCommands)
    return registry


def execute_value(registry: CommandRegistry, command_text: str) -> Any:
    result = registry.execute(command_text)
    if isinstance(result, list):
        return result
    return result.value if result.ok else result.error.render()


def main() -> None:
    registry = build_registry()

    print("=== Business Context via State Factory Demo ===\n")
    print("Context is created fresh via factory on each command execution\n")

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