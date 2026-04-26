"""Validation backends for llmcli commands.

This module provides various validation adapters that convert Python function
signatures, dataclasses, Pydantic models, or JSON schemas into llmcli-compatible
argument specifications with full type coercion and validation logic.
"""

from __future__ import annotations

import difflib
import inspect
import json
import types
from dataclasses import dataclass
from dataclasses import MISSING, fields, is_dataclass
from typing import Annotated, Any, Literal, get_args, get_origin, get_type_hints

from llmcli.types import ArgSpec

try:
    from pydantic import BaseModel
except Exception:  # pragma: no cover - optional dependency
    BaseModel = None  # type: ignore[assignment]


@dataclass(frozen=True)
class Option:
    """Per-argument CLI metadata.

    Provides additional CLI-specific metadata for command arguments using
    the @Annotated pattern. Use with Optional[Option(...)] to attach metadata
    to type annotations.

    Attributes:
        short: Single character short flag (e.g., 'v' for -v).
        description: Human-readable description of the argument.
        positional: Whether this is a positional argument.
        value_name: Placeholder name in usage help (e.g., <FILE>).
        example: Example value shown in help text.
        order: Display order in help text.
        position: Position index for sorting positional args.
        hidden: Whether to hide from help output.
        repeatable: Whether argument can be specified multiple times.
        nargs: Number of values to consume.
        requires: Arguments that must be provided when this is provided.
        excludes: Arguments that cannot be provided with this one.
        internal: Mark as internal (injected, not from user input).
        inject: Static value to inject.
        inject_factory: Factory function to generate injected value.

    Example:
        def cmd(
            file: Annotated[str, Option(short='f', description='Input file')],
        ) -> None: ...
    """

    short: str | None = None
    description: str = ""
    positional: bool = False
    value_name: str | None = None
    example: str | None = None
    order: int | None = None
    position: int | None = None
    hidden: bool = False
    repeatable: bool = False
    nargs: int | None = None
    requires: tuple[str, ...] = ()
    excludes: tuple[str, ...] = ()
    internal: bool = False
    inject: Any = None
    inject_factory: Any = None


def Injected(*, value: Any = None, factory: Any = None) -> Option:
    """Create an internal-only injected parameter marker.

    Marks a parameter as internal (injected), meaning it won't be parsed
    from user input but instead provided automatically at execution time.

    Args:
        value: Static value to inject.
        factory: Factory function to call to generate the injected value.

    Returns:
        Option with internal=True and inject/inject_factory set.

    Example:
        def cmd(state: Annotated[dict, Injected(factory=get_state)]) -> None: ...
    """
    return Option(internal=True, inject=value, inject_factory=factory)


def Callback(*, value: Any = None, factory: Any = None) -> Option:
    """Alias for an injected callback dependency.

    Convenience function for marking a parameter as an injected callback.
    Equivalent to Injected(value=value, factory=factory).

    Args:
        value: Static callback value to inject.
        factory: Factory function producing the callback.

    Returns:
        Option configured for callback injection.
    """
    return Injected(value=value, factory=factory)


def State(*, value: Any = None, factory: Any = None) -> Option:
    """Alias for an injected state dependency.

    Convenience function for marking a parameter as an injected state object.
    Equivalent to Injected(value=value, factory=factory).

    Args:
        value: Static state value to inject.
        factory: Factory function producing the state.

    Returns:
        Option configured for state injection.
    """
    return Injected(value=value, factory=factory)


def _is_pydantic_model(candidate: Any) -> bool:
    """Check if candidate is a Pydantic model class."""
    return bool(BaseModel) and inspect.isclass(candidate) and issubclass(candidate, BaseModel)


def _unwrap_annotated(annotation: Any) -> tuple[Any, Option | None]:
    """Extract base type and Option from Annotated type."""
    if get_origin(annotation) is Annotated:
        args = get_args(annotation)
        base = args[0]
        meta = next((item for item in args[1:] if isinstance(item, Option)), None)
        return base, meta
    return annotation, None


