"""Tests for the modules under ``example/``.

Each test runs a registry built by an example module and asserts the
expected output for one or two representative commands. Together they
double as smoke tests that the example files stay runnable.
"""

from __future__ import annotations

from example import (
    cli_command,
    command_from_method,
    command_from_model,
    command_group,
    decorator,
    external_adapters,
    linux_like_shell,
    prompt_filtering,
    provider_integration,
    wrap_tool,
)
from agenticli import ExecTool


def execute_value(registry, command_text: str):
    result = registry.execute(command_text)
    assert not isinstance(result, list)
    return result.value if result.ok else result.error.render()


# ---------------------------------------------------------------------------
# example/decorator.py — @command decorator
# ---------------------------------------------------------------------------


def test_decorator():
    registry = decorator.build_registry()

    assert execute_value(registry, "hello -n Alice") == {"message": "Hello, Alice!"}
    assert execute_value(registry, "add 1 2 3") == {
        "values": [1.0, 2.0, 3.0],
        "result": 6.0,
    }


# ---------------------------------------------------------------------------
# example/command_group.py — @command_group
# ---------------------------------------------------------------------------


def test_command_group():
    registry = command_group.build_registry()

    assert execute_value(registry, 'string upper "hello world"') == {"result": "HELLO WORLD"}
    assert execute_value(registry, 'string replace "hello world" -o world -n agenticli') == {
        "result": "hello agenticli"
    }


# ---------------------------------------------------------------------------
# example/cli_command.py — CliCommand subclass
# ---------------------------------------------------------------------------


def test_cli_command():
    registry = cli_command.build_registry()

    assert execute_value(registry, "repeat --text go -n 3") == {
        "text": "go",
        "times": 3,
        "result": "gogogo",
    }


# ---------------------------------------------------------------------------
# example/command_from_model.py — dataclass + handler
# ---------------------------------------------------------------------------


def test_command_from_model():
    registry = command_from_model.build_registry()

    assert execute_value(registry, "scale 10 -f 1.5 -o 2") == {
        "value": 10.0,
        "factor": 1.5,
        "offset": 2.0,
        "result": 17.0,
    }


# ---------------------------------------------------------------------------
# example/command_from_method.py — bound instance method
# ---------------------------------------------------------------------------


def test_command_from_method_preserves_instance_state():
    registry = command_from_method.build_registry()

    assert registry.execute("counter add 2 ; counter add 3 ; counter reset", chain=True) == [
        {"total": 2},
        {"total": 5},
        {"total": 0},
    ]


# ---------------------------------------------------------------------------
# example/wrap_tool.py — wrap_tool / wrap_openai_tool_schema
# ---------------------------------------------------------------------------


def test_wrap_tool():
    registry = wrap_tool.build_registry()

    assert execute_value(registry, "weather --city Beijing --unit celsius") == {
        "city": "Beijing",
        "unit": "celsius",
        "temperature": 22,
    }
    assert execute_value(registry, 'translate --text "hello" --target ja') == {
        "text": "hello",
        "target": "ja",
        "translated": "[ja] hello",
    }


# ---------------------------------------------------------------------------
# example/external_adapters.py — LangChain/AutoGen-style wrappers
# ---------------------------------------------------------------------------


def test_external_adapters():
    registry = external_adapters.build_registry()

    assert execute_value(registry, "lc_echo --text hello --upper") == {"echo": "HELLO"}
    assert execute_value(registry, "ag_join --left agent --right cli --sep /") == {
        "joined": "agent/cli"
    }


# ---------------------------------------------------------------------------
# example/prompt_filtering.py — include_in_prompt=False
# ---------------------------------------------------------------------------


def test_prompt_filtering_hides_optional_commands_from_llm():
    registry = prompt_filtering.build_registry()

    context = registry.render_llm_context()
    assert "greet" in context
    assert "reports" in context
    assert "reset" not in context
    assert "backup" not in context
    assert "ops" not in context
    assert "reports secret" not in context

    help_text = registry.help()
    assert "reset" in help_text
    assert "ops" in help_text
    assert "secret" in registry.help("reports")

    assert execute_value(registry, "reset") == {"reset": True}
    assert execute_value(registry, "ops deploy") == {"deployed": True}
    assert execute_value(registry, "reports secret") == {"report": "secret"}


# ---------------------------------------------------------------------------
# example/linux_like_shell.py — pwd/cd/ls/cat/head/grep/wc
# ---------------------------------------------------------------------------


def test_linux_like_shell_lists_files(tmp_path):
    (tmp_path / "alpha.txt").write_text("alpha\nbeta\n", encoding="utf-8")
    (tmp_path / ".hidden").write_text("secret\n", encoding="utf-8")

    registry = linux_like_shell.build_registry(tmp_path)

    assert execute_value(registry, "pwd") == {"cwd": str(tmp_path.resolve())}
    assert execute_value(registry, "ls") == {
        "path": str(tmp_path.resolve()),
        "entries": ["alpha.txt"],
    }
    assert execute_value(registry, "ls -a")["entries"] == [".hidden", "alpha.txt"]


def test_linux_like_shell_common_read_commands(tmp_path):
    sample = tmp_path / "sample.txt"
    sample.write_text("agenticli demo\nsecond line\nAGENTICLI upper\n", encoding="utf-8")

    registry = linux_like_shell.build_registry(tmp_path)

    assert execute_value(registry, "head sample.txt -n 1")["lines"] == ["agenticli demo"]
    assert execute_value(registry, "grep agenticli sample.txt -i")["matches"] == [
        {"path": str(sample.resolve()), "line": 1, "text": "agenticli demo"},
        {"path": str(sample.resolve()), "line": 3, "text": "AGENTICLI upper"},
    ]
    assert execute_value(registry, "wc sample.txt -l -w") == {
        "path": str(sample.resolve()),
        "lines": 3,
        "words": 6,
    }


