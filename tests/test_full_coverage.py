"""Function-by-function coverage for every public surface of agenticli.

This file exists to pin down the expected behavior of every public class
and function in the package. Each test is named after the symbol it
covers (e.g. ``test_ArgSpec_to_dict_round_trip``) so a missing entry
means a gap in the public-surface contract.

Public surface covered here:

* Data classes
    - ArgSpec (to_dict / from_dict)
    - CommandError (render)
    - CommandSpec (to_dict / from_dict, with/without resolvers)
    - ExecutionCallbacks / ExecutionContext / ExecutionResult
    - HitResult / ParseResult

* Validation
    - Option, Injected, Callback, State
    - ValidationAdapter, SignatureAdapter, DataclassAdapter, PydanticAdapter, JsonSchemaAdapter
    - build_adapter dispatch
    - _validate_against_arg_specs (required, requires, excludes)
    - _coerce_value / _coerce_simple (bool, int, float, list, tuple, dict, enum)

* Decorators and builders
    - @command (bare, parens, all kwargs)
    - @command_group (group + namespace modes, all flags)
    - command_from_method / command_from_model
    - CliCommand (with dataclass and Pydantic args models)

* CommandRegistry
    - register, register_spec, unregister, get, has
    - parse, match, execute, execute_async
    - discover
    - to_dict, from_dict
    - help, render_llm_context
    - len, contains, commands

* Adapters
    - wrap_tool, wrap_langchain_tool, wrap_autogen_tool, wrap_openai_tool_schema

* Built-ins
    - ExecTool

* Side-effect invariants (the final section) are tested in
  ``test_property_fuzz.py`` — they belong with the property-based
  testing to keep this file deterministic.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field, fields
from typing import Annotated, Any, Literal, Optional

import pytest

from agenticli import (
    ArgSpec,
    CliCommand,
    CommandError,
    CommandRegistry,
    CommandSpec,
    ExecTool,
    ExecutionCallbacks,
    ExecutionContext,
    ExecutionResult,
    HitResult,
    Injected,
    Callback,
    State,
    Option,
    ParseResult,
    command,
    command_from_method,
    command_from_model,
    command_group,
    wrap_autogen_tool,
    wrap_langchain_tool,
    wrap_openai_tool_schema,
    wrap_tool,
)
from agenticli.parser import CommandLineParser, CommandParser, ChainSegment
from agenticli.matcher import CommandMatcher
from agenticli.factory import CommandFactory
from agenticli.validation import (
    DataclassAdapter,
    JsonSchemaAdapter,
    PydanticAdapter,
    SignatureAdapter,
    ValidationAdapter,
    _annotation_to_schema,
    _coerce_simple,
    _coerce_value,
    _enum_from_annotation,
    _is_optional,
    _list_item_annotation,
    _make_short_name,
    _nargs_from_annotation,
    _normalize_annotation,
    _schema_type_to_python,
    _tuple_item_annotations,
    _unwrap_annotated,
    _validate_against_arg_specs,
    build_adapter,
)
from agenticli.discover import (
    DiscoverError,
    DiscoverResult,
    build_target,
    discover,
    iter_command_classes,
    iter_module_specs,
)
from agenticli.runtime import run_sync
from agenticli.builtin import ExecTool as BuiltinExecTool

from agenticli import builtin as builtin_module  # for coverage of imports


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _no_self(func):
    """Wrapper to add assert to verify func identity isn't equal to wrapper."""
    return func


# ---------------------------------------------------------------------------
# ArgSpec: to_dict / from_dict
# ---------------------------------------------------------------------------


def test_ArgSpec_defaults():
    spec = ArgSpec(name="x")
    assert spec.name == "x"
    assert spec.type is str
    assert spec.default is None
    assert spec.required is False
    assert spec.description == ""
    assert spec.enum is None
    assert spec.short is None
    assert spec.is_flag is False
    assert spec.schema is None
    assert spec.positional is False
    assert spec.value_name is None
    assert spec.example is None
    assert spec.order is None
    assert spec.position is None
    assert spec.hidden is False
    assert spec.repeatable is False
    assert spec.nargs is None
    assert spec.requires == []
    assert spec.excludes == []
    assert spec.raw_annotation is str


def test_ArgSpec_to_dict_round_trip():
    spec = ArgSpec(
        name="verbose",
        type=bool,
        default=False,
        required=False,
        description="verbose output",
        short="v",
        is_flag=True,
        schema={"type": "boolean"},
        positional=False,
        value_name="V",
        example="--verbose",
        order=2,
        position=0,
        hidden=False,
        repeatable=True,
        nargs=3,
        requires=["x"],
        excludes=["y"],
        raw_annotation=bool,
    )
    data = spec.to_dict()
    # raw_annotation is intentionally dropped.
    assert "raw_annotation" not in data
    # type is normalized to a string for JSON.
    assert data["type"] == "bool"
    rebuilt = ArgSpec.from_dict(data)
    assert rebuilt.name == spec.name
    # After round trip, type is the JSON-safe string form.
    assert rebuilt.type == "bool"
    assert rebuilt.default == spec.default
    assert rebuilt.required == spec.required
    assert rebuilt.description == spec.description
    assert rebuilt.short == spec.short
    assert rebuilt.is_flag == spec.is_flag
    assert rebuilt.schema == spec.schema
    assert rebuilt.positional == spec.positional
    assert rebuilt.value_name == spec.value_name
    assert rebuilt.example == spec.example
    assert rebuilt.order == spec.order
    assert rebuilt.position == spec.position
    assert rebuilt.hidden == spec.hidden
    assert rebuilt.repeatable == spec.repeatable
    assert rebuilt.nargs == spec.nargs
    assert rebuilt.requires == spec.requires
    assert rebuilt.excludes == spec.excludes
    # raw_annotation is left at the default after a round trip.
    assert rebuilt.raw_annotation is str


def test_ArgSpec_from_dict_handles_missing_keys():
    rebuilt = ArgSpec.from_dict({"name": "x"})
    assert rebuilt.name == "x"
    assert rebuilt.type == "str"
    assert rebuilt.required is False
    assert rebuilt.hidden is False
    assert rebuilt.repeatable is False
    assert rebuilt.requires == []


def test_ArgSpec_to_dict_is_json_safe():
    spec = ArgSpec(name="tags", type=list, default=["a", "b"], enum=None)
    data = spec.to_dict()
    encoded = json.dumps(data)
    decoded = json.loads(encoded)
    assert decoded["name"] == "tags"
    assert decoded["default"] == ["a", "b"]


# ---------------------------------------------------------------------------
# CommandError
# ---------------------------------------------------------------------------


def test_CommandError_render_no_suggestion_no_hint():
    err = CommandError(code="x", message="boom")
    assert err.render() == "Error: boom"


def test_CommandError_render_with_suggestion():
    err = CommandError(code="x", message="unknown", suggestion="foo")
    assert err.render() == "Error: unknown Did you mean 'foo'?"


def test_CommandError_render_with_hint():
    err = CommandError(code="x", message="unknown", hint="try --help")
    assert err.render() == "Error: unknown try --help"


def test_CommandError_render_with_both_in_order():
    err = CommandError(code="x", message="m", suggestion="s", hint="h")
    # suggestion first, then hint
    assert err.render() == "Error: m Did you mean 's'? h"


def test_CommandError_default_details_is_empty_dict():
    err = CommandError(code="x", message="m")
    assert err.details == {}
    err.details["k"] = "v"  # mutable
    assert err.details == {"k": "v"}


def test_CommandError_keeps_subject_and_code():
    err = CommandError(code="parse_error", message="bad", subject="ls")
    assert err.subject == "ls"
    assert err.code == "parse_error"


# ---------------------------------------------------------------------------
# CommandSpec: to_dict / from_dict
# ---------------------------------------------------------------------------


def _make_spec(name="cmd", **kwargs) -> CommandSpec:
    def f(**kwargs_inner):
        return kwargs_inner

    defaults = dict(
        description="d",
        func=f,
        args=[ArgSpec(name="x", type=int, required=True)],
        usage=f"{name} <x>",
        aliases=["a"],
        parent="grp",
        validator=None,
        source="function",
        help_text=f"Command: {name}",
        hidden=False,
        deprecated=None,
        include_in_prompt=True,
        injections={},
        injection_factories={},
    )
    defaults.update(kwargs)
    return CommandSpec(name=name, **defaults)


def test_CommandSpec_defaults():
    spec = CommandSpec(name="c", description="d", func=lambda: None)
    assert spec.args == []
    assert spec.usage == ""
    assert spec.aliases == []
    assert spec.parent is None
    assert spec.validator is None
    assert spec.source == "function"
    assert spec.help_text == ""
    assert spec.hidden is False
    assert spec.deprecated is None
    assert spec.include_in_prompt is True
    assert spec.injections == {}
    assert spec.injection_factories == {}


def test_CommandSpec_to_dict_drops_callables_and_keeps_safe_injections():
    spec = _make_spec(
        injections={"safe": 1, "unsafe": object()},  # object() is not JSON-safe
        injection_factories={"k": lambda: 1},
    )
    data = spec.to_dict()
    # callables stripped
    assert "func" not in data
    assert "validator" not in data
    # unsafe injection dropped
    assert "safe" in data["injections"]
    assert "unsafe" not in data["injections"]
    # factory names retained (callable not stored)
    assert data["injection_factory_names"] == ["k"]


def test_CommandSpec_to_dict_is_json_safe():
    spec = _make_spec()
    data = spec.to_dict()
    encoded = json.dumps(data)
    decoded = json.loads(encoded)
    assert decoded["name"] == "cmd"
    assert decoded["args"][0]["name"] == "x"