def _is_optional(annotation: Any) -> tuple[bool, Any]:
    """Check if annotation is Optional[T] (Union[T, None])."""
    origin = get_origin(annotation)
    if origin is None:
        return False, annotation
    args = [arg for arg in get_args(annotation) if arg is not type(None)]
    if origin not in (types.UnionType, getattr(__import__("typing"), "Union", object)):
        return False, annotation
    if len(args) + 1 == len(get_args(annotation)) and len(args) >= 1:
        return True, args[0] if len(args) == 1 else annotation
    return False, annotation


def _normalize_annotation(annotation: Any) -> Any:
    """Normalize annotation by unwrapping Annotated and Optional."""
    annotation, _ = _unwrap_annotated(annotation)
    optional, inner = _is_optional(annotation)
    annotation = inner if optional else annotation
    origin = get_origin(annotation)
    if origin is None:
        return annotation
    if origin is Literal:
        literal_args = get_args(annotation)
        return type(literal_args[0]) if literal_args else str
    if origin in (list, tuple, set, dict):
        return origin
    return annotation


def _schema_type_to_python(schema_type: str | None) -> type | str:
    """Convert JSON schema type string to Python type."""
    mapping = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    return mapping.get(schema_type or "string", str)


class ValidationAdapter:
    """Base validation adapter.

    Provides common functionality for argument validation including
    usage string generation, help text formatting, and ordered argument
    retrieval.

    Subclasses must implement validate() for custom validation logic.
    """

    def __init__(self, args: list[ArgSpec], schema: dict[str, Any] | None = None):
        """Initialize validation adapter.

        Args:
            args: List of argument specifications.
            schema: Optional JSON schema for the command.
        """
        self.args = args
        self.schema = schema or {"type": "object", "properties": {}}
        if not hasattr(self, "injections"):
            self.injections = {}
        if not hasattr(self, "injection_factories"):
            self.injection_factories = {}

    def validate(self, raw_args: dict[str, Any]) -> dict[str, Any]:
        """Validate and coerce raw arguments.

        Args:
            raw_args: Raw argument dictionary from parser.

        Returns:
            Validated and coerced argument dictionary.

        Raises:
            ValueError: If required arguments are missing or validation fails.
        """
        raise NotImplementedError

    def usage(self, name: str) -> str:
        """Generate usage string for command.

        Args:
            name: Command name.

        Returns:
            Usage string like "cmd <arg1> [--opt <value>]".
        """
        pieces = [name]
        for arg in self._ordered_args():
            if arg.hidden:
                continue
            if arg.positional:
                marker = f"<{arg.value_name or arg.name}>" if arg.required else f"[<{arg.value_name or arg.name}>]"
                pieces.append(marker)
                continue
            flag = f"--{arg.name}"
            value_name = arg.value_name or arg.name
            if arg.required:
                if arg.is_flag:
                    pieces.append(flag)
                else:
                    pieces.append(f"{flag} <{value_name}>")
            elif arg.is_flag:
                pieces.append(f"[{flag}]")
            else:
                pieces.append(f"[{flag} <{value_name}>]")
        return " ".join(pieces)

    def help_text(self, name: str, description: str) -> str:
        """Generate complete help text for command.

        Args:
            name: Command name.
            description: Command description.

        Returns:
            Formatted help text with usage, description, and argument details.
        """
        lines = [f"Command: {name}", f"Usage: {self.usage(name)}"]
        if description:
            lines.extend(["", description.strip()])
        visible_args = [arg for arg in self._ordered_args() if not arg.hidden]
        if visible_args:
            lines.extend(["", f"Recommended order: {self.usage(name)}"])
        if visible_args:
            lines.extend(["", "Arguments:"])
            examples: list[str] = []
            for arg in visible_args:
                req = "required" if arg.required else "optional"
                default = ""
                if arg.default is not None and arg.default is not inspect._empty:
                    default = f" default={arg.default!r}"
                enum = f" enum={arg.enum}" if arg.enum else ""
                flag = " flag" if arg.is_flag else ""
                short = f" short=-{arg.short}" if arg.short else ""
                positional = " positional" if arg.positional else ""
                example = f" example={arg.example!r}" if arg.example else ""
                order = f" order={arg.order}" if arg.order is not None else ""
                position = f" position={arg.position}" if arg.position is not None else ""
                desc = arg.description or "no description"
                label = arg.name if arg.positional else f"--{arg.name}"
                lines.append(
                    f"  {label}: {desc} ({req}{flag}{short}{positional}{default}{enum}{example}{order}{position})"
                )
                if arg.example:
                    sample_label = arg.name if arg.positional else f"--{arg.name}"
                    examples.append(f"  {sample_label}: {arg.example}")
            if examples:
                lines.extend(["", "Examples:"])
                lines.extend(examples)
        return "\n".join(lines)

    def _ordered_args(self) -> list[ArgSpec]:
        """Return arguments sorted by position, order, then original index."""
        indexed = list(enumerate(self.args))
        return [
            arg
            for _, arg in sorted(
                indexed,
                key=lambda item: (
                    item[1].position is None,
                    item[1].position if item[1].position is not None else 10_000,
                    item[1].order is None,
                    item[1].order if item[1].order is not None else 10_000,
                    item[0],
                ),
            )
        ]


