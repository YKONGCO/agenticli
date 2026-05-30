# agenticli Roadmap

> 📌 Last updated: 2026-05-26

## Project Vision

agenticli converts functions, classes, and schema-based tools into a stable CLI semantic layer for LLM agents. The command string is the most stable, restrained, and observable intermediate representation between LLMs and tool systems.

---

## 🎯 Current Features

### Parsing
- [x] Long options: `--option value`
- [x] Short options: `-o value`
- [x] Inline values: `--option=value` or `-ovalue`
- [x] Flags: `--flag`
- [x] Positional arguments
- [x] List accumulation for repeatable args
- [x] Command chaining: `&&`, `||`, `;`
- [x] Quoted argument splitting
- [x] Quote-aware command chain splitting
- [x] Backslash line continuation

### Validation
- [x] Type coercion (str, int, float, bool, list, dict)
- [x] Enum validation with fuzzy matching
- [x] Required/optional argument enforcement
- [x] Default value handling

### Commands
- [x] Decorator-based: `@command`
- [x] Class-based: `CliCommand`
- [x] Schema-based tool wrapping
- [x] Command groups: `@command_group`
- [x] Aliases
- [x] Prefix matching

### Help & Introspection
- [x] `--help` for commands and groups
- [x] Fuzzy command detection
- [x] Lifecycle callbacks

---

## ✅ Recently Completed

### Backslash Line Continuation
**Status**: Completed

Unix shell-style line continuation is supported where `\` followed by LF or
CRLF is normalized to a space before command parsing:

```bash
# These are equivalent:
ls --help
ls \
--help
```

**Implementation location**: `src/agenticli/core.py` → `_preprocess_command_input()` and `_preprocess_backslash()`

### Quote-aware Chain Splitting
**Status**: Completed

Command chains split on `;`, `&&`, and `||` only outside quoted arguments:

```bash
say "hello ; world" ; say done
say "hello && world" && say ok
```

---

## 📋 Planned Features

The roadmap prioritizes agenticli as an LLM tool semantic layer, not as a full
shell emulator. Shell-like syntax is used only where it improves compactness,
observability, and model reliability.

### P0: Documentation & Release Hygiene
- [ ] Keep `pyproject.toml`, README badges, CHANGELOG, and roadmap versions in sync
- [ ] Document the supported command grammar as a stable contract
- [ ] Clearly document unsupported shell syntax and whether it is passed through or rejected
- [ ] Replace placeholder repository links in CHANGELOG with the canonical project URL

### P1: LLM Tool Semantics
- [ ] Stable `CommandSpec` serialization for persistence, inspection, and cross-process transport
- [ ] Export command specs to JSON Schema / OpenAI-style tool definitions where useful
- [ ] Improve schema import coverage for common tool ecosystems
- [ ] Add compact and detailed prompt rendering modes with predictable token budgets
- [ ] Make structured error codes and suggestions part of the public compatibility contract
- [ ] Add command capability discovery APIs for agents that need incremental help expansion

### P1: Parser Reliability
- [ ] Add explicit tests for unsupported shell syntax: `|`, `>`, `<`, `&`, `$VAR`, `${VAR}`, `$()`, and backticks
- [ ] Decide whether unsupported shell syntax should always be treated as literal arguments or rejected with structured errors
- [ ] Harden quote, escape, and chain-splitting behavior around edge cases
- [ ] Improve diagnostics for malformed quotes and incomplete command chains

### P1: Execution & Observability
- [ ] Add execution trace metadata for parse, validation, execution, callback, and error stages
- [ ] Add first-class timeout and cancellation handling for async execution
- [ ] Expand lifecycle callbacks into a clearer policy/audit hook surface
- [ ] Support optional structured logging without forcing a logging framework dependency

### P2: Streaming Results
- [ ] Support commands returning async iterators for streaming tool results
- [ ] Define sync and async streaming result wrappers
- [ ] Document how streaming results should be consumed by agent runtimes

### P3: Optional CLI Application Layer
- [ ] Interactive REPL mode, if the project adds an official `agenticli` executable
- [ ] Command history and shell completion, scoped to the optional executable
- [ ] YAML/TOML configuration for loading local command registries

---

## 🔮 Future Considerations

These are speculative and depend on user feedback:

- **Plugin system**: Load commands from external packages
- **GUI debugger**: Visual command inspection
- **Provider adapters**: Convenience bridges for agent runtimes that want an `exec`-style tool
- **LLM-aware features**: Prompt optimization suggestions and command repair hints

---

## 🐛 Known Limitations

1. **Not a shell emulator**: agenticli intentionally does not implement full shell semantics.
2. **No shell expansion**: glob patterns, variables, command substitution, redirection, and pipe syntax are not expanded by agenticli.
3. **Limited command chaining**: only `;`, `&&`, and `||` are supported through the `chain=True` parser/execution mode.
4. **No output piping**: command output is returned as structured Python values, not streamed into another command's stdin.
5. **Quoting is shlex-based**: argument splitting follows Python `shlex`, not every Bash, PowerShell, Cmd, fish, or zsh edge case.

---

## 📝 Version History

See [CHANGELOG.md](../CHANGELOG.md) for detailed version history.

- **v0.2.1**: Current stable release - Instance registration support for command groups
- **v0.2.0**: Previous stable release
- **v0.1.3**: Async execution and external tool wrapping
- **v0.1.2**: Command groups and aliases
- **v0.1.1**: Validation enhancements
- **v0.1.0**: Initial release

---

## 💡 Contributing

Found a feature you'd like to see? Open an issue or submit a PR. See [CONTRIBUTING.md](../CONTRIBUTING.md) for guidelines.