def test_CommandSpec_from_dict_without_resolver_returns_raising_func():
    spec = _make_spec(name="cmdx")
    data = spec.to_dict()
    rebuilt = CommandSpec.from_dict(data)
    with pytest.raises(RuntimeError, match="cmdx"):
        rebuilt.func()


def test_CommandSpec_from_dict_with_resolver_binds_func():
    spec = _make_spec(name="bindy")
    data = spec.to_dict()
    sentinel = lambda **kwargs: "BOUND"  # noqa: E731
    rebuilt = CommandSpec.from_dict(data, func_resolver=lambda n, p: sentinel)
    assert rebuilt.func() == "BOUND"


def test_CommandSpec_from_dict_with_factory_resolver_binds_factories():
    spec = _make_spec(
        injection_factories={"k": lambda: "raw"},
    )
    data = spec.to_dict()
    sentinel_factory = lambda: "REPLACED"  # noqa: E731
    rebuilt = CommandSpec.from_dict(
        data,
        factory_resolver=lambda fname, parent: sentinel_factory,
    )
    assert rebuilt.injection_factories["k"] is sentinel_factory


def test_CommandSpec_from_dict_no_factory_resolver_leaves_empty_dict():
    spec = _make_spec(injection_factories={"k": lambda: 1})
    data = spec.to_dict()
    rebuilt = CommandSpec.from_dict(data)
    assert rebuilt.injection_factories == {}


def test_CommandSpec_round_trip_preserves_public_fields():
    spec = _make_spec(
        hidden=True,
        deprecated="use new",
        include_in_prompt=False,
    )
    data = spec.to_dict()
    rebuilt = CommandSpec.from_dict(data)
    assert rebuilt.name == spec.name
    assert rebuilt.description == spec.description
    assert rebuilt.usage == spec.usage
    assert rebuilt.aliases == spec.aliases
    assert rebuilt.parent == spec.parent
    assert rebuilt.source == spec.source
    assert rebuilt.help_text == spec.help_text
    assert rebuilt.hidden == spec.hidden
    assert rebuilt.deprecated == spec.deprecated
    assert rebuilt.include_in_prompt == spec.include_in_prompt
    assert rebuilt.args[0].name == spec.args[0].name


# ---------------------------------------------------------------------------
# ExecutionCallbacks / ExecutionContext / ExecutionResult
# ---------------------------------------------------------------------------


def test_ExecutionCallbacks_defaults_all_none():
    cb = ExecutionCallbacks()
    assert cb.before_execute is None
    assert cb.after_execute is None
    assert cb.on_error is None


def test_ExecutionContext_defaults():
    ctx = ExecutionContext(command="c", raw="c 1")
    assert ctx.args == {}
    assert ctx.result is None
    assert ctx.error is None


def test_ExecutionContext_mutable_args():
    ctx = ExecutionContext(command="c", raw="c 1")
    ctx.args["k"] = "v"
    assert ctx.args == {"k": "v"}


def test_ExecutionResult_success_shape():
    r = ExecutionResult(ok=True, command="c", value=42)
    assert r.command == "c"
    assert r.value == 42
    assert r.error is None


def test_ExecutionResult_failure_shape():
    err = CommandError(code="x", message="m")
    r = ExecutionResult(ok=False, command="c", error=err)
    assert r.value is None
    assert r.error is err


# ---------------------------------------------------------------------------
# HitResult / ParseResult
# ---------------------------------------------------------------------------


def test_HitResult_defaults():
    hit = HitResult(command=None)
    assert hit.confidence == 0.0
    assert hit.suggested_args is None
    assert hit.match_type is None
    assert hit.args_str is None


def test_HitResult_supports_explicit_construction():
    hit = HitResult(command="c", confidence=0.9, suggested_args={"x": 1},
                    match_type="exact", args_str="foo bar")
    assert hit.command == "c"
    assert hit.confidence == 0.9
    assert hit.suggested_args == {"x": 1}
    assert hit.match_type == "exact"
    assert hit.args_str == "foo bar"


def test_ParseResult_defaults():
    res = ParseResult(command="c", args={}, raw="c")
    assert res.errors == []


def test_ParseResult_errors_is_mutable_list():
    res = ParseResult(command="c", args={}, raw="c")
    res.errors.append("bad")
    assert res.errors == ["bad"]


# ---------------------------------------------------------------------------
# Option / Injected / Callback / State
# ---------------------------------------------------------------------------


def test_Option_defaults():
    opt = Option()
    assert opt.short is None
    assert opt.description == ""
    assert opt.positional is False
    assert opt.value_name is None
    assert opt.example is None
    assert opt.order is None
    assert opt.position is None
    assert opt.hidden is False
    assert opt.repeatable is False
    assert opt.nargs is None
    assert opt.requires == ()
    assert opt.excludes == ()
    assert opt.internal is False
    assert opt.inject is None
    assert opt.inject_factory is None


def test_Option_is_frozen():
    opt = Option()
    with pytest.raises(Exception):  # FrozenInstanceError
        opt.description = "x"  # type: ignore[misc]


def test_Injected_marks_internal_with_value():
    opt = Injected(value=42)
    assert opt.internal is True
    assert opt.inject == 42
    assert opt.inject_factory is None


def test_Injected_marks_internal_with_factory():
    def f():
        return 1

    opt = Injected(factory=f)
    assert opt.internal is True
    assert opt.inject_factory is f
    assert opt.inject is None


def test_Callback_alias_of_Injected():
    opt = Callback(value=lambda: 1)
    assert opt.internal is True
    assert opt.inject is not None


def test_State_alias_of_Injected():
    opt = State(value={"k": "v"})
    assert opt.internal is True
    assert opt.inject == {"k": "v"}


def test_Injected_default_no_value_no_factory_injects_None_at_runtime():
    @command(name="inj_default")
    def inj_default(state: Annotated[Any, Injected()]) -> Any:
        return state

    registry = CommandRegistry()
    registry.register(inj_default)
    result = registry.execute("inj_default")
    assert result.ok
    assert result.value is None


# ---------------------------------------------------------------------------
# Validation: _unwrap_annotated / _is_optional / _normalize_annotation
# ---------------------------------------------------------------------------


def test_unwrap_annotated_no_metadata_returns_same():
    t, m = _unwrap_annotated(str)
    assert t is str
    assert m is None


def test_unwrap_annotated_returns_base_and_option():
    t, m = _unwrap_annotated(Annotated[str, Option(short="s")])
    assert t is str
    assert m is not None
    assert m.short == "s"


def test_unwrap_annotated_picks_option_from_many_metas():
    t, m = _unwrap_annotated(Annotated[int, "doc", Option(short="x")])
    assert t is int
    assert m is not None
    assert m.short == "x"


def test_is_optional_recognizes_Optional_T():
    is_opt, inner = _is_optional(Annotated[Optional[int], Option()])
    # outer is Annotated, not Optional — but after _unwrap_annotated the test
    # would not be applicable. Test Optional[int] directly:
    is_opt, inner = _is_optional(Optional[int])
    assert is_opt is True
    assert inner is int


def test_is_optional_returns_false_for_plain_types():
    is_opt, inner = _is_optional(str)
    assert is_opt is False
    assert inner is str


def test_normalize_annotation_strips_annotated_and_optional():
    norm = _normalize_annotation(Annotated[Optional[int], Option()])
    assert norm is int


def test_normalize_annotation_handles_literal():
    norm = _normalize_annotation(Literal["a", "b"])
    assert norm is str


def test_normalize_annotation_handles_list_tuple_set_dict():
    assert _normalize_annotation(list[int]) is list
    assert _normalize_annotation(tuple[int, str]) is tuple
    assert _normalize_annotation(set[int]) is set
    assert _normalize_annotation(dict[str, int]) is dict


# ---------------------------------------------------------------------------
# Validation: _schema_type_to_python
# ---------------------------------------------------------------------------


def test_schema_type_to_python_known_types():
    assert _schema_type_to_python("string") is str
    assert _schema_type_to_python("integer") is int
    assert _schema_type_to_python("number") is float
    assert _schema_type_to_python("boolean") is bool
    assert _schema_type_to_python("array") is list
    assert _schema_type_to_python("object") is dict


def test_schema_type_to_python_unknown_defaults_to_str():
    assert _schema_type_to_python("weird-type") is str
    assert _schema_type_to_python(None) is str


# ---------------------------------------------------------------------------
# Validation: _make_short_name
# ---------------------------------------------------------------------------


def test_make_short_name_picks_first_unused_char():
    used = set()
    assert _make_short_name("verbose", used) == "v"
    assert "v" in used


def test_make_short_name_skips_taken():
    used = {"v"}
    assert _make_short_name("verbose", used) == "e"


def test_make_short_name_returns_none_when_no_alpha():
    # A name with no alpha chars (only digits/punct) → None.
    used = set()
    assert _make_short_name("___", used) is None
    assert _make_short_name("123", used) is None


def test_make_short_name_returns_none_when_all_taken():
    used = set("abcde")
    assert _make_short_name("abcde", used) is None


# ---------------------------------------------------------------------------
# Validation: _annotation_to_schema
# ---------------------------------------------------------------------------


def test_annotation_to_schema_basic_types():
    assert _annotation_to_schema(str, None) == {"type": "string"}
    assert _annotation_to_schema(int, None) == {"type": "integer"}
    assert _annotation_to_schema(float, None) == {"type": "number"}
    assert _annotation_to_schema(bool, None) == {"type": "boolean"}


