# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.3] - 2026-06-03

### Removed (breaking)
- Module-level `_COMMAND_REGISTRY` global. Decorators no longer mutate any global state — `@command` only attaches a `CommandSpec` to the wrapped function, and `@command_group` only marks the class with `__command_group__`. Commands must be registered through `CommandRegistry.register()` to be executable.
- Public functions `get_registered_commands()` and `clear_commands()` have been removed. The exposed API no longer implies a "default registry".
- `command_group` no longer mutates inner `CommandSpec.parent` as a side effect of decoration; parent metadata is set by `CommandRegistry._register_command_group` when the group class is registered.

### Changed
- `@command` decorator now accepts the bare form (`@command`) in addition to `@command(...)`. The parentheses are no longer required when all parameters use their defaults. Existing keyword-argument usage is unchanged.

### Migration
- Replace any direct call to `get_registered_commands()` / `clear_commands()` with `CommandRegistry`-scoped equivalents.
- Before:
  ```python
  @command
  def foo(): ...
  get_registered_commands()  # implicit global lookup
  ```
- After:
  ```python
  @command
  def foo(): ...

  registry = CommandRegistry()
  registry.register(foo)
  list(registry.commands)  # instance-scoped lookup
  ```

## [0.2.2] - 2026-06-03

### Added
- `include_in_prompt: bool = True` field on `CommandSpec` to control whether a command/group appears in `render_llm_context()`. Plumbed through `@command`, `@command_group`, `CliCommand`, `command_from_model`, and `command_from_method`. Hidden from LLM but still visible in `help()` and still executable.
- `example/prompt_filtering.py` demonstrating command-level and group-level prompt filtering.
- `CommandSpec.to_dict()` / `CommandSpec.from_dict()` for JSON-safe serialization of registered commands (callables like `func` and `injection_factories` are excluded; pass a `func_resolver` for roundtrip execution).
- `ArgSpec.to_dict()` / `ArgSpec.from_dict()` companion serialization.
- `CommandRegistry.to_dict()` / `CommandRegistry.from_dict()` for snapshotting an entire registry.

## [0.2.1] - 2026-05-30

### Added
- Support for registering `@command_group` class instances with bound context (e.g., `registry.register(UserService(user_id="alice"))`)
- `injection_factories` are now properly copied when creating nested CommandSpecs in `_register_command_group`
- `context_group_instance.py` example demonstrating context injection via class `__init__`
- `context_state_factory.py` example demonstrating context injection via `State(factory=...)`
- `context_init.py` example demonstrating context injection via `command_from_method`

### Fixed
- Fixed `_register_command_group` to correctly handle instances (was iterating `type(target)` instead of `target`)
- Fixed `cls = target if is_instance else target` (was incorrectly using `type(target)`)

### Documentation
- Added usage pattern demos for business context injection

## [0.2.0] - 2026-05-26

### Changed
- Simplified `CommandRegistry` to the core `parse`, `execute`, `execute_async`, `match`, `help`, and command-description APIs
- Moved chain execution behind the `chain=True` parameter on `parse`, `execute`, `execute_async`, and `match`
- Moved class-command helpers to `agenticli.commands`
- Moved external tool adapters to `agenticli.adapters`
- Return structured errors for malformed command input such as unclosed quotes or empty slash commands
- Report unknown command-group subcommands as `unknown_command` instead of falling back to group help
- Updated README, examples, and docs for the 0.2.0 API

### Removed
- Removed legacy `CommandRegistry` aliases: `parse_and_execute`, `parse_and_execute_async`, `chain_execute`, `chain_execute_async`, `chain_hit`, `chain_has`, `render_help`, `detect`, `match_command`, `is_command`, and `get_llm_prompt`
- Removed the redundant `describe_commands` API before the 0.2.0 release
- Removed the `agenticli.tooling` compatibility module

### Documentation
- Added `docs/migration_0.2.md`
- Clarified `ExecTool` documentation as a callback bridge rather than a shell executor

## [0.1.4] - 2026-05-25

### Added
- Backslash line continuation support for LF and CRLF command input
- Quote-aware command chain splitting for `;`, `&&`, and `||`
- Additional parser and chain execution tests for quoted operators and line continuations

### Changed
- Updated README and docs to describe the current command grammar and LLM tool semantic layer scope
- Clarified that agenticli does not implement full shell expansion or shell emulation

## [0.1.3] - 2026-04-27

### Added
- Native async execution APIs: `execute_async`, `parse_and_execute_async`, and `chain_execute_async`
- Tool import helpers in `agenticli.tooling`: `wrap_langchain_tool`, `wrap_autogen_tool`, and `wrap_openai_tool_schema`

### Changed
- Updated README and docs to reflect async support and external tool wrapping

### Removed
- Removed the experimental `src/agenticli/integrations` adapter directory in favor of tooling-level wrappers

## [0.1.2] - 2026-04-27

### Changed
- Unified all package imports and internal module references to `agenticli`
- Updated tests, examples, and documentation to use `agenticli` consistently

### Added
- Added `tests/conftest.py` so the package imports correctly in the `src` layout during test runs

## [0.1.1] - Package Rename

### Changed
- Renamed package from `llmcli` to `agenticli`
- Renamed source directory from `src/llmcli` to `src/agenticli`

### Documentation
- Updated all documentation to reflect new package name

## [0.1.0] - Initial Release

