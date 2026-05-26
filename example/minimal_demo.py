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


def execute_value(command_text: str):
    result = registry.execute(command_text)
    if isinstance(result, list):
        return result
    return result.value if result.ok else result.error.render()


# Simple usage
print("=== Basic usage ===")
print(execute_value('hello --name "World"'))

print("\n=== Short options + bool flag ===")
print(execute_value("hello -n Alice -l"))

print("\n=== Mix short and full options ===")
print(execute_value("hello --name Bob -l"))

print("\n=== Short options ===")
print(execute_value("add -a 10 -b 20"))

print("\n=== Full options ===")
print(execute_value("add --a 100 --b 200"))

print("\n=== Class-based command ===")
print(execute_value("class_greet --name Classy"))

print("\n=== Help: --help (global) ===")
print(execute_value("--help"))

print("\n=== Help: --help hello ===")
print(execute_value("--help hello"))

print("\n=== Help: hello --help ===")
print(execute_value("hello --help"))

print("\n=== Help: hello -h (short) ===")
print(execute_value("hello -h"))

print("\n=== Chain: ; (sequential) ===")
for result in registry.execute("hello -n A; add -a 1 -b 2; hello -n B", chain=True):
    print(result)

print("\n=== Chain: && (AND - stop on failure) ===")
for result in registry.execute("hello -n A && add -a 1 -b 2 && hello -n B", chain=True):
    print(result)

print("\n=== Chain: || (OR - stop on success) ===")
for result in registry.execute("hello -n A || add -a 1 -b 2", chain=True):
    print(result)

print("\n=== Slash /cmd style ===")
print(execute_value("/hello -n Slash"))
print(execute_value("/add -a 5 -b 3"))

print("\n=== Chain with / ===")
for result in registry.execute("/hello -n A && /add -a 10 -b 20", chain=True):
    print(result)

print("\n=== match(chain=True): check if all commands registered ===")
for hit in registry.match("hello -n World && add -a 1 -b 2", chain=True):
    print(f"  {hit.command}: confidence={hit.confidence}")

print("\n=== match(chain=True): with unknown command ===")
for hit in registry.match("hello -n World && unknown_cmd && add -a 1 -b 2", chain=True):
    print(f"  {hit.command}: confidence={hit.confidence}")

print("\n=== match(chain=True): boolean check ===")
print(f"All registered: {all(hit.command for hit in registry.match('hello -n A && add -a 1 -b 2', chain=True))}")
print(f"Has unknown: {all(hit.command for hit in registry.match('hello -n A && unknown_cmd', chain=True))}")