def test_annotation_to_schema_list_and_tuple():
    assert _annotation_to_schema(list[int], None) == {
        "type": "array",
        "items": {"type": "integer"},
    }
    assert _annotation_to_schema(tuple[int, ...], None) == {
        "type": "array",
        "items": {"type": "integer"},
    }
    fixed = _annotation_to_schema(tuple[int, str], None)
    assert fixed["type"] == "array"
    assert fixed["minItems"] == 2
    assert fixed["maxItems"] == 2


def test_annotation_to_schema_dict():
    # bare ``dict`` has no origin and falls through to the default
    # ``{"type": "string"}`` branch — only parameterized ``dict[K, V]``
    # produces the object schema.
    assert _annotation_to_schema(dict, None) == {"type": "string"}
    assert _annotation_to_schema(dict[str, int], None) == {"type": "object"}


def test_annotation_to_schema_literal():
    sch = _annotation_to_schema(Literal["a", "b", "c"], None)
    assert sch["type"] == "string"
    assert sch["enum"] == ["a", "b", "c"]


def test_annotation_to_schema_default_attached():
    sch = _annotation_to_schema(int, 5)
    assert sch["default"] == 5


# ---------------------------------------------------------------------------
# Validation: _enum_from_annotation
# ---------------------------------------------------------------------------


def test_enum_from_literal():
    assert _enum_from_annotation(Literal["a", "b"]) == ["a", "b"]


def test_enum_from_non_literal_is_none():
    assert _enum_from_annotation(str) is None
    assert _enum_from_annotation(int) is None
    assert _enum_from_annotation(list[int]) is None


# ---------------------------------------------------------------------------
# Validation: _nargs_from_annotation
# ---------------------------------------------------------------------------


def test_nargs_from_tuple_fixed_arity():
    assert _nargs_from_annotation(tuple[int, str, float]) == 3


def test_nargs_from_tuple_ellipsis_is_none():
    assert _nargs_from_annotation(tuple[int, ...]) is None


def test_nargs_from_non_tuple_is_none():
    assert _nargs_from_annotation(list[int]) is None
    assert _nargs_from_annotation(int) is None


# ---------------------------------------------------------------------------
# Validation: _coerce_simple
# ---------------------------------------------------------------------------


def test_coerce_simple_int():
    assert _coerce_simple("5", int) == 5
    assert _coerce_simple(5, int) == 5


def test_coerce_simple_float():
    assert _coerce_simple("1.5", float) == 1.5


def test_coerce_simple_bool_truthy():
    for v in ("1", "true", "yes", "on"):
        assert _coerce_simple(v, bool) is True
    for v in ("0", "false", "no", "off"):
        assert _coerce_simple(v, bool) is False


def test_coerce_simple_bool_invalid_raises():
    with pytest.raises(ValueError):
        _coerce_simple("maybe", bool)


def test_coerce_simple_literal_invalid_raises_with_suggestion():
    with pytest.raises(ValueError, match="one of"):
        _coerce_simple("z", Literal["a", "b", "c"])


def test_coerce_simple_literal_close_match_suggests():
    # Choose a value that difflib considers close to one of the literals.
    with pytest.raises(ValueError, match="Did you mean"):
        _coerce_simple("alphax", Literal["alpha", "beta", "c"])


def test_coerce_simple_literal_value_passes_through():
    # A valid literal value passes through unchanged.
    assert _coerce_simple("alpha", Literal["alpha", "beta", "c"]) == "alpha"


def test_coerce_simple_unknown_type_returns_value_unchanged():
    assert _coerce_simple("hello", str) == "hello"


# ---------------------------------------------------------------------------
# Validation: _coerce_value
# ---------------------------------------------------------------------------


def test_coerce_value_none_passthrough():
    spec = ArgSpec(name="x", type=str)
    assert _coerce_value(None, spec) is None


def test_coerce_value_bool_from_native_bool():
    spec = ArgSpec(name="x", type=bool)
    assert _coerce_value(True, spec) is True
    assert _coerce_value(False, spec) is False


def test_coerce_value_int_and_float():
    spec_i = ArgSpec(name="x", type=int)
    spec_f = ArgSpec(name="x", type=float)
    assert _coerce_value("5", spec_i) == 5
    assert _coerce_value("1.25", spec_f) == 1.25


def test_coerce_value_list_from_native_list():
    spec = ArgSpec(name="x", type=list, raw_annotation=list[int])
    assert _coerce_value([1, 2, 3], spec) == [1, 2, 3]


def test_coerce_value_list_from_json_string():
    # JSON-parsed list items keep their JSON-parsed types; the validator
    # doesn't re-coerce ints inside a list[str] context. This test pins
    # the actual library behavior: items are returned with their JSON
    # types preserved unless a non-string-compatible coercion applies.
    spec = ArgSpec(name="x", type=list)
    out = _coerce_value("[1,2,3]", spec)
    # Items may be ints (from json.loads) — verify the list shape and contents.
    assert out == [1, 2, 3]
    # Strings coming from JSON strings stay strings.
    spec2 = ArgSpec(name="x", type=list, raw_annotation=list[str])
    out2 = _coerce_value('["a","b"]', spec2)
    assert out2 == ["a", "b"]


def test_coerce_value_list_from_csv_string():
    spec = ArgSpec(name="x", type=list)
    assert _coerce_value("a,b,c", spec) == ["a", "b", "c"]


def test_coerce_value_list_json_but_not_array_raises():
    spec = ArgSpec(name="x", type=list)
    with pytest.raises(ValueError):
        _coerce_value('{"a": 1}', spec)


def test_coerce_value_tuple_from_native_list():
    spec = ArgSpec(name="x", type=tuple, raw_annotation=tuple[int, str])
    out = _coerce_value([1, "two"], spec)
    assert out == (1, "two")


def test_coerce_value_tuple_wrong_arity_raises():
    spec = ArgSpec(name="x", type=tuple, raw_annotation=tuple[int, str])
    with pytest.raises(ValueError, match="2 values"):
        _coerce_value([1, 2, 3], spec)


def test_coerce_value_tuple_ellipsis_variadic():
    spec = ArgSpec(name="x", type=tuple, raw_annotation=tuple[int, ...])
    assert _coerce_value([1, 2, 3, 4], spec) == (1, 2, 3, 4)


def test_coerce_value_dict_from_native():
    spec = ArgSpec(name="x", type=dict)
    assert _coerce_value({"a": 1}, spec) == {"a": 1}


def test_coerce_value_dict_from_json_string():
    spec = ArgSpec(name="x", type=dict)
    assert _coerce_value('{"a": 1}', spec) == {"a": 1}


def test_coerce_value_dict_json_not_object_raises():
    spec = ArgSpec(name="x", type=dict)
    with pytest.raises(ValueError):
        _coerce_value("[1, 2]", spec)


def test_coerce_value_enum_invalid_with_close_match():
    spec = ArgSpec(name="mode", enum=["fast", "safe"], type=str)
    with pytest.raises(ValueError, match="Did you mean"):
        _coerce_value("fas", spec)


def test_coerce_value_enum_valid():
    spec = ArgSpec(name="mode", enum=["fast", "safe"], type=str)
    assert _coerce_value("fast", spec) == "fast"


def test_coerce_value_schema_enum_invalid_with_close_match():
    spec = ArgSpec(name="mode", type=str, schema={"enum": ["alpha", "beta"]})
    with pytest.raises(ValueError, match="Did you mean"):
        _coerce_value("alph", spec)


def test_coerce_value_passthrough_for_unknown_type():
    spec = ArgSpec(name="x", type=str)
    assert _coerce_value("plain", spec) == "plain"


# ---------------------------------------------------------------------------
# Validation: _list_item_annotation / _tuple_item_annotations
# ---------------------------------------------------------------------------


def test_list_item_annotation():
    assert _list_item_annotation(list[int]) is int


def test_list_item_annotation_for_non_list_is_str():
    assert _list_item_annotation(int) is str


def test_tuple_item_annotations_for_tuple():
    assert _tuple_item_annotations(tuple[int, str, bool]) == [int, str, bool]


def test_tuple_item_annotations_for_non_tuple_is_empty():
    assert _tuple_item_annotations(int) == []


# ---------------------------------------------------------------------------
# Validation: _validate_against_arg_specs
# ---------------------------------------------------------------------------


def test_validate_required_missing_raises():
    args = [ArgSpec(name="x", type=int, required=True)]
    with pytest.raises(ValueError, match="missing required argument: x"):
        _validate_against_arg_specs({}, args)


def test_validate_required_present_passes():
    args = [ArgSpec(name="x", type=int, required=True)]
    out = _validate_against_arg_specs({"x": "5"}, args)
    assert out == {"x": 5}


def test_validate_default_applied_when_missing():
    args = [ArgSpec(name="x", type=int, default=10)]
    assert _validate_against_arg_specs({}, args) == {"x": 10}


def test_validate_flag_default_false_when_missing():
    args = [ArgSpec(name="v", type=bool, is_flag=True)]
    assert _validate_against_arg_specs({}, args) == {"v": False}


def test_validate_extra_keys_silently_ignored():
    args = [ArgSpec(name="x", type=int, default=0)]
    out = _validate_against_arg_specs({"x": 1, "y": 2}, args)
    assert out == {"x": 1}


def test_validate_requires_constraint_raises():
    args = [
        ArgSpec(name="a", type=bool, is_flag=True, requires=["b"]),
        ArgSpec(name="b", type=bool, is_flag=True),
    ]
    with pytest.raises(ValueError, match="requires b"):
        _validate_against_arg_specs({"a": True}, args)


def test_validate_excludes_constraint_raises():
    args = [
        ArgSpec(name="a", type=bool, is_flag=True, excludes=["b"]),
        ArgSpec(name="b", type=bool, is_flag=True),
    ]
    with pytest.raises(ValueError, match="cannot be used with b"):
        _validate_against_arg_specs({"a": True, "b": True}, args)