class SignatureAdapter(ValidationAdapter):
    """Validation based on Python function signatures.

    Extracts argument specifications from a function's signature, using
    type hints and Optional[Option(...)] annotations for metadata.
    """

    def __init__(self, func: Any):
        """Initialize from function.

        Args:
            func: Function to extract signature from.
        """
        sig = inspect.signature(func)
        hints = get_type_hints(func, include_extras=True)
        self.injections = {}
        self.injection_factories = {}
        args: list[ArgSpec] = []
        used_shorts: set[str] = set()
        properties: dict[str, Any] = {}
        required: list[str] = []

        for param_name, param in sig.parameters.items():
            if param_name in {"self", "cls"}:
                continue

            annotation = hints.get(param_name, str)
            annotation, option = _unwrap_annotated(annotation)
            if option and option.internal:
                if option.inject_factory is not None:
                    self.injection_factories[param_name] = option.inject_factory
                elif option.inject is not None:
                    self.injections[param_name] = option.inject
                elif param.default is not inspect.Parameter.empty:
                    self.injections[param_name] = param.default
                else:
                    self.injections[param_name] = None
                continue
            normalized = _normalize_annotation(annotation)
            default = None if param.default is inspect.Parameter.empty else param.default
            is_required = param.default is inspect.Parameter.empty
            is_flag = normalized is bool
            short = option.short if option and option.short else _make_short_name(param_name, used_shorts)
            if short:
                used_shorts.add(short)
            description = option.description if option else ""
            enum = _enum_from_annotation(annotation)
            value_name = option.value_name if option and option.value_name else param_name
            example = option.example if option else None
            order = option.order if option else None
            position = option.position if option else None
            hidden = bool(option and option.hidden)
            repeatable = bool(option and option.repeatable)
            nargs = option.nargs if option else None
            if nargs is None:
                nargs = _nargs_from_annotation(annotation)
            requires = list(option.requires) if option else []
            excludes = list(option.excludes) if option else []

            args.append(
                ArgSpec(
                    name=param_name,
                    type=normalized,
                    default=default,
                    required=is_required,
                    description=description,
                    enum=enum,
                    short=short,
                    is_flag=is_flag,
                    schema=_annotation_to_schema(annotation, default),
                    positional=bool(option and option.positional),
                    value_name=value_name,
                    example=example,
                    order=order,
                    position=position,
                    hidden=hidden,
                    repeatable=repeatable,
                    nargs=nargs,
                    requires=requires,
                    excludes=excludes,
                    raw_annotation=annotation,
                )
            )
            properties[param_name] = _annotation_to_schema(annotation, default)
            if is_required:
                required.append(param_name)

        schema = {"type": "object", "properties": properties, "required": required}
        super().__init__(args=args, schema=schema)

    def validate(self, raw_args: dict[str, Any]) -> dict[str, Any]:
        """Validate arguments against function signature.

        Args:
            raw_args: Raw argument dictionary.

        Returns:
            Validated argument dictionary with type coercion applied.

        Raises:
            ValueError: If required arguments are missing or type coercion fails.
        """
        return _validate_against_arg_specs(raw_args, self.args)