### Added
- `CommandRegistry` as the core execution and help system
- Multiple command registration patterns:
  - Function decorator (`@command`)
  - Command groups (`@command_group`)
  - Class inheritance (`CliCommand`)
  - Dataclass-based (`command_from_model`)
  - Schema-based tool wrapping (`wrap_tool`)
- Command parsing:
  - Positional arguments
  - Long options (`--option value`)
  - Short options (`-o value`)
  - Boolean flags
  - Inline values (`--option=value`)
- Help system:
  - Local command help
  - Group help with subcommands
- Structured execution API:
  - `ExecutionResult` with ok/value/error
  - `CommandError` with code, message, hint, and suggestion
- Command suggestions:
  - Unknown command suggestions (did you mean)
  - Unknown option suggestions
  - Enum value suggestions
- Command metadata:
  - Hidden commands (excluded from help)
  - Deprecated commands with notice
- Parameter features:
  - Ordering and positioning control
  - Example values for documentation
  - Hidden parameters
  - Repeatable parameters
  - List/dict/tuple parameter handling
  - `requires` / `excludes` validation
- Lifecycle callbacks (`ExecutionCallbacks`):
  - `before_execute`
  - `after_execute`
  - `on_error`
- Internal parameter injection (`Injected`, `Callback`, `State`)
- Chain execution with operators (`&&`, `||`, `;`)
- Built-in `ExecTool` callback bridge for command strings

## [Unreleased]

## [0.2.4] - 2026-06-04

### Added
- `CommandRegistry.discover(directory, *, context_provider=None, recursive=True, package=None, on_error="ignore")` to auto-discover and register command classes from a directory. Two opt-in markers are recognized: classes carrying `__command_group__` (i.e. decorated with `@command_group`) and subclasses of `CliCommand`. Returns a `DiscoverResult` with `registered` (newly added command names) and `errors` (per-file failures, collected when `on_error="ignore"`).
- New internal `agenticli.discover` module exposing `discover`, `DiscoverResult`, `DiscoverError`, `iter_module_specs`, `iter_command_classes`, and `build_target`. Public discover lives on `CommandRegistry`; the module is intentionally not re-exported from the top-level package.
- New `example/discover.py` plus `example/discover_cmds/` (calc/ping/user) demonstrating directory-driven discovery with a `context_provider` that binds request-scoped context to discovered classes.
- `@command_group(register_as_command=False)` namespace mode. The class is no longer registered as a parent command; its `@command`-decorated methods are registered as flat top-level commands with `spec.parent=None`. The default for `register_as_command` is inferred from `name` (True when `name` is non-empty, False when it is empty).
- Namespace-mode groups can hide their subcommands from the LLM by setting `include_in_prompt=False` on the group; the False value propagates to every subcommand that did not explicitly set `include_in_prompt`. An explicit subcommand value (True or False) always wins.
- `_include_in_prompt_explicit` marker attached to `CommandSpec` so non-`@command` builders (`command_from_method`, `command_from_model`) can participate in the same propagation contract.

### Changed (breaking for callers that used positional args)
- `command_from_method` and `command_from_model` now type `include_in_prompt: bool | None = None`. Pass an explicit `True`/`False` to lock the value; omit it to let a parent `@command_group` namespace's hidden state propagate. The effective value stored on the spec is always a `bool`, so existing keyword-argument callers that passed `True`/`False` see no behavior change.
- `@command_group` now accepts an optional `name` (`name: str = ""`) and a new `register_as_command: bool | None = None` keyword. Setting `register_as_command=True` with an empty `name` raises `ValueError`.

### Tests
- Renamed `tests/test_command_group_instance.py` to `tests/test_command_group.py` and expanded it to cover namespace mode, propagation of `include_in_prompt` from hidden namespace groups, and subcommand naming.
- Added `tests/test_discover.py` covering `discover()` with `@command_group` classes, `CliCommand` subclasses, re-export filtering, conflict detection, and `on_error="raise"`.
- Added `tests/test_concurrency_and_memory.py`, `tests/test_full_coverage.py`, and `tests/test_property_fuzz.py` for additional coverage.
- Rewrote `tests/test_examples.py` as a smoke-test suite that imports and exercises every module under `example/`.
- Removed `tests/test_command_group_naming.py`, `tests/test_linux_like_example.py`, and `tests/test_usage_pattern_examples.py` (their coverage moved into the expanded suites above).

### Documentation
- Renamed every file under `example/` to drop the `_demo` suffix (e.g. `decorator_demo.py` → `decorator.py`, `demo.py` → `provider_integration.py`). The list of runnable examples in `README.md` / `README_zh.md` was updated to match.
- Updated `README.md`, `README_zh.md`, `docs/index_en.md`, `docs/index_zh.md`, and `docs/ROADMAP.md` to describe `discover()`, namespace-mode groups, and the `include_in_prompt` propagation contract.

[Unreleased]: https://github.com/YKONGCO/agenticli/compare/v0.2.4...HEAD
[0.2.4]: https://github.com/YKONGCO/agenticli/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/YKONGCO/agenticli/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/YKONGCO/agenticli/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/YKONGCO/agenticli/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/YKONGCO/agenticli/compare/v0.1.4...v0.2.0
[0.1.4]: https://github.com/YKONGCO/agenticli/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/YKONGCO/agenticli/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/YKONGCO/agenticli/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/YKONGCO/agenticli/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/YKONGCO/agenticli/releases/tag/v0.1.0