# ---------------------------------------------------------------------------
# Validation: build_adapter dispatch
# ---------------------------------------------------------------------------


def test_build_adapter_from_function():
    def f(x: int) -> None:
        pass

    adapter = build_adapter(f)
    assert isinstance(adapter, SignatureAdapter)
    assert any(a.name == "x" for a in adapter.args)


def test_build_adapter_from_dataclass():
    @dataclass
    class M:
        x: int

    adapter = build_adapter(M)
    assert isinstance(adapter, DataclassAdapter)
    assert any(a.name == "x" for a in adapter.args)


def test_build_adapter_from_pydantic():
    pyd = pytest.importorskip("pydantic")
    from pydantic import BaseModel

    class M(BaseModel):
        x: int

    adapter = build_adapter(M)
    assert isinstance(adapter, PydanticAdapter)


def test_build_adapter_from_schema():
    adapter = build_adapter(schema={"type": "object", "properties": {"x": {"type": "integer"}}})
    assert isinstance(adapter, JsonSchemaAdapter)


def test_build_adapter_no_target_or_schema():
    adapter = build_adapter()
    assert isinstance(adapter, JsonSchemaAdapter)
    assert adapter.args == []


def test_build_adapter_unsupported_raises():
    with pytest.raises(TypeError, match="Unsupported validation target"):
        build_adapter(42)


# ---------------------------------------------------------------------------
# Validation adapters: usage() and help_text()
# ---------------------------------------------------------------------------


def test_signature_adapter_usage_includes_positionals_and_flags():
    def cmd(
        path: Annotated[str, Option(positional=True)],
        verbose: Annotated[bool, Option(short="v")] = False,
    ) -> None:
        pass

    adapter = build_adapter(cmd)
    usage = adapter.usage("cmd")
    assert usage.startswith("cmd ")
    assert "<path>" in usage
    assert "[--verbose" in usage or "[-v" in usage


def test_signature_adapter_help_text_includes_description():
    def cmd(
        path: Annotated[str, Option(positional=True, description="the file")],
    ) -> None:
        """the command"""
        pass

    adapter = build_adapter(cmd)
    text = adapter.help_text("cmd", "the command")
    assert "Command: cmd" in text
    assert "Usage: cmd" in text
    assert "the command" in text
    assert "the file" in text


def test_dataclass_adapter_usage():
    @dataclass
    class M:
        a: int
        b: Annotated[str, Option(short="b")] = "x"

    adapter = build_adapter(M)
    usage = adapter.usage("m")
    assert "m" in usage
    assert "--a" in usage or "-a" in usage


def test_json_schema_adapter_usage():
    schema = {
        "type": "object",
        "properties": {
            "a": {"type": "integer"},
            "b": {"type": "string"},
        },
        "required": ["a"],
    }
    adapter = build_adapter(schema=schema)
    usage = adapter.usage("m")
    assert "--a" in usage
    assert "--b" in usage


def test_pydantic_adapter_help_text():
    pyd = pytest.importorskip("pydantic")
    from pydantic import BaseModel

    class M(BaseModel):
        a: int

    adapter = build_adapter(M)
    text = adapter.help_text("m", "desc")
    assert "Command: m" in text
    assert "desc" in text


# ---------------------------------------------------------------------------
# CommandLineParser
# ---------------------------------------------------------------------------


def test_command_line_parser_preprocess_handles_backslash_newline():
    out = CommandLineParser.preprocess("a\\\nb")
    assert out == "a b"


def test_command_line_parser_preprocess_handles_backslash_cr():
    out = CommandLineParser.preprocess("a\\\r\nb")
    assert out == "a b"


def test_command_line_parser_preprocess_no_change_when_no_continuation():
    assert CommandLineParser.preprocess("plain") == "plain"


def test_command_line_parser_split_chain_semicolon():
    out = CommandLineParser.split_chain("a ; b ; c")
    assert [s.command for s in out] == ["a", "b", "c"]
    assert [s.operator_after for s in out] == [";", ";", None]


def test_command_line_parser_split_chain_double_ampersand():
    out = CommandLineParser.split_chain("a && b && c")
    assert [s.command for s in out] == ["a", "b", "c"]
    assert [s.operator_after for s in out] == ["&&", "&&", None]


def test_command_line_parser_split_chain_double_pipe():
    out = CommandLineParser.split_chain("a || b")
    assert [s.command for s in out] == ["a", "b"]
    assert [s.operator_after for s in out] == ["||", None]


def test_command_line_parser_split_chain_preserves_quoted_operators():
    # A "quoted ; inside" must NOT split on the semicolon.
    out = CommandLineParser.split_chain('echo "a ; b" ; echo c')
    assert [s.command for s in out] == ['echo "a ; b"', "echo c"]


def test_command_line_parser_split_chain_empty():
    assert CommandLineParser.split_chain("") == []


def test_command_line_parser_parser_parts():
    parts = CommandLineParser.parser_parts("grp sub", ["grp", "sub", "x"])
    assert parts == ["sub", "x"]


def test_command_line_parser_parse_returns_preprocessed_string():
    parser = CommandLineParser()
    out = parser.parse("a\\\nb")
    assert out == "a b"


def test_command_line_parser_parse_with_chain_returns_segments():
    parser = CommandLineParser()
    out = parser.parse("a ; b", chain=True)
    assert isinstance(out, list)
    assert all(isinstance(s, ChainSegment) for s in out)


# ---------------------------------------------------------------------------
# CommandParser
# ---------------------------------------------------------------------------


def test_command_parser_parse_positional():
    parser = CommandParser([ArgSpec(name="x", type=str, required=True, positional=True)])
    res = parser.parse("cmd hello")
    assert res.command == "cmd"
    assert res.args == {"x": "hello"}
    assert res.errors == []


def test_command_parser_parse_long_option():
    parser = CommandParser([ArgSpec(name="v", type=bool, is_flag=True)])
    res = parser.parse("cmd --v")
    assert res.args == {"v": True}


def test_command_parser_parse_long_option_with_equals():
    parser = CommandParser([ArgSpec(name="name", type=str)])
    res = parser.parse("cmd --name=alice")
    assert res.args == {"name": "alice"}


def test_command_parser_parse_short_option():
    parser = CommandParser([ArgSpec(name="v", type=bool, short="v", is_flag=True)])
    res = parser.parse("cmd -v")
    assert res.args == {"v": True}


def test_command_parser_parse_short_option_with_inline_value():
    parser = CommandParser([ArgSpec(name="name", type=str, short="n")])
    res = parser.parse("cmd -nalice")
    assert res.args == {"name": "alice"}


def test_command_parser_parse_unknown_long_option():
    parser = CommandParser([])
    res = parser.parse("cmd --xyz")
    assert "unknown option: --xyz" in res.errors


def test_command_parser_parse_unknown_short_option():
    parser = CommandParser([])
    res = parser.parse("cmd -x")
    assert "unknown option: -x" in res.errors


def test_command_parser_parse_missing_value_for_option():
    parser = CommandParser([ArgSpec(name="x", type=str)])
    res = parser.parse("cmd --x")
    assert any("missing value" in e for e in res.errors)


def test_command_parser_parse_repeatable_accumulates_list():
    parser = CommandParser([ArgSpec(name="tag", type=str, repeatable=True)])
    res = parser.parse("cmd --tag a --tag b")
    assert res.args == {"tag": ["a", "b"]}


def test_command_parser_parse_repeatable_with_no_prior_value_creates_list():
    parser = CommandParser([ArgSpec(name="tag", type=str, repeatable=True)])
    res = parser.parse("cmd --tag a")
    assert res.args == {"tag": ["a"]}


def test_command_parser_parse_nargs_collects_multiple():
    parser = CommandParser([ArgSpec(name="coord", type=str, nargs=2)])
    res = parser.parse("cmd --coord 1 2")
    assert res.args == {"coord": ["1", "2"]}


def test_command_parser_parse_nargs_insufficient_errors():
    parser = CommandParser([ArgSpec(name="coord", type=str, nargs=2)])
    res = parser.parse("cmd --coord 1")
    assert any("missing value" in e for e in res.errors)


def test_command_parser_parse_unexpected_positional():
    parser = CommandParser([ArgSpec(name="x", type=str, required=True, positional=True)])
    res = parser.parse("cmd a b")
    assert any("unexpected positional" in e for e in res.errors)


def test_command_parser_parse_empty_input():
    parser = CommandParser([])
    res = parser.parse("")
    assert res.command == ""
    assert res.args == {}


def test_command_parser_parse_tokens_with_raw():
    parser = CommandParser([ArgSpec(name="x", type=str, positional=True)])
    res = parser.parse_tokens(["cmd", "hello"], raw="cmd hello")
    assert res.raw == "cmd hello"
    assert res.command == "cmd"


# ---------------------------------------------------------------------------
# CommandMatcher
# ---------------------------------------------------------------------------


def _make_matcher(commands_specs):
    """Helper: build a CommandMatcher with a controllable command map."""
    from agenticli.types import CommandSpec

    class _FakeReg:
        def __init__(self):
            self._cmds: dict[str, CommandSpec] = {}

        def _ensure_help_command(self):
            pass

        def _resolve_command(self, parts):
            if not parts:
                return "", None
            for n, s in self._cmds.items():
                if n == parts[0]:
                    return n, s
            return parts[0], None

    reg = _FakeReg()
    for name, spec in commands_specs.items():
        reg._cmds[name] = spec
    return CommandMatcher(reg._cmds, reg._resolve_command, reg._ensure_help_command)