class DataclassAdapter(ValidationAdapter):
    """Validation backed by a dataclass type.

    Extracts argument specifications from a dataclass's field definitions,
    using type hints and Annotated[Type, Option(...)] for metadata.
    """

    def __init__(self, model: type):
        """Initialize from dataclass.

        Args:
            model: Dataclass type to extract fields from.
        """
        hints = get_type_hints(model, include_extras=True)
        self.injections = {}
        self.injection_factories = {}
        args: list[ArgSpec] = []
        used_shorts: set[str] = set()
        properties: dict[str, Any] = {}
        required: list[str] = []

        for field_info in fields(model):
            annotation = hints.get(field_info.name, field_info.type)
            annotation, option = _unwrap_annotated(annotation)
            if option and option.internal:
                if option.inject_factory is not None:
                    self.injection_factories[field_info.name] = option.inject_factory
                elif option.inject is not None:
                    self.injections[field_info.name] = option.inject
                elif field_info.default is not MISSING:
                    self.injections[field_info.name] = field_info.default
                else:
                    self.injections[field_info.name] = None
                continue
            normalized = _normalize_annotation(annotation)
            has_default = field_info.default is not MISSING or field_info.default_factory is not MISSING
            default = None
            if field_info.default is not MISSING:
                default = field_info.default
            is_required = not has_default
            is_flag = normalized is bool
            short = option.short if option and option.short else _make_short_name(field_info.name, used_shorts)
            if short:
                used_shorts.add(short)
            description = option.description if option else ""
            enum = _enum_from_annotation(annotation)
            value_name = option.value_name if option and option.value_name else field_info.name
            example = option.example if option else None
            order = option.order if option else None
            position = option.position if option else None
            hidden = bool(option and option.hidden)
            repeatable = bool(option and option.repeatable)
            nargs = option.nargs if option else None
            if nargs is None:
                nargs = _nargs_from_annotation(annotation)
            requires = list(option.requires) if option else []
            excludes = list(option.excludes) if option else []
            args.append(
                ArgSpec(
                    name=field_info.name,
                    type=normalized,
                    default=default,
                    required=is_required,
                    description=description,
                    enum=enum,
                    short=short,
                    is_flag=is_flag,
                    schema=_annotation_to_schema(annotation, default),
                    positional=bool(option and option.positional),
                    value_name=value_name,
                    example=example,
                    order=order,
                    position=position,
                    hidden=hidden,
                    repeatable=repeatable,
                    nargs=nargs,
                    requires=requires,
                    excludes=excludes,
                    raw_annotation=annotation,
                )
            )
            properties[field_info.name] = _annotation_to_schema(annotation, default)
            if is_required:
                required.append(field_info.name)

        self.model = model
        schema = {"type": "object", "properties": properties, "required": required}
        super().__init__(args=args, schema=schema)

    def validate(self, raw_args: dict[str, Any]) -> dict[str, Any]:
        """Validate arguments and instantiate dataclass.

        Args:
            raw_args: Raw argument dictionary.

        Returns:
            Dictionary of validated arguments with dataclass instance fields.

        Raises:
            ValueError: If validation fails.
        """
        values = _validate_against_arg_specs(raw_args, self.args)
        return self.model(**values).__dict__


