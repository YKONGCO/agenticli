from __future__ import annotations

from example import (
    class_command_demo,
    command_from_method_demo,
    command_from_model_demo,
    command_group_demo,
    decorator_demo,
    external_adapters_demo,
    prompt_filtering_demo,
    wrap_tool_demo,
)


def test_decorator_demo():
    registry = decorator_demo.build_registry()

    assert decorator_demo.execute_value(registry, "hello -n Alice") == {"message": "Hello, Alice!"}
    assert decorator_demo.execute_value(registry, "add 1 2 3") == {
        "values": [1.0, 2.0, 3.0],
        "result": 6.0,
    }


def test_command_group_demo():
    registry = command_group_demo.build_registry()

    assert command_group_demo.execute_value(registry, 'string upper "hello world"') == {"result": "HELLO WORLD"}
    assert command_group_demo.execute_value(registry, 'string replace "hello world" -o world -n agenticli') == {
        "result": "hello agenticli"
    }


def test_class_command_demo():
    registry = class_command_demo.build_registry()

    assert class_command_demo.execute_value(registry, "repeat --text go -n 3") == {
        "text": "go",
        "times": 3,
        "result": "gogogo",
    }


def test_command_from_model_demo():
    registry = command_from_model_demo.build_registry()

    assert command_from_model_demo.execute_value(registry, "scale 10 -f 1.5 -o 2") == {
        "value": 10.0,
        "factor": 1.5,
        "offset": 2.0,
        "result": 17.0,
    }


def test_command_from_method_demo_preserves_instance_state():
    registry = command_from_method_demo.build_registry()

    assert registry.execute("counter add 2 ; counter add 3 ; counter reset", chain=True) == [
        {"total": 2},
        {"total": 5},
        {"total": 0},
    ]


def test_wrap_tool_demo():
    registry = wrap_tool_demo.build_registry()

    assert wrap_tool_demo.execute_value(registry, "weather --city Beijing --unit celsius") == {
        "city": "Beijing",
        "unit": "celsius",
        "temperature": 22,
    }
    assert wrap_tool_demo.execute_value(registry, 'translate --text "hello" --target ja') == {
        "text": "hello",
        "target": "ja",
        "translated": "[ja] hello",
    }


def test_external_adapters_demo():
    registry = external_adapters_demo.build_registry()

    assert external_adapters_demo.execute_value(registry, "lc_echo --text hello --upper") == {"echo": "HELLO"}
    assert external_adapters_demo.execute_value(registry, "ag_join --left agent --right cli --sep /") == {
        "joined": "agent/cli"
    }


def test_prompt_filtering_demo_hides_optional_commands_from_llm():
    registry = prompt_filtering_demo.build_registry()

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

    assert prompt_filtering_demo.execute_value(registry, "reset") == {"reset": True}
    assert prompt_filtering_demo.execute_value(registry, "ops deploy") == {"deployed": True}
    assert prompt_filtering_demo.execute_value(registry, "reports secret") == {"report": "secret"}