def test_command_matcher_exact():
    spec = CommandSpec(name="hello", description="d", func=lambda: None)
    matcher = _make_matcher({"hello": spec})
    hit = matcher.match("hello")
    assert hit.command == "hello"
    assert hit.match_type == "exact"
    assert hit.confidence == 1.0


def test_command_matcher_invalid_mode_raises():
    matcher = _make_matcher({})
    with pytest.raises(ValueError, match="mode"):
        matcher.match("anything", mode="weird")


def test_command_matcher_natural_mention_returns_command():
    spec = CommandSpec(
        name="weather",
        description="d",
        func=lambda: None,
        args=[ArgSpec(name="city", type=str)],
    )
    matcher = _make_matcher({"weather": spec})
    hit = matcher.match_natural("what's the weather in tokyo?")
    assert hit.command == "weather"
    assert hit.confidence == 0.9


def test_command_matcher_natural_no_match():
    matcher = _make_matcher({})
    hit = matcher.match_natural("nothing here")
    assert hit.command is None
    assert hit.confidence == 0.0


def test_command_matcher_chain():
    spec = CommandSpec(name="a", description="d", func=lambda: None)
    spec2 = CommandSpec(name="b", description="d", func=lambda: None)
    matcher = _make_matcher({"a": spec, "b": spec2})
    hits = matcher.match("a ; b", chain=True)
    assert [h.command for h in hits] == ["a", "b"]


def test_command_matcher_chain_short_circuits_on_unknown_with_ampersand():
    """When a segment fails to match and the operator after it is
    ``&&`` or ``||``, the matcher stops iterating (short-circuits)."""
    spec = CommandSpec(name="a", description="d", func=lambda: None)
    matcher = _make_matcher({"a": spec})
    # "missing1 && missing2 && a" — first segment fails AND the operator
    # after it is "&&", so the chain short-circuits and only the first
    # hit is returned.
    hits = matcher.match("missing1 && missing2 && a", chain=True)
    assert len(hits) == 1
    assert hits[0].command is None

    # Without the short-circuit, "a ; missing ; a" returns all three.
    hits_full = matcher.match("a ; missing ; a", chain=True)
    assert len(hits_full) == 3


def test_command_matcher_slash_form():
    spec = CommandSpec(name="hello", description="d", func=lambda: None)
    matcher = _make_matcher({"hello": spec})
    hit = matcher.match("/hello")
    assert hit.command == "hello"
    assert hit.match_type == "slash"


def test_command_matcher_empty_text():
    matcher = _make_matcher({})
    hit = matcher.match("")
    assert hit.command is None
    assert hit.confidence == 0.0


# ---------------------------------------------------------------------------
# CommandFactory
# ---------------------------------------------------------------------------


def test_command_factory_from_CliCommand_instance():
    class Cmd(CliCommand):
        name = "fc"
        description = "d"

        async def run(self):
            return 1

    spec = CommandFactory.from_target(Cmd())
    assert isinstance(spec, CommandSpec)
    assert spec.name == "fc"


def test_command_factory_from_CliCommand_class():
    class Cmd(CliCommand):
        name = "fc2"
        description = "d"

        async def run(self):
            return 1

    spec = CommandFactory.from_target(Cmd)
    assert isinstance(spec, CommandSpec)
    assert spec.name == "fc2"


def test_command_factory_from_command_spec_decorated_function():
    @command(name="fcd")
    def myfn() -> str:
        return "x"

    spec = CommandFactory.from_target(myfn)
    assert spec.name == "fcd"


def test_command_factory_from_schema_tool():
    class Tool:
        name = "ts"
        description = "td"
        parameters = {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}

        def execute(self, q):
            return q

    spec = CommandFactory.from_target(Tool())
    assert spec.name == "ts"


def test_command_factory_rejects_unsupported():
    with pytest.raises(TypeError, match="Unsupported command target"):
        CommandFactory.from_target(42)


# ---------------------------------------------------------------------------
# @command: every parameter
# ---------------------------------------------------------------------------


def test_command_name_defaults_to_function_name():
    @command
    def myfunc(value: Annotated[str, Option(positional=True)]) -> str:
        return value

    assert myfunc.__command_spec__.name == "myfunc"


def test_command_explicit_name_overrides_function_name():
    @command(name="explicit")
    def myfunc(value: Annotated[str, Option(positional=True)]) -> str:
        return value

    assert myfunc.__command_spec__.name == "explicit"


def test_command_description_from_kwarg():
    @command(description="the desc")
    def f() -> str:
        return ""

    assert f.__command_spec__.description == "the desc"


def test_command_description_from_docstring_when_no_kwarg():
    @command
    def f() -> str:
        """docstring desc"""
        return ""

    assert f.__command_spec__.description == "docstring desc"


def test_command_description_empty_when_neither_kwarg_nor_docstring():
    @command
    def f() -> str:
        return ""

    assert f.__command_spec__.description == ""


def test_command_aliases_kwarg():
    @command(name="a", aliases=["b", "c"])
    def a() -> str:
        return "a"

    assert a.__command_spec__.aliases == ["b", "c"]


def test_command_aliases_default_empty():
    @command(name="a")
    def a() -> str:
        return "a"

    assert a.__command_spec__.aliases == []


def test_command_hidden_kwarg():
    @command(name="h", hidden=True)
    def h() -> str:
        return "h"

    assert h.__command_spec__.hidden is True


def test_command_deprecated_kwarg():
    @command(name="d", deprecated="use new")
    def d() -> str:
        return "d"

    assert d.__command_spec__.deprecated == "use new"


def test_command_include_in_prompt_default_True():
    @command(name="d")
    def d() -> str:
        return "d"

    spec = d.__command_spec__
    assert spec.include_in_prompt is True
    assert getattr(spec, "_include_in_prompt_explicit", False) is False


def test_command_include_in_prompt_explicit_True_flagged():
    @command(name="d", include_in_prompt=True)
    def d() -> str:
        return "d"

    spec = d.__command_spec__
    assert spec.include_in_prompt is True
    assert getattr(spec, "_include_in_prompt_explicit", False) is True


def test_command_include_in_prompt_explicit_False():
    @command(name="d", include_in_prompt=False)
    def d() -> str:
        return "d"

    spec = d.__command_spec__
    assert spec.include_in_prompt is False
    assert getattr(spec, "_include_in_prompt_explicit", False) is True


# ---------------------------------------------------------------------------
# @command_group
# ---------------------------------------------------------------------------


def test_command_group_default_register_as_command_true_with_name():
    @command_group(name="g", description="d")
    class G:
        pass

    info = G.__command_group__
    assert info["name"] == "g"
    assert info["register_as_command"] is True


def test_command_group_empty_name_defaults_to_namespace_mode():
    @command_group()
    class G:
        pass

    assert G.__command_group__["name"] == ""
    assert G.__command_group__["register_as_command"] is False


def test_command_group_explicit_register_as_command_false_overrides_name():
    @command_group(name="g", register_as_command=False)
    class G:
        pass

    assert G.__command_group__["register_as_command"] is False


def test_command_group_register_as_command_true_requires_name():
    with pytest.raises(ValueError, match="non-empty"):
        @command_group(name="", register_as_command=True)
        class G:
            pass


def test_command_group_include_in_prompt_default_true():
    @command_group()
    class G:
        pass

    assert G.__command_group__["include_in_prompt"] is True


# ---------------------------------------------------------------------------
# command_from_method
# ---------------------------------------------------------------------------


def test_command_from_method_uses_class_when_target_is_class():
    class Service:
        def run(self) -> int:
            return 99

    spec = command_from_method("svc", Service, "run")
    assert spec.name == "svc"
    assert "self" not in {a.name for a in spec.args}


def test_command_from_method_uses_instance_when_target_is_instance():
    class Service:
        def __init__(self):
            self.value = 42

        def run(self) -> int:
            return self.value

    inst = Service()
    spec = command_from_method("svc", inst, "run")
    assert spec.source == "method"


def test_command_from_method_unknown_method_raises():
    class Service:
        pass

    with pytest.raises(AttributeError):
        command_from_method("svc", Service, "nope")


def test_command_from_method_non_callable_attr_raises():
    class Service:
        not_a_method = 1

    with pytest.raises(TypeError, match="not callable"):
        command_from_method("svc", Service, "not_a_method")


def test_command_from_method_all_kwargs_propagate():
    class Service:
        def run(self) -> int:
            return 1

    spec = command_from_method(
        "svc",
        Service,
        "run",
        description="desc",
        aliases=["s"],
        hidden=True,
        deprecated="old",
        include_in_prompt=False,
    )
    assert spec.description == "desc"
    assert spec.aliases == ["s"]
    assert spec.hidden is True
    assert spec.deprecated == "old"
    assert spec.include_in_prompt is False
    assert getattr(spec, "_include_in_prompt_explicit", False) is True


# ---------------------------------------------------------------------------
# command_from_model
# ---------------------------------------------------------------------------


def test_command_from_model_dataclass():
    @dataclass
    class M:
        x: Annotated[int, Option(positional=True)]

    def handler(x: int) -> int:
        return x * 2

    spec = command_from_model("mdl", M, handler)
    assert spec.source == "model"
    assert any(a.name == "x" for a in spec.args)


def test_command_from_model_pydantic():
    pyd = pytest.importorskip("pydantic")
    from pydantic import BaseModel

    class M(BaseModel):
        x: int

    def handler(x: int) -> int:
        return x

    spec = command_from_model("pym", M, handler)
    assert spec.source == "model"


def test_command_from_model_unsupported_type_raises():
    with pytest.raises(TypeError, match="dataclass or Pydantic"):
        command_from_model("bad", int, lambda: None)