def test_linux_like_shell_cd_state_and_chain(tmp_path):
    subdir = tmp_path / "sub"
    subdir.mkdir()
    (subdir / "nested.txt").write_text("nested\n", encoding="utf-8")

    registry = linux_like_shell.build_registry(tmp_path)

    assert execute_value(registry, "cd sub") == {"cwd": str(subdir.resolve())}
    assert execute_value(registry, "ls") == {
        "path": str(subdir.resolve()),
        "entries": ["nested.txt"],
    }
    assert registry.execute("cd .. ; pwd ; ls", chain=True) == [
        {"cwd": str(tmp_path.resolve())},
        {"cwd": str(tmp_path.resolve())},
        {"path": str(tmp_path.resolve()), "entries": ["sub"]},
    ]


# ---------------------------------------------------------------------------
# example/provider_integration.py — OpenAI/Anthropic tool-call helpers
# ---------------------------------------------------------------------------


class _OpenAIFunction:
    def __init__(self, name: str, arguments: str):
        self.name = name
        self.arguments = arguments


class _OpenAIToolCall:
    def __init__(self, call_id: str, function: _OpenAIFunction):
        self.id = call_id
        self.function = function


class _OpenAIMessage:
    def __init__(self, tool_calls=None, function_call=None):
        self.tool_calls = tool_calls
        self.function_call = function_call


class _AnthropicBlock:
    def __init__(self, id_: str, name: str, input_, type_: str = "tool_use"):
        self.id = id_
        self.name = name
        self.input = input_
        self.type = type_


class _AnthropicMessage:
    def __init__(self, content):
        self.content = content


def test_provider_integration_calc_commands():
    registry = provider_integration.build_registry()

    assert execute_value(registry, "calc add 10 20 30 40") == {
        "operation": "add",
        "values": [10.0, 20.0, 30.0, 40.0],
        "result": 100.0,
    }
    assert execute_value(registry, "calc mean 10 20 30 -p 3") == {
        "operation": "mean",
        "values": [10.0, 20.0, 30.0],
        "precision": 3,
        "result": 20.0,
    }
    assert execute_value(registry, 'calc dot -l "[1,2,3]" -r "[4,5,6]"') == {
        "operation": "dot",
        "left": [1.0, 2.0, 3.0],
        "right": [4.0, 5.0, 6.0],
        "result": 32.0,
    }


def test_provider_integration_openai_helpers():
    registry = provider_integration.build_registry()
    exec_tool = ExecTool(callback=lambda command, **kwargs: execute_value(registry, command))

    tools = provider_integration.build_openai_tools(exec_tool)
    functions = provider_integration.build_openai_functions(exec_tool)
    assert tools[0]["function"]["name"] == "exec"
    assert functions[0]["name"] == "exec"

    message = _OpenAIMessage(
        tool_calls=[
            _OpenAIToolCall(
                "call_1",
                _OpenAIFunction("exec", '{"command":"calc stats 10 20 30 40 --mode full -p 3"}'),
            )
        ]
    )
    calls = provider_integration.extract_openai_function_calls(message)
    assert calls == [
        {
            "call_id": "call_1",
            "name": "exec",
            "arguments": {"command": "calc stats 10 20 30 40 --mode full -p 3"},
        }
    ]

    legacy_message = _OpenAIMessage(
        function_call=_OpenAIFunction("exec", '{"command":"calc add 1 2 3"}')
    )
    legacy_calls = provider_integration.extract_openai_function_calls(legacy_message)
    assert legacy_calls == [
        {
            "call_id": "function_call_0",
            "name": "exec",
            "arguments": {"command": "calc add 1 2 3"},
        }
    ]

    tool_outputs = provider_integration.build_openai_tool_messages(calls, [{"ok": True}])
    function_outputs = provider_integration.build_openai_function_messages(legacy_calls, [{"ok": True}])
    assert tool_outputs == [{"role": "tool", "tool_call_id": "call_1", "content": '{"ok": true}'}]
    assert function_outputs == [{"role": "function", "name": "exec", "content": '{"ok": true}'}]


def test_provider_integration_anthropic_helpers():
    registry = provider_integration.build_registry(with_lifecycle_logs=True)
    exec_tool = ExecTool(callback=lambda command, **kwargs: execute_value(registry, command))

    tools = provider_integration.build_anthropic_tools(exec_tool)
    assert tools[0]["name"] == "exec"

    message = _AnthropicMessage(
        [
            _AnthropicBlock("tool_1", "exec", {"command": 'calc dot -l "[1,2,3]" -r "[4,5,6]"'}),
            _AnthropicBlock("ignored", "other", {}, type_="text"),
        ]
    )
    tool_uses = provider_integration.extract_anthropic_tool_uses(message)
    assert tool_uses == [
        {"id": "tool_1", "name": "exec", "input": {"command": 'calc dot -l "[1,2,3]" -r "[4,5,6]"'}}
    ]

    outputs = provider_integration.build_anthropic_tool_results(tool_uses, [{"ok": True}])
    assert outputs == [{"type": "tool_result", "tool_use_id": "tool_1", "content": '{"ok": true}'}]


def test_provider_integration_parse_args_selects_provider():
    openai_args = provider_integration.parse_args(["--provider", "openai"])
    anthropic_args = provider_integration.parse_args(["--provider", "anthropic"])

    assert openai_args.provider == "openai"
    assert anthropic_args.provider == "anthropic"
