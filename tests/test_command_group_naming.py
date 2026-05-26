"""Tests to verify command_group subcommand naming with hyphenated names."""

from __future__ import annotations

from typing import Annotated

from agenticli import CommandRegistry, Option, command, command_group


def execute_value(registry: CommandRegistry, command_text: str):
    result = registry.execute(command_text)
    assert not isinstance(result, list)
    return result.value if result.ok else result.error.render()


@command_group(name="media", description="Media operations")
class MediaCommands:
    @command(name="gen-image", description="Generate an image")
    def gen_image(
        self,
        prompt: Annotated[str, Option(positional=True, description="image prompt")],
    ) -> str:
        return f"generated: {prompt}"

    @command(name="list-images", description="List images")
    def list_images(
        self,
        limit: Annotated[int, Option(short="n", description="max results")] = 10,
    ) -> list[str]:
        return [f"image_{i}" for i in range(min(limit, 3))]


def test_command_group_subcommand_uses_hyphenated_name_from_decorator():
    """Verify subcommand is registered with hyphenated name, not underscored function name."""
    registry = CommandRegistry()
    registry.register(MediaCommands)

    # The subcommand should be registered as "media gen-image", not "media gen_image"
    assert registry.has("media gen-image"), "Subcommand should be registered as 'media gen-image'"
    assert not registry.has("media gen_image"), "Subcommand should NOT be registered as 'media gen_image'"


def test_command_group_subcommand_executes_with_hyphenated_name():
    """Verify subcommand can be executed using hyphenated name."""
    registry = CommandRegistry()
    registry.register(MediaCommands)

    result = execute_value(registry, 'media gen-image "a beautiful sunset"')
    assert result == "generated: a beautiful sunset"


def test_command_group_subcommand_help_with_hyphenated_name():
    """Verify subcommand help works with hyphenated name."""
    registry = CommandRegistry()
    registry.register(MediaCommands)

    help_text = execute_value(registry, "media gen-image --help")
    assert "Command: media gen-image" in help_text
    assert "gen-image" in help_text


def test_command_group_all_subcommands_have_hyphenated_names():
    """Verify multiple subcommands all use their decorator names correctly."""
    registry = CommandRegistry()
    registry.register(MediaCommands)

    # Both subcommands should use hyphenated names
    assert registry.has("media gen-image")
    assert registry.has("media list-images")
    assert not registry.has("media gen_image")
    assert not registry.has("media list_images")

    # Both should execute
    result1 = execute_value(registry, 'media gen-image "test"')
    assert result1 == "generated: test"

    result2 = execute_value(registry, "media list-images -n 5")
    assert result2 == ["image_0", "image_1", "image_2"]


def test_command_group_nested_name_from_spec_name_not_func_name():
    """Verify the nested command name comes from spec.name, not function __name__."""
    registry = CommandRegistry()
    registry.register(MediaCommands)

    # Get the registered spec and verify its name
    spec = registry.get("media gen-image")
    assert spec is not None, "Spec should exist for 'media gen-image'"
    assert spec.name == "media gen-image", f"Spec name should be 'media gen-image', got '{spec.name}'"

    # Check the other subcommand too
    spec2 = registry.get("media list-images")
    assert spec2 is not None, "Spec should exist for 'media list-images'"
    assert spec2.name == "media list-images", f"Spec name should be 'media list-images', got '{spec2.name}'"


def test_mixed_underscore_and_hyphen_names_in_same_group():
    """Test group with some commands using underscores in function names but hyphen in @command name."""

    @command_group(name="tools", description="Tool operations")
    class ToolCommands:
        @command(name="create-file", description="Create a file")  # hyphenated name
        def make_file(self, path: Annotated[str, Option(positional=True)]) -> str:
            return f"created: {path}"

        @command(description="Delete a file")  # no name provided, uses func name
        def delete_file(self, path: Annotated[str, Option(positional=True)]) -> str:
            return f"deleted: {path}"

    registry = CommandRegistry()
    registry.register(ToolCommands)

    # Explicit hyphenated name should be used
    assert registry.has("tools create-file")
    assert not registry.has("tools make_file")

    # Default func name (delete_file) should be used as-is
    assert registry.has("tools delete_file")
    assert not registry.has("tools delete-file")

    # Execute both to confirm they work
    assert execute_value(registry, 'tools create-file "/tmp/test"') == "created: /tmp/test"
    assert execute_value(registry, 'tools delete_file "/tmp/test"') == "deleted: /tmp/test"