def test_command_from_model_async_handler():
    @dataclass
    class M:
        x: int

    async def handler(x: int) -> int:
        return x + 1

    spec = command_from_model("asyncmdl", M, handler)
    registry = CommandRegistry()
    registry.register_spec(spec)
    out = registry.execute("asyncmdl --x 4").value
    assert out == 5


def test_command_from_model_kwargs_propagate():
    @dataclass
    class M:
        x: int

    def handler(x: int) -> int:
        return x

    spec = command_from_model(
        "m", M, handler,
        description="d", aliases=["a"], hidden=True, deprecated="x", include_in_prompt=False,
    )
    assert spec.description == "d"
    assert spec.aliases == ["a"]
    assert spec.hidden is True
    assert spec.deprecated == "x"
    assert spec.include_in_prompt is False
    assert getattr(spec, "_include_in_prompt_explicit", False) is True


# ---------------------------------------------------------------------------
# CliCommand
# ---------------------------------------------------------------------------


def test_CliCommand_class_executes():
    @dataclass
    class Args:
        x: Annotated[int, Option(positional=True)]

    class Cmd(CliCommand):
        name = "cc"
        description = "d"
        args_model = Args

        async def run(self, x: int) -> int:
            return x + 1

    registry = CommandRegistry()
    registry.register(Cmd())
    assert registry.execute("cc 10").value == 11


def test_CliCommand_defaults():
    cmd = CliCommand()
    assert cmd.name == ""
    assert cmd.description == ""
    assert cmd.aliases == []
    assert cmd.args_model is None
    assert cmd.hidden is False
    assert cmd.deprecated is None
    assert cmd.include_in_prompt is True


def test_CliCommand_run_not_implemented():
    with pytest.raises(NotImplementedError):
        asyncio.run(CliCommand().run())


def test_CliCommand_name_falls_back_to_class_name():
    class MyCommand(CliCommand):
        description = "d"
        args_model = None

        async def run(self):
            return None

    spec = MyCommand().to_command_spec()
    assert spec.name == "my"


# ---------------------------------------------------------------------------
# CommandRegistry.register / register_spec
# ---------------------------------------------------------------------------


def test_register_rejects_non_target():
    registry = CommandRegistry()
    with pytest.raises(TypeError):
        registry.register(42)


def test_register_spec_rejects_name_collision():
    @command(name="dup")
    def dup() -> str:
        return "1"

    @command(name="dup")
    def dup2() -> str:
        return "2"

    registry = CommandRegistry()
    registry.register(dup)
    # Different spec object with the same name → ValueError.
    with pytest.raises(ValueError, match="already registered"):
        registry.register_spec(dup2.__command_spec__)


def test_register_spec_rejects_alias_collision():
    @command(name="x1", aliases=["a"])
    def x1() -> str:
        return "1"

    @command(name="x2", aliases=["a"])
    def x2() -> str:
        return "2"

    registry = CommandRegistry()
    registry.register(x1)
    with pytest.raises(ValueError, match="alias already registered"):
        registry.register_spec(x2.__command_spec__)


def test_register_spec_allows_reregistering_same_spec():
    @command(name="self")
    def self_cmd() -> str:
        return "x"

    registry = CommandRegistry()
    registry.register(self_cmd)
    # re-registering the same spec object should be a no-op (same identity).
    registry.register_spec(self_cmd.__command_spec__)
    assert registry.execute("self").value == "x"


# ---------------------------------------------------------------------------
# CommandRegistry.unregister / get / has
# ---------------------------------------------------------------------------


def test_unregister_drops_command_and_aliases():
    @command(name="u", aliases=["u1", "u2"])
    def u() -> str:
        return "u"

    registry = CommandRegistry()
    registry.register(u)
    assert registry.has("u") and registry.has("u1") and registry.has("u2")

    registry.unregister("u")
    assert not registry.has("u")
    assert not registry.has("u1")
    assert not registry.has("u2")


def test_unregister_missing_is_no_op():
    registry = CommandRegistry()
    # Should not raise.
    registry.unregister("does-not-exist")


def test_get_returns_spec_or_None():
    @command(name="g")
    def g() -> str:
        return "g"

    registry = CommandRegistry()
    registry.register(g)
    assert registry.get("g") is g.__command_spec__
    assert registry.get("nope") is None


# ---------------------------------------------------------------------------
# CommandRegistry.parse
# ---------------------------------------------------------------------------


def test_parse_returns_none_for_empty():
    registry = CommandRegistry()
    assert registry.parse("") is None


def test_parse_returns_help_for_dash_dash_help():
    @command(name="hi")
    def hi() -> str:
        return "hi"

    registry = CommandRegistry()
    registry.register(hi)
    res = registry.parse("--help hi")
    assert res is not None
    assert res.command == "--help"
    assert res.args == {"command": "hi"}


def test_parse_returns_help_when_trailing_help():
    @command(name="hi")
    def hi() -> str:
        return "hi"

    registry = CommandRegistry()
    registry.register(hi)
    res = registry.parse("hi --help")
    assert res is not None
    assert res.command == "--help"


def test_parse_returns_None_for_unknown():
    registry = CommandRegistry()
    assert registry.parse("zzz") is None


def test_parse_returns_ParseResult_for_normal():
    @command(name="calc")
    def calc(x: Annotated[int, Option(positional=True)]) -> int:
        return x

    registry = CommandRegistry()
    registry.register(calc)
    res = registry.parse("calc 5")
    assert res is not None
    assert res.command == "calc"
    assert res.args == {"x": "5"}


def test_parse_quoting_preserves_spaces():
    @command(name="echo")
    def echo(value: Annotated[str, Option(positional=True)]) -> str:
        return value

    registry = CommandRegistry()
    registry.register(echo)
    res = registry.parse('echo "hello world"')
    assert res is not None
    assert res.args == {"value": "hello world"}


def test_parse_chain_returns_list():
    @command(name="a")
    def a() -> int:
        return 1

    @command(name="b")
    def b() -> int:
        return 2

    registry = CommandRegistry()
    registry.register(a)
    registry.register(b)
    res = registry.parse("a ; b", chain=True)
    assert isinstance(res, list)
    assert [r.command for r in res] == ["a", "b"]


# ---------------------------------------------------------------------------
# CommandRegistry.execute
# ---------------------------------------------------------------------------


def test_execute_returns_empty_command_error():
    registry = CommandRegistry()
    r = registry.execute("")
    assert r.ok is False
    assert r.error.code == "empty_command"


def test_execute_returns_parse_error_for_unclosed_quote():
    registry = CommandRegistry()
    r = registry.execute('echo "abc')
    assert r.ok is False
    assert r.error.code == "parse_error"


def test_execute_returns_unknown_command_with_suggestion():
    @command(name="echo", description="e")
    def echo_cmd() -> str:
        return "e"

    registry = CommandRegistry()
    registry.register(echo_cmd)
    r = registry.execute("ehco")
    assert r.ok is False
    assert r.error.code == "unknown_command"
    assert r.error.suggestion == "echo"


def test_execute_slash_stripped():
    @command(name="hi")
    def hi() -> str:
        return "hi"

    registry = CommandRegistry()
    registry.register(hi)
    assert registry.execute("/hi").value == "hi"


def test_execute_help_short_circuit():
    @command(name="x")
    def x() -> str:
        return "x"

    registry = CommandRegistry()
    registry.register(x)
    r = registry.execute("--help x")
    assert r.ok is True
    assert "Command: x" in r.value


def test_execute_async_returns_same_value():
    @command(name="ax")
    def ax() -> int:
        return 1

    registry = CommandRegistry()
    registry.register(ax)
    r = asyncio.run(registry.execute_async("ax"))
    assert r.ok
    assert r.value == 1


def test_execute_async_handles_awaitable_handler_return():
    @command(name="ax2")
    def ax2() -> Any:
        async def coro():
            return "async-result"

        return coro()

    registry = CommandRegistry()
    registry.register(ax2)
    r = asyncio.run(registry.execute_async("ax2"))
    assert r.ok
    assert r.value == "async-result"


def test_execute_returns_list_when_chain():
    @command(name="p")
    def p() -> int:
        return 1

    @command(name="q")
    def q() -> int:
        return 2

    registry = CommandRegistry()
    registry.register(p)
    registry.register(q)
    r = registry.execute("p ; q", chain=True)
    assert isinstance(r, list)
    assert r == [1, 2]


def test_execute_runtime_error_wrapped_in_CommandError():
    @command(name="boom")
    def boom() -> str:
        raise ValueError("nope")

    registry = CommandRegistry()
    registry.register(boom)
    r = registry.execute("boom")
    assert r.ok is False
    assert r.error.code == "execution_error"


# ---------------------------------------------------------------------------
# CommandRegistry.match
# ---------------------------------------------------------------------------


def test_match_returns_HitResult():
    @command(name="a")
    def a() -> str:
        return "a"

    registry = CommandRegistry()
    registry.register(a)
    hit = registry.match("a")
    assert isinstance(hit, HitResult)
    assert hit.command == "a"


def test_match_chain_returns_list():
    @command(name="a")
    def a() -> str:
        return "a"

    registry = CommandRegistry()
    registry.register(a)
    hits = registry.match("a ; a", chain=True)
    assert isinstance(hits, list)
    assert len(hits) == 2


# ---------------------------------------------------------------------------
# CommandRegistry: help / render_llm_context / commands / len / contains
# ---------------------------------------------------------------------------


def test_help_lists_all_top_level():
    @command(name="p", description="p cmd")
    def p() -> str:
        return "p"

    @command(name="q", description="q cmd", hidden=True)
    def q() -> str:
        return "q"

    registry = CommandRegistry()
    registry.register(p)
    registry.register(q)
    out = registry.help()
    assert "p:" in out
    assert "q:" not in out  # hidden


