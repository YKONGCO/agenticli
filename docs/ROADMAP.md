# agenticli Roadmap

> 📌 Last updated: 2026-05-25

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

### Parsing Enhancements
- [ ] Glob pattern expansion for argument values 待定

### Shell Compatibility
- [ ] Input/output redirection support (`>`, `<`)
- [ ] Pipe operator (`|`) for command chaining
- [ ] Background execution (`&`)
- [ ] Command substitution (`$( )`, backticks)

### Developer Experience
- [ ] Interactive REPL mode
- [ ] Shell completion scripts
- [ ] Debug mode with verbose logging
- [ ] Configuration file support (YAML/TOML)

### Advanced Features
- [ ] Async iterator support for streaming results
- [ ] Middleware/hook system for pre/post processing
- [ ] Command history (up-arrow)
- [ ] Variable expansion (`$VAR`, `${VAR}`)

---

## 🔮 Future Considerations

These are speculative and depend on user feedback:

- **Plugin system**: Load commands from external packages
- **GUI debugger**: Visual command inspection
- **Multi-shell support**: PowerShell, Cmd, fish compatibility
- **LLM-aware features**: Prompt optimization suggestions

---

## 🐛 Known Limitations

1. **No glob expansion**: `*.txt` passed literally, not expanded
2. **Limited shell emulation**: quoting follows `shlex.split()`, not every shell edge case
3. **Single-command output**: Cannot pipe output to next command input
4. **No shell expansion**: variables, command substitution, and redirection are passed literally

---

## 📝 Version History

See [CHANGELOG.md](../CHANGELOG.md) for detailed version history.

- **v0.1.3**: Current stable release
- **v0.1.2**: Command groups and aliases
- **v0.1.1**: Validation enhancements
- **v0.1.0**: Initial release

---

## 💡 Contributing

Found a feature you'd like to see? Open an issue or submit a PR. See [CONTRIBUTING.md](../CONTRIBUTING.md) for guidelines.