class PydanticAdapter(ValidationAdapter):
    """Validation backed by Pydantic v2.

    Extracts argument specifications from a Pydantic model's field definitions,
    using model_fields and type hints for metadata.
    """

    def __init__(self, model: type):
        """Initialize from Pydantic model.

        Args:
            model: Pydantic BaseModel subclass.
        """
        field_map = getattr(model, "model_fields")
        hints = get_type_hints(model, include_extras=True)
        self.injections = {}
        self.injection_factories = {}
        args: list[ArgSpec] = []
        used_shorts: set[str] = set()

        for name, field_info in field_map.items():
            annotation = hints.get(name, field_info.annotation)
            annotation, option = _unwrap_annotated(annotation)
            if option and option.internal:
                if option.inject_factory is not None:
                    self.injection_factories[name] = option.inject_factory
                elif option.inject is not None:
                    self.injections[name] = option.inject
                elif not field_info.is_required():
                    self.injections[name] = field_info.default
                else:
                    self.injections[name] = None
                continue
            normalized = _normalize_annotation(annotation)
            required = field_info.is_required()
            default = None if required else field_info.default
            is_flag = normalized is bool
            short = option.short if option and option.short else _make_short_name(name, used_shorts)
            if short:
                used_shorts.add(short)
            description = option.description if option and option.description else (field_info.description or "")
            schema = field_info.json_schema_extra or {}
            full_schema = {"description": description, **schema}
            if "type" not in full_schema:
                full_schema.update(_annotation_to_schema(annotation, default))
            value_name = option.value_name if option and option.value_name else name
            example = option.example if option else None
            order = option.order if option else None
            position = option.position if option else None
            hidden = bool(option and option.hidden)
            repeatable = bool(option and option.repeatable)
            nargs = option.nargs if option else None
            if nargs is None:
                nargs = _nargs_from_annotation(annotation)
            requires = list(option.requires) if option else []
            excludes = list(option.excludes) if option else []
            args.append(
                ArgSpec(
                    name=name,
                    type=normalized,
                    default=default,
                    required=required,
                    description=description,
                    short=short,
                    is_flag=is_flag,
                    enum=list(getattr(annotation, "__args__", [])) if getattr(annotation, "__origin__", None) else None,
                    schema=full_schema,
                    positional=bool(option and option.positional),
                    value_name=value_name,
                    example=example,
                    order=order,
                    position=position,
                    hidden=hidden,
                    repeatable=repeatable,
                    nargs=nargs,
                    requires=requires,
                    excludes=excludes,
                    raw_annotation=annotation,
                )
            )

        self.model = model
        schema = model.model_json_schema()
        super().__init__(args=args, schema=schema)

    def validate(self, raw_args: dict[str, Any]) -> dict[str, Any]:
        """Validate arguments using Pydantic model.

        Args:
            raw_args: Raw argument dictionary.

        Returns:
            Validated arguments as dictionary via model_dump().

        Raises:
            ValidationError: If Pydantic validation fails.
        """
        casted = _validate_against_arg_specs(raw_args, self.args)
        return self.model.model_validate(casted).model_dump()