def test_help_for_specific_command_includes_aliases():
    @command(name="kx", aliases=["k"], description="kx")
    def kx() -> str:
        return "kx"

    registry = CommandRegistry()
    registry.register(kx)
    out = registry.help("kx")
    assert "Command: kx" in out
    assert "Aliases:" in out
    assert "k" in out


def test_help_for_unknown_command():
    registry = CommandRegistry()
    out = registry.help("nope")
    assert "Unknown command" in out


def test_help_for_prefix_match():
    @command(name="weather")
    def w() -> str:
        return "w"

    registry = CommandRegistry()
    registry.register(w)
    out = registry.help("weath")
    assert "Command: weather" in out


def test_help_for_deprecated_shows_notice():
    @command(name="old", description="d", deprecated="use new")
    def old() -> str:
        return "old"

    registry = CommandRegistry()
    registry.register(old)
    out = registry.help("old")
    assert "Deprecated" in out


def test_help_for_group_shows_subcommands():
    @command_group(name="g", description="gdesc")
    class G:
        @command(name="s1", description="s1 desc")
        def s1(self) -> str:
            return "s1"

    registry = CommandRegistry()
    registry.register(G())
    out = registry.help("g")
    assert "Subcommands:" in out
    assert "s1:" in out


def test_help_for_empty_registry():
    registry = CommandRegistry()
    out = registry.help()
    assert "Available commands:" in out


def test_render_llm_context_excludes_hidden():
    @command(name="v", description="visible")
    def v() -> str:
        return "v"

    @command(name="h", description="hidden", hidden=True)
    def h() -> str:
        return "h"

    registry = CommandRegistry()
    registry.register(v)
    registry.register(h)
    ctx = registry.render_llm_context()
    assert "v:" in ctx
    assert "h:" not in ctx


def test_render_llm_context_excludes_include_in_prompt_false():
    @command(name="v", description="visible", include_in_prompt=False)
    def v() -> str:
        return "v"

    registry = CommandRegistry()
    registry.register(v)
    ctx = registry.render_llm_context()
    assert "v:" not in ctx


def test_render_llm_context_detailed_includes_usage():
    @command(name="v", description="d")
    def v(x: Annotated[int, Option(positional=True)]) -> int:
        return x

    registry = CommandRegistry()
    registry.register(v)
    ctx = registry.render_llm_context(detailed=True)
    assert "v <" in ctx


def test_render_llm_context_empty_registry():
    """An empty registry still has the built-in --help command, so the
    prompt includes the standard invocation hint."""
    registry = CommandRegistry()
    out = registry.render_llm_context()
    assert "Use <command> --help" in out
    assert "exec --command" in out


def test_commands_property_excludes_help_only():
    """``commands`` excludes only the built-in ``--help``; the hidden
    flag is enforced at the help/prompt level, not at the property
    level. This pins the actual behavior so the contract doesn't drift."""
    @command(name="v")
    def v() -> str:
        return "v"

    @command(name="h", hidden=True)
    def h() -> str:
        return "h"

    registry = CommandRegistry()
    registry.register(v)
    registry.register(h)
    cmds = registry.commands
    assert "v" in cmds
    assert "h" in cmds  # hidden is excluded from help(), not from .commands
    assert "--help" not in cmds


def test_len_returns_visible_count():
    @command(name="a")
    def a() -> str:
        return "a"

    registry = CommandRegistry()
    assert len(registry) == 0
    registry.register(a)
    assert len(registry) == 1


def test_contains_returns_bool():
    @command(name="a")
    def a() -> str:
        return "a"

    registry = CommandRegistry()
    registry.register(a)
    assert "a" in registry
    assert "z" not in registry


# ---------------------------------------------------------------------------
# CommandRegistry: to_dict / from_dict
# ---------------------------------------------------------------------------


def test_registry_to_dict_excludes_builtin_help():
    @command(name="a", description="d")
    def a() -> str:
        return "a"

    registry = CommandRegistry()
    registry.register(a)
    data = registry.to_dict()
    assert any(entry["name"] == "a" for entry in data)
    assert all(not entry["name"].startswith("--") for entry in data)


def test_registry_from_dict_registers_all_specs():
    @command(name="a", description="d")
    def a() -> str:
        return "a"

    registry = CommandRegistry()
    registry.register(a)
    data = registry.to_dict()

    registry2 = CommandRegistry()
    sentinel = lambda **kwargs: "RESTORED"  # noqa: E731
    specs = registry2.from_dict(data, func_resolver=lambda n, p: sentinel)
    assert any(s.name == "a" for s in specs)
    assert registry2.execute("a").value == "RESTORED"


# ---------------------------------------------------------------------------
# Adapters: wrap_tool / wrap_langchain_tool / wrap_autogen_tool / wrap_openai_tool_schema
# ---------------------------------------------------------------------------


def test_wrap_tool_basic():
    class Tool:
        name = "search"
        description = "search tool"
        parameters = {
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
        }

        async def execute(self, q):
            return f"found:{q}"

    spec = wrap_tool(Tool())
    assert spec.name == "search"
    assert spec.source == "wrapped-tool"

    registry = CommandRegistry()
    registry.register_spec(spec)
    assert registry.execute("search --q hello").value == "found:hello"


def test_wrap_tool_missing_execute_raises():
    class Tool:
        name = "x"

    with pytest.raises(TypeError, match="execute"):
        wrap_tool(Tool())


def test_wrap_tool_with_callable_schema():
    class Tool:
        name = "cs"
        description = "cs"

        def parameters(self):
            return {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}

        async def execute(self, q):
            return q

    spec = wrap_tool(Tool())
    assert spec.name == "cs"
    assert any(a.name == "q" for a in spec.args)


def test_wrap_langchain_tool_uses_invoke():
    class LCTool:
        name = "lc"
        description = "lc"
        args_schema = None  # No schema → empty args allowed

        def invoke(self, kwargs):
            return f"invoked:{kwargs}"

    spec = wrap_langchain_tool(LCTool())
    assert spec.source == "langchain-tool"
    registry = CommandRegistry()
    registry.register_spec(spec)
    assert registry.execute("lc").value.startswith("invoked")


def test_wrap_langchain_tool_uses_ainvoke_when_present():
    class LCTool:
        name = "lca"
        description = "lca"

        async def ainvoke(self, kwargs):
            return "async-result"

    spec = wrap_langchain_tool(LCTool())
    registry = CommandRegistry()
    registry.register_spec(spec)
    assert registry.execute("lca").value == "async-result"


def test_wrap_langchain_tool_uses_arun():
    class LCTool:
        name = "lcr"
        description = "lcr"

        async def arun(self, **kwargs):
            return "arun"

    spec = wrap_langchain_tool(LCTool())
    registry = CommandRegistry()
    registry.register_spec(spec)
    assert registry.execute("lcr").value == "arun"


def test_wrap_langchain_tool_uses_run():
    class LCTool:
        name = "lcrun"
        description = "lcrun"

        def run(self, **kwargs):
            return "run-result"

    spec = wrap_langchain_tool(LCTool())
    registry = CommandRegistry()
    registry.register_spec(spec)
    assert registry.execute("lcrun").value == "run-result"


def test_wrap_langchain_tool_uses_func():
    class LCTool:
        name = "lcf"
        description = "lcf"

        def func(self, **kwargs):
            return "func-result"

    spec = wrap_langchain_tool(LCTool())
    registry = CommandRegistry()
    registry.register_spec(spec)
    assert registry.execute("lcf").value == "func-result"


def test_wrap_langchain_tool_no_supported_method_raises_at_execute():
    class LCTool:
        name = "broken"
        description = "b"

    spec = wrap_langchain_tool(LCTool())
    registry = CommandRegistry()
    registry.register_spec(spec)
    # The error is raised at execution time, not at wrap time — the
    # wrap-time surface is `args_schema` lookup; the runtime surface is
    # dispatching to invoke/arun/run/func.
    r = registry.execute("broken")
    assert r.ok is False
    assert r.error.code == "execution_error"
    assert "Unsupported LangChain" in r.error.message


def test_wrap_langchain_tool_missing_name_raises():
    class LCTool:
        pass

    with pytest.raises(TypeError, match="name"):
        wrap_langchain_tool(LCTool())


def test_wrap_langchain_tool_with_tool_call_schema():
    """``tool_call_schema`` is used as the args source when ``args_schema``
    is None. The schema must be a dataclass or Pydantic model — the
    library passes it to ``build_adapter``."""
    @dataclass
    class Schema:
        query: Annotated[str, Option(positional=True)]

    class LCTool:
        name = "lc2"
        description = "lc2"
        tool_call_schema = Schema  # class only, args_schema is None

        def run(self, **kwargs):
            return f"got:{kwargs}"

    spec = wrap_langchain_tool(LCTool())
    assert spec.name == "lc2"
    # The schema is now the args source.
    assert any(a.name == "query" for a in spec.args)


def test_wrap_autogen_tool_basic():
    class AUTool:
        schema = {
            "name": "au",
            "description": "au tool",
            "parameters": {
                "type": "object",
                "properties": {"q": {"type": "string"}},
                "required": ["q"],
            },
        }

        def func(self, **kwargs):
            return f"au:{kwargs}"

    spec = wrap_autogen_tool(AUTool())
    assert spec.source == "autogen-tool"

    registry = CommandRegistry()
    registry.register_spec(spec)
    assert registry.execute("au --q hi").value == "au:{'q': 'hi'}"


