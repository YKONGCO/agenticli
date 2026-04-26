"""Minimal demo - just print raw command output."""

from dataclasses import dataclass

from agenticli import CliCommand, CommandRegistry, command, Option
from typing import Annotated


@command(name="hello", description="Say hello")
def hello(
    name: Annotated[str, Option(short="n", description="Who to greet")],
    loud: Annotated[bool, Option(short="l", description="Shout loud")] = False,
) -> dict:
    msg = f"Hello, {name}!"
    return {"message": msg.upper() if loud else msg}


@command(name="add", description="Add two numbers")
def add(
    a: Annotated[float, Option(short="a", description="First number")],
    b: Annotated[float, Option(short="b", description="Second number")],
) -> dict:
    return {"result": a + b}


@dataclass
class GreetInput:
    name: str


class GreetCommand(CliCommand):
    """Greet using class-based command."""

    name = "class_greet"
    description = "Greet from a class"

    args_model = GreetInput

    async def run(self, name: str) -> dict:
        return {"message": f"Hello, {name}! (from class)"}


registry = CommandRegistry()
registry.register(hello)
registry.register(add)
registry.register(GreetCommand)


# Simple usage
print("=== Basic usage ===")
print(registry.parse_and_execute('hello --name "World"'))

print("\n=== Short options + bool flag ===")
print(registry.parse_and_execute("hello -n Alice -l"))

print("\n=== Mix short and full options ===")
print(registry.parse_and_execute("hello --name Bob -l"))

print("\n=== Short options ===")
print(registry.parse_and_execute("add -a 10 -b 20"))

print("\n=== Full options ===")
print(registry.parse_and_execute("add --a 100 --b 200"))

print("\n=== Class-based command ===")
print(registry.parse_and_execute("class_greet --name Classy"))

print("\n=== Help: --help (global) ===")
print(registry.parse_and_execute("--help"))

print("\n=== Help: --help hello ===")
print(registry.parse_and_execute("--help hello"))

print("\n=== Help: hello --help ===")
print(registry.parse_and_execute("hello --help"))

print("\n=== Help: hello -h (short) ===")
print(registry.parse_and_execute("hello -h"))

print("\n=== Chain: ; (sequential) ===")
for result in registry.chain_execute("hello -n A; add -a 1 -b 2; hello -n B"):
    print(result)

print("\n=== Chain: && (AND - stop on failure) ===")
for result in registry.chain_execute("hello -n A && add -a 1 -b 2 && hello -n B"):
    print(result)

print("\n=== Chain: || (OR - stop on success) ===")
for result in registry.chain_execute("hello -n A || add -a 1 -b 2"):
    print(result)

print("\n=== Slash /cmd style ===")
print(registry.parse_and_execute("/hello -n Slash"))
print(registry.parse_and_execute("/add -a 5 -b 3"))

print("\n=== Chain with / ===")
for result in registry.chain_execute("/hello -n A && /add -a 10 -b 20"):
    print(result)

print("\n=== chain_hit: check if all commands registered ===")
for hit in registry.chain_hit("hello -n World && add -a 1 -b 2"):
    print(f"  {hit.command}: confidence={hit.confidence}")

print("\n=== chain_hit: with unknown command ===")
for hit in registry.chain_hit("hello -n World && unknown_cmd && add -a 1 -b 2"):
    print(f"  {hit.command}: confidence={hit.confidence}")

print("\n=== chain_has: boolean check ===")
print(f"All registered: {registry.chain_has('hello -n A && add -a 1 -b 2')}")
print(f"Has unknown: {registry.chain_has('hello -n A && unknown_cmd')}")