class JsonSchemaAdapter(ValidationAdapter):
    """Validation based on a JSON schema object.

    Converts a JSON schema definition into argument specifications,
    supporting x-* extensions for additional metadata.
    """

    def __init__(self, schema: dict[str, Any]):
        """Initialize from JSON schema.

        Args:
            schema: JSON schema object with properties definition.
        """
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))
        used_shorts: set[str] = set()
        args: list[ArgSpec] = []

        for name, prop_schema in properties.items():
            arg_type = _schema_type_to_python(prop_schema.get("type"))
            args.append(
                ArgSpec(
                    name=name,
                    type=arg_type,
                    default=prop_schema.get("default"),
                    required=name in required,
                    description=prop_schema.get("description", ""),
                    enum=prop_schema.get("enum"),
                    short=_make_short_name(name, used_shorts),
                    is_flag=arg_type is bool,
                    schema=prop_schema,
                    value_name=prop_schema.get("title", name),
                    example=prop_schema.get("examples", [None])[0],
                    order=prop_schema.get("x-order"),
                    position=prop_schema.get("x-position"),
                    hidden=bool(prop_schema.get("x-hidden", False)),
                    repeatable=bool(prop_schema.get("x-repeatable", False)),
                    nargs=prop_schema.get("x-nargs"),
                    requires=list(prop_schema.get("x-requires", [])),
                    excludes=list(prop_schema.get("x-excludes", [])),
                )
            )

        super().__init__(args=args, schema=schema)

    def validate(self, raw_args: dict[str, Any]) -> dict[str, Any]:
        """Validate arguments against JSON schema.

        Args:
            raw_args: Raw argument dictionary.

        Returns:
            Validated argument dictionary.

        Raises:
            ValueError: If required arguments are missing.
        """
        return _validate_against_arg_specs(raw_args, self.args)


def build_adapter(target: Any = None, schema: dict[str, Any] | None = None) -> ValidationAdapter:
    """Create the best validation adapter for a target.

    Automatically selects the appropriate adapter based on the target type:
    - Pydantic BaseModel -> PydanticAdapter
    - Function/method -> SignatureAdapter
    - Dataclass -> DataclassAdapter
    - dict (JSON schema) -> JsonSchemaAdapter

    Args:
        target: The target to create adapter for (function, class, or None).
        schema: Optional JSON schema to use instead of inferring from target.

    Returns:
        Appropriate ValidationAdapter subclass for the target.

    Raises:
        TypeError: If target type is not supported.
    """
    if schema is not None:
        return JsonSchemaAdapter(schema)
    if target is None:
        return JsonSchemaAdapter({"type": "object", "properties": {}})
    if _is_pydantic_model(target):
        return PydanticAdapter(target)
    if inspect.isfunction(target) or inspect.ismethod(target):
        return SignatureAdapter(target)
    if inspect.isclass(target) and is_dataclass(target):
        return DataclassAdapter(target)
    raise TypeError(f"Unsupported validation target: {target!r}")


def _make_short_name(name: str, used: set[str]) -> str | None:
    """Generate a short flag name from argument name.

    Args:
        name: Argument name to derive short name from.
        used: Set of already-used short names to avoid collisions.

    Returns:
        First available character as short name, or None if all taken.
    """
    for char in name:
        lower = char.lower()
        if lower.isalpha() and lower not in used:
            used.add(lower)
            return lower
    return None


def _annotation_to_schema(annotation: Any, default: Any) -> dict[str, Any]:
    """Convert Python type annotation to JSON schema dict.

    Args:
        annotation: Type annotation to convert.
        default: Default value if any.

    Returns:
        JSON schema dictionary representation.
    """
    annotation, _ = _unwrap_annotated(annotation)
    optional, inner = _is_optional(annotation)
    annotation = inner if optional else annotation
    origin = get_origin(annotation)

    if origin is Literal:
        literal_args = list(get_args(annotation))
        literal_type = _annotation_to_schema(type(literal_args[0]), None)["type"] if literal_args else "string"
        schema = {"type": literal_type, "enum": literal_args}
    elif origin is list:
        item_args = get_args(annotation)
        items = _annotation_to_schema(item_args[0], None) if item_args else {"type": "string"}
        schema = {"type": "array", "items": items}
    elif origin is tuple:
        tuple_args = get_args(annotation)
        if tuple_args and len(tuple_args) == 2 and tuple_args[1] is Ellipsis:
            schema = {"type": "array", "items": _annotation_to_schema(tuple_args[0], None)}
        else:
            schema = {
                "type": "array",
                "prefixItems": [_annotation_to_schema(arg, None) for arg in tuple_args],
                "minItems": len(tuple_args),
                "maxItems": len(tuple_args),
            }
    elif origin is dict:
        schema = {"type": "object"}
    elif annotation is int:
        schema = {"type": "integer"}
    elif annotation is float:
        schema = {"type": "number"}
    elif annotation is bool:
        schema = {"type": "boolean"}
    else:
        schema = {"type": "string"}

    if default is not None:
        schema["default"] = default
    return schema