def test_wrap_autogen_tool_uses_run_json():
    class AUTool:
        schema = {
            "name": "aujson",
            "description": "aujson",
            "parameters": {"type": "object", "properties": {}},
        }

        def run_json(self, args, cancellation_token=None):
            return "via-run-json"

    spec = wrap_autogen_tool(AUTool())
    registry = CommandRegistry()
    registry.register_spec(spec)
    assert registry.execute("aujson").value == "via-run-json"


def test_wrap_autogen_tool_uses__func():
    class AUTool:
        schema = {
            "name": "auf",
            "description": "auf",
            "parameters": {"type": "object", "properties": {}},
        }

        def _func(self, **kwargs):
            return "via-_func"

    spec = wrap_autogen_tool(AUTool())
    registry = CommandRegistry()
    registry.register_spec(spec)
    assert registry.execute("auf").value == "via-_func"


def test_wrap_autogen_tool_missing_schema_raises():
    class AUTool:
        name = "broken"

    with pytest.raises(TypeError, match="schema"):
        wrap_autogen_tool(AUTool())


def test_wrap_autogen_tool_schema_missing_parameters_raises():
    class AUTool:
        schema = {"name": "x"}

    with pytest.raises(TypeError, match="parameters"):
        wrap_autogen_tool(AUTool())


def test_wrap_openai_tool_schema_basic():
    def handler(q: str) -> str:
        return f"oai:{q}"

    spec = wrap_openai_tool_schema(
        name="oai",
        parameters={
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
        },
        handler=handler,
        description="oai",
    )
    assert spec.source == "openai-tool-schema"
    registry = CommandRegistry()
    registry.register_spec(spec)
    assert registry.execute("oai --q x").value == "oai:x"


def test_wrap_openai_tool_schema_non_callable_handler_raises():
    with pytest.raises(TypeError, match="callable"):
        wrap_openai_tool_schema(
            name="x",
            parameters={"type": "object", "properties": {}},
            handler=42,
        )


def test_wrap_openai_tool_schema_async_handler():
    async def handler(**kwargs):
        return "async-handler"

    spec = wrap_openai_tool_schema(
        name="oaa",
        parameters={"type": "object", "properties": {}},
        handler=handler,
    )
    registry = CommandRegistry()
    registry.register_spec(spec)
    assert registry.execute("oaa").value == "async-handler"


# ---------------------------------------------------------------------------
# ExecTool
# ---------------------------------------------------------------------------


def test_exec_tool_construction():
    def cb(cmd, **kwargs):
        return f"got:{cmd}"

    tool = ExecTool(callback=cb)
    assert tool.name == "exec"
    assert "command" in tool.parameters["properties"]


def test_exec_tool_execute_sync_callback():
    captured = []

    def cb(cmd, **kwargs):
        captured.append((cmd, kwargs))
        return "sync-ok"

    tool = ExecTool(callback=cb)
    res = asyncio.run(tool.execute(command="ls"))
    assert res == "sync-ok"
    assert captured == [("ls", {})]


def test_exec_tool_execute_async_callback():
    async def cb(cmd, **kwargs):
        return f"async:{cmd}"

    tool = ExecTool(callback=cb)
    res = asyncio.run(tool.execute(command="ls"))
    assert res == "async:ls"


def test_exec_tool_execute_without_command():
    captured = []

    def cb(**kwargs):
        captured.append(kwargs)
        return "no-cmd"

    tool = ExecTool(callback=cb)
    res = asyncio.run(tool.execute(timeout=10))
    assert res == "no-cmd"
    assert captured == [{"timeout": 10}]


def test_exec_tool_to_schema():
    tool = ExecTool(callback=lambda c: c)
    schema = tool.to_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "exec"
    assert "command" in schema["function"]["parameters"]["properties"]


def test_exec_tool_via_wrap_tool():
    captured = []

    def cb(cmd, **kwargs):
        captured.append((cmd, kwargs))
        return f"wrap:{cmd}"

    tool = ExecTool(callback=cb)
    spec = wrap_tool(tool)
    registry = CommandRegistry()
    registry.register_spec(spec)
    out = registry.execute("exec pytest --timeout 5").value
    assert out == "wrap:pytest"
    # The callback received both the command and the timeout kwarg
    # (timeout is JSON-schema-typed as integer, so it arrives coerced).
    assert captured == [("pytest", {"timeout": 5})]


# ---------------------------------------------------------------------------
# discover internals (low-level, before any registry binding)
# ---------------------------------------------------------------------------


def test_iter_module_specs_skips_underscore_files(tmp_path):
    (tmp_path / "_skip.py").write_text("x = 1")
    (tmp_path / "ok.py").write_text("x = 1")
    (tmp_path / ".hidden.py").write_text("x = 1")

    specs = list(iter_module_specs(tmp_path))
    names = [p.name for p, _ in specs]
    assert "ok.py" in names
    assert "_skip.py" not in names
    assert ".hidden.py" not in names


def test_iter_module_specs_skips_pycache(tmp_path):
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "old.py").write_text("x = 1")
    (tmp_path / "live.py").write_text("x = 1")

    specs = list(iter_module_specs(tmp_path))
    names = [p.name for p, _ in specs]
    assert "live.py" in names
    assert "old.py" not in names


def test_iter_module_specs_non_recursive(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "inner.py").write_text("x = 1")
    (tmp_path / "outer.py").write_text("x = 1")

    specs = list(iter_module_specs(tmp_path, recursive=False))
    names = [p.name for p, _ in specs]
    assert "outer.py" in names
    assert "inner.py" not in names


def test_iter_module_specs_with_package_dotted_names(tmp_path, monkeypatch):
    pkg = tmp_path / "p"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "mod.py").write_text("x = 1")

    monkeypatch.syspath_prepend(str(tmp_path))

    specs = list(iter_module_specs(pkg, package="p"))
    for path, dotted in specs:
        if path.name == "mod.py":
            assert dotted == "p.mod"


def test_iter_module_specs_nonexistent_dir_yields_nothing(tmp_path):
    assert list(iter_module_specs(tmp_path / "missing")) == []


def test_iter_command_classes_excludes_re_exports():
    import types

    @command_group()
    class Local:
        pass

    # Fake module that *defines* Local.
    mod = types.ModuleType("fake_mod")
    mod.Local = Local
    # Force __module__ so the class looks like it was defined in `mod`.
    Local.__module__ = "fake_mod"

    classes = list(iter_command_classes(mod))
    assert Local in classes

    # Re-exported name: same class, but __module__ differs.
    other = types.ModuleType("other")
    other.Local = Local
    Local.__module__ = "other"  # simulate a re-import
    assert list(iter_command_classes(mod)) == []
    # Restore for any later tests (though pytest may have isolated it).
    Local.__module__ = "fake_mod"


def test_build_target_no_provider_returns_class():
    class C:
        pass

    assert build_target(C, None) is C


def test_build_target_with_provider():
    class C:
        pass

    sentinel = object()
    assert build_target(C, lambda cls: sentinel) is sentinel


def test_discover_raises_without_register():
    with pytest.raises(TypeError, match="register="):
        discover("/tmp")


def test_discover_invalid_on_error_raises():
    with pytest.raises(ValueError, match="on_error"):
        discover("/tmp", on_error="bad", register=lambda t: None)


def test_discover_collects_errors_in_ignore_mode(tmp_path):
    (tmp_path / "broken.py").write_text("raise Exception('boom')")

    captured: list[str] = []
    result = discover(tmp_path, register=lambda t: captured.append(t.name) if hasattr(t, "name") else None, on_error="ignore")
    assert any("boom" in str(e.exception) for e in result.errors)


def test_discover_raise_mode_re_raises(tmp_path):
    (tmp_path / "broken.py").write_text("raise Exception('boom')")

    with pytest.raises(Exception, match="boom"):
        discover(tmp_path, register=lambda t: None, on_error="raise")


def test_DiscoverError_attributes():
    err = DiscoverError(path=__file__, class_name="X", stage="import", exception=ValueError("v"))
    assert err.stage == "import"
    assert err.class_name == "X"


def test_DiscoverResult_defaults():
    res = DiscoverResult()
    assert res.registered == []
    assert res.errors == []


# ---------------------------------------------------------------------------
# run_sync
# ---------------------------------------------------------------------------


def test_run_sync_passthrough_for_non_awaitable():
    sentinel = object()
    assert run_sync(sentinel) is sentinel


def test_run_sync_evaluates_awaitable():
    async def coro():
        return 42

    assert run_sync(coro()) == 42


# ---------------------------------------------------------------------------
# Import surface
# ---------------------------------------------------------------------------


def test_all_exports_are_importable():
    """Pins down the public import surface — anything removed here is a breaking change."""
    from agenticli import (
        ArgSpec, CliCommand, CommandError, CommandRegistry, CommandSpec,
        ExecutionCallbacks, ExecutionContext, ExecutionResult, ExecTool,
        HitResult, Injected, Callback, State, Option, ParseResult,
        command, command_from_method, command_from_model, command_group,
        wrap_autogen_tool, wrap_langchain_tool, wrap_openai_tool_schema, wrap_tool,
    )
    # Smoke: each symbol is bound and not None.
    for sym in (
        ArgSpec, CliCommand, CommandError, CommandRegistry, CommandSpec,
        ExecutionCallbacks, ExecutionContext, ExecutionResult, ExecTool,
        HitResult, Injected, Callback, State, Option, ParseResult,
        command, command_from_method, command_from_model, command_group,
        wrap_autogen_tool, wrap_langchain_tool, wrap_openai_tool_schema, wrap_tool,
    ):
        assert sym is not None


def test_builtin_module_reexports_ExecTool():
    assert builtin_module.ExecTool is BuiltinExecTool
    assert BuiltinExecTool is ExecTool
