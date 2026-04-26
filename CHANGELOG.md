# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
- Built-in `ExecTool` for shell command execution

[Unreleased]: https://github.com/your-repo/agenticli/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/your-repo/agenticli/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/your-repo/agenticli/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/your-repo/agenticli/releases/tag/v0.1.0