def _enum_from_annotation(annotation: Any) -> list[Any] | None:
    """Extract enum values from Literal type annotation."""
    annotation, _ = _unwrap_annotated(annotation)
    optional, inner = _is_optional(annotation)
    annotation = inner if optional else annotation
    if get_origin(annotation) is Literal:
        return list(get_args(annotation))
    return None


def _nargs_from_annotation(annotation: Any) -> int | None:
    """Determine nargs from tuple annotation."""
    annotation, _ = _unwrap_annotated(annotation)
    optional, inner = _is_optional(annotation)
    annotation = inner if optional else annotation
    origin = get_origin(annotation)
    if origin is tuple:
        tuple_args = get_args(annotation)
        if tuple_args and len(tuple_args) == 2 and tuple_args[1] is Ellipsis:
            return None
        return len(tuple_args)
    return None


def _coerce_value(value: Any, arg: ArgSpec) -> Any:
    """Coerce a value to the appropriate type based on ArgSpec.

    Args:
        value: Raw value to coerce.
        arg: Argument specification with target type and constraints.

    Returns:
        Coerced value of the appropriate type.

    Raises:
        ValueError: If coercion fails or value is invalid for enum.
    """
    target = arg.type
    schema = arg.schema or {}
    annotation = arg.raw_annotation

    if value is None:
        return value
    if target is bool:
        if isinstance(value, bool):
            return value
        lowered = str(value).lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"{arg.name} should be boolean")
    if target is int:
        return int(value)
    if target is float:
        return float(value)
    if target is list:
        item_annotation = _list_item_annotation(annotation)
        if isinstance(value, list):
            return [_coerce_simple(item, item_annotation) for item in value]
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if not isinstance(parsed, list):
                    raise ValueError(f"{arg.name} should be array")
                return [_coerce_simple(item, item_annotation) for item in parsed]
            except json.JSONDecodeError:
                parts = [part.strip() for part in value.split(",") if part.strip()]
                return [_coerce_simple(item, item_annotation) for item in parts]
    if target is tuple:
        tuple_annotations = _tuple_item_annotations(annotation)
        if isinstance(value, list):
            values = value
        elif isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    values = parsed
                else:
                    values = [segment.strip() for segment in value.split(",")]
            except json.JSONDecodeError:
                values = [segment.strip() for segment in value.split(",")]
        else:
            values = [value]
        if tuple_annotations and tuple_annotations[-1] is Ellipsis:
            base = tuple_annotations[0]
            return tuple(_coerce_simple(item, base) for item in values)
        if tuple_annotations and len(values) != len(tuple_annotations):
            raise ValueError(f"{arg.name} expects {len(tuple_annotations)} values")
        coerced = [
            _coerce_simple(item, tuple_annotations[idx] if idx < len(tuple_annotations) else str)
            for idx, item in enumerate(values)
        ]
        return tuple(coerced)
    if target is dict:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            parsed = json.loads(value)
            if not isinstance(parsed, dict):
                raise ValueError(f"{arg.name} should be object")
            return parsed
    if arg.enum and value not in arg.enum:
        matches = difflib.get_close_matches(str(value), [str(v) for v in arg.enum], n=1, cutoff=0.5)
        suffix = f". Did you mean '{matches[0]}'?" if matches else ""
        raise ValueError(f"{arg.name} must be one of {arg.enum}{suffix}")
    if schema.get("enum") and value not in schema["enum"]:
        matches = difflib.get_close_matches(str(value), [str(v) for v in schema["enum"]], n=1, cutoff=0.5)
        suffix = f". Did you mean '{matches[0]}'?" if matches else ""
        raise ValueError(f"{arg.name} must be one of {schema['enum']}{suffix}")
    return value


