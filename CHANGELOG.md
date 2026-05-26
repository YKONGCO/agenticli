# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/YKONGCO/agenticli/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/YKONGCO/agenticli/compare/v0.1.4...v0.2.0
[0.1.4]: https://github.com/YKONGCO/agenticli/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/YKONGCO/agenticli/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/YKONGCO/agenticli/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/YKONGCO/agenticli/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/YKONGCO/agenticli/releases/tag/v0.1.0
