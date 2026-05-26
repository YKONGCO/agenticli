"""Adapters for wrapping external tool shapes as CommandSpec objects."""

from __future__ import annotations

import inspect
from typing import Any

from agenticli.types import CommandSpec
from agenticli.validation import build_adapter


def wrap_tool(
    tool: Any,
    *,
    name: str | None = None,
    description: str | None = None,
    aliases: list[str] | None = None,
    hidden: bool = False,
    deprecated: str | None = None,
) -> CommandSpec:
    """Wrap a schema-based tool object as an agenticli command."""
    if not hasattr(tool, "execute"):
        raise TypeError("Wrapped tool must expose an execute method")

    schema = getattr(tool, "parameters", None)
    if callable(schema):
        schema = schema()
    adapter = build_adapter(schema=schema)
    cmd_name = name or getattr(tool, "name", tool.__class__.__name__.lower())
    cmd_description = description or getattr(tool, "description", "") or ""

    async def invoke(**kwargs: Any) -> Any:
        result = tool.execute(**kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    return CommandSpec(
        name=cmd_name,
        description=cmd_description,
        func=invoke,
        args=adapter.args,
        usage=adapter.usage(cmd_name),
        aliases=list(aliases or []),
        validator=adapter,
        source="wrapped-tool",
        help_text=adapter.help_text(cmd_name, cmd_description),
        hidden=hidden,
        deprecated=deprecated,
        injections=dict(adapter.injections),
        injection_factories=dict(adapter.injection_factories),
    )


def wrap_langchain_tool(
    tool: Any,
    *,
    name: str | None = None,
    description: str | None = None,
    aliases: list[str] | None = None,
    hidden: bool = False,
    deprecated: str | None = None,
) -> CommandSpec:
    """Wrap a LangChain tool as an agenticli command."""
    if not hasattr(tool, "name"):
        raise TypeError("LangChain tool must expose a name")

    args_schema = getattr(tool, "args_schema", None)
    if args_schema is None:
        tool_call_schema = getattr(tool, "tool_call_schema", None)
        if inspect.isclass(tool_call_schema):
            args_schema = tool_call_schema

    adapter = build_adapter(args_schema) if args_schema is not None else build_adapter(schema={"type": "object", "properties": {}})
    cmd_name = name or getattr(tool, "name")
    cmd_description = description or getattr(tool, "description", "") or ""

    async def invoke(**kwargs: Any) -> Any:
        if hasattr(tool, "ainvoke"):
            result = tool.ainvoke(kwargs)
            if inspect.isawaitable(result):
                return await result
            return result
        if hasattr(tool, "arun"):
            result = tool.arun(**kwargs)
            if inspect.isawaitable(result):
                return await result
            return result
        if hasattr(tool, "invoke"):
            result = tool.invoke(kwargs)
            if inspect.isawaitable(result):
                return await result
            return result
        if hasattr(tool, "run"):
            result = tool.run(**kwargs)
            if inspect.isawaitable(result):
                return await result
            return result
        if hasattr(tool, "func") and callable(tool.func):
            result = tool.func(**kwargs)
            if inspect.isawaitable(result):
                return await result
            return result
        raise TypeError(f"Unsupported LangChain tool target: {tool!r}")

    return CommandSpec(
        name=cmd_name,
        description=cmd_description,
        func=invoke,
        args=adapter.args,
        usage=adapter.usage(cmd_name),
        aliases=list(aliases or []),
        validator=adapter,
        source="langchain-tool",
        help_text=adapter.help_text(cmd_name, cmd_description),
        hidden=hidden,
        deprecated=deprecated,
        injections=dict(adapter.injections),
        injection_factories=dict(adapter.injection_factories),
    )


def wrap_autogen_tool(
    tool: Any,
    *,
    name: str | None = None,
    description: str | None = None,
    aliases: list[str] | None = None,
    hidden: bool = False,
    deprecated: str | None = None,
) -> CommandSpec:
    """Wrap an AutoGen tool as an agenticli command."""
    schema = getattr(tool, "schema", None)
    if not isinstance(schema, dict):
        raise TypeError("AutoGen tool must expose a schema dictionary")

    parameters = schema.get("parameters")
    if not isinstance(parameters, dict):
        raise TypeError("AutoGen tool schema must include a parameters object")

    adapter = build_adapter(schema=parameters)
    cmd_name = name or schema.get("name") or getattr(tool, "name", tool.__class__.__name__.lower())
    cmd_description = description or schema.get("description") or getattr(tool, "description", "") or ""

    async def invoke(**kwargs: Any) -> Any:
        if hasattr(tool, "run_json"):
            result = tool.run_json(kwargs, cancellation_token=None)
            if inspect.isawaitable(result):
                return await result
            return result
        if hasattr(tool, "_func") and callable(tool._func):
            result = tool._func(**kwargs)
            if inspect.isawaitable(result):
                return await result
            return result
        if hasattr(tool, "func") and callable(tool.func):
            result = tool.func(**kwargs)
            if inspect.isawaitable(result):
                return await result
            return result
        raise TypeError(f"Unsupported AutoGen tool target: {tool!r}")

    return CommandSpec(
        name=cmd_name,
        description=cmd_description,
        func=invoke,
        args=adapter.args,
        usage=adapter.usage(cmd_name),
        aliases=list(aliases or []),
        validator=adapter,
        source="autogen-tool",
        help_text=adapter.help_text(cmd_name, cmd_description),
        hidden=hidden,
        deprecated=deprecated,
        injections=dict(adapter.injections),
        injection_factories=dict(adapter.injection_factories),
    )


def wrap_openai_tool_schema(
    *,
    name: str,
    parameters: dict[str, Any],
    handler: Any,
    description: str = "",
    aliases: list[str] | None = None,
    hidden: bool = False,
    deprecated: str | None = None,
) -> CommandSpec:
    """Wrap an OpenAI function/tool schema plus handler as a command."""
    if not callable(handler):
        raise TypeError("handler must be callable")

    adapter = build_adapter(schema=parameters)

    async def invoke(**kwargs: Any) -> Any:
        result = handler(**kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    return CommandSpec(
        name=name,
        description=description,
        func=invoke,
        args=adapter.args,
        usage=adapter.usage(name),
        aliases=list(aliases or []),
        validator=adapter,
        source="openai-tool-schema",
        help_text=adapter.help_text(name, description),
        hidden=hidden,
        deprecated=deprecated,
        injections=dict(adapter.injections),
        injection_factories=dict(adapter.injection_factories),
    )
