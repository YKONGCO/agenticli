from __future__ import annotations

from example import demo
from llmcli import ExecTool


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


def test_demo_registry_supports_complex_calc_commands():
    registry = demo.build_registry()

    assert registry.parse_and_execute("calc add 10 20 30 40") == {
        "operation": "add",
        "values": [10.0, 20.0, 30.0, 40.0],
        "result": 100.0,
    }
    assert registry.parse_and_execute("calc mean 10 20 30 -p 3") == {
        "operation": "mean",
        "values": [10.0, 20.0, 30.0],
        "precision": 3,
        "result": 20.0,
    }
    assert registry.parse_and_execute('calc dot -l "[1,2,3]" -r "[4,5,6]"') == {
        "operation": "dot",
        "left": [1.0, 2.0, 3.0],
        "right": [4.0, 5.0, 6.0],
        "result": 32.0,
    }


def test_demo_openai_helpers():
    registry = demo.build_registry()
    exec_tool = ExecTool(callback=registry.parse_and_execute)

    tools = demo.build_openai_tools(exec_tool)
    functions = demo.build_openai_functions(exec_tool)
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
    calls = demo.extract_openai_function_calls(message)
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
    legacy_calls = demo.extract_openai_function_calls(legacy_message)
    assert legacy_calls == [
        {
            "call_id": "function_call_0",
            "name": "exec",
            "arguments": {"command": "calc add 1 2 3"},
        }
    ]

    tool_outputs = demo.build_openai_tool_messages(calls, [{"ok": True}])
    function_outputs = demo.build_openai_function_messages(legacy_calls, [{"ok": True}])
    assert tool_outputs == [{"role": "tool", "tool_call_id": "call_1", "content": '{"ok": true}'}]
    assert function_outputs == [{"role": "function", "name": "exec", "content": '{"ok": true}'}]


def test_demo_anthropic_helpers():
    registry = demo.build_registry(with_lifecycle_logs=True)
    exec_tool = ExecTool(callback=registry.parse_and_execute)

    tools = demo.build_anthropic_tools(exec_tool)
    assert tools[0]["name"] == "exec"

    message = _AnthropicMessage(
        [
            _AnthropicBlock("tool_1", "exec", {"command": 'calc dot -l "[1,2,3]" -r "[4,5,6]"'}),
            _AnthropicBlock("ignored", "other", {}, type_="text"),
        ]
    )
    tool_uses = demo.extract_anthropic_tool_uses(message)
    assert tool_uses == [
        {"id": "tool_1", "name": "exec", "input": {"command": 'calc dot -l "[1,2,3]" -r "[4,5,6]"'}}
    ]

    outputs = demo.build_anthropic_tool_results(tool_uses, [{"ok": True}])
    assert outputs == [{"type": "tool_result", "tool_use_id": "tool_1", "content": '{"ok": true}'}]


def test_demo_parse_args_selects_provider():
    openai_args = demo.parse_args(["--provider", "openai"])
    anthropic_args = demo.parse_args(["--provider", "anthropic"])

    assert openai_args.provider == "openai"
    assert anthropic_args.provider == "anthropic"