def _validate_against_arg_specs(raw_args: dict[str, Any], args: list[ArgSpec]) -> dict[str, Any]:
    """Validate and coerce raw arguments against ArgSpec list.

    Applies type coercion, checks required arguments, and validates
    requires/excludes constraints.

    Args:
        raw_args: Raw argument dictionary from parser.
        args: List of argument specifications.

    Returns:
        Validated and coerced argument dictionary.

    Raises:
        ValueError: If required arguments are missing or constraints violated.
    """
    result: dict[str, Any] = {}
    arg_map = {arg.name: arg for arg in args}
    provided = set()

    for key, value in raw_args.items():
        if key not in arg_map:
            continue
        result[key] = _coerce_value(value, arg_map[key])
        provided.add(key)

    for arg in args:
        if arg.name in result:
            continue
        if arg.default is not None:
            result[arg.name] = arg.default
            continue
        if arg.is_flag and not arg.required:
            result[arg.name] = False
            continue
        if arg.required:
            raise ValueError(f"missing required argument: {arg.name}")

    for arg in args:
        active = arg.name in provided and result.get(arg.name) not in (None, False, [], {}, ())
        if not active:
            continue
        for required_name in arg.requires:
            required_value = result.get(required_name)
            if required_name not in result or required_value in (None, False, [], {}, ()):
                raise ValueError(f"{arg.name} requires {required_name}")
        for excluded_name in arg.excludes:
            excluded_value = result.get(excluded_name)
            if excluded_name in provided or excluded_value not in (None, False, [], {}, ()):
                raise ValueError(f"{arg.name} cannot be used with {excluded_name}")

    return result


def _coerce_simple(value: Any, annotation: Any) -> Any:
    """Coerce a single value based on type annotation.

    Args:
        value: Value to coerce.
        annotation: Type annotation to coerce against.

    Returns:
        Coerced value.

    Raises:
        ValueError: If value cannot be coerced or is invalid for enum.
    """
    annotation, _ = _unwrap_annotated(annotation)
    optional, inner = _is_optional(annotation)
    annotation = inner if optional else annotation
    origin = get_origin(annotation)
    if origin is Literal:
        literal_args = list(get_args(annotation))
        if not literal_args:
            return value
        base_type = type(literal_args[0])
        converted = _coerce_simple(value, base_type)
        if converted not in literal_args:
            matches = difflib.get_close_matches(str(converted), [str(v) for v in literal_args], n=1, cutoff=0.5)
            suffix = f". Did you mean '{matches[0]}'?" if matches else ""
            raise ValueError(f"value must be one of {literal_args}{suffix}")
        return converted
    if annotation is int:
        return int(value)
    if annotation is float:
        return float(value)
    if annotation is bool:
        lowered = str(value).lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        raise ValueError("value should be boolean")
    return value


def _list_item_annotation(annotation: Any) -> Any:
    """Extract item type from list annotation."""
    annotation, _ = _unwrap_annotated(annotation)
    optional, inner = _is_optional(annotation)
    annotation = inner if optional else annotation
    if get_origin(annotation) is list:
        args = get_args(annotation)
        return args[0] if args else str
    return str


def _tuple_item_annotations(annotation: Any) -> list[Any]:
    """Extract item types from tuple annotation."""
    annotation, _ = _unwrap_annotated(annotation)
    optional, inner = _is_optional(annotation)
    annotation = inner if optional else annotation
    if get_origin(annotation) is tuple:
        return list(get_args(annotation))
    return []