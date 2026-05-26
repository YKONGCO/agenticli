from __future__ import annotations

from example import linux_like_demo


def test_linux_like_demo_lists_files(tmp_path):
    (tmp_path / "alpha.txt").write_text("alpha\nbeta\n", encoding="utf-8")
    (tmp_path / ".hidden").write_text("secret\n", encoding="utf-8")

    registry = linux_like_demo.build_registry(tmp_path)

    assert linux_like_demo.execute_value(registry, "pwd") == {"cwd": str(tmp_path.resolve())}
    assert linux_like_demo.execute_value(registry, "ls") == {
        "path": str(tmp_path.resolve()),
        "entries": ["alpha.txt"],
    }
    assert linux_like_demo.execute_value(registry, "ls -a")["entries"] == [".hidden", "alpha.txt"]


def test_linux_like_demo_common_read_commands(tmp_path):
    sample = tmp_path / "sample.txt"
    sample.write_text("agenticli demo\nsecond line\nAGENTICLI upper\n", encoding="utf-8")

    registry = linux_like_demo.build_registry(tmp_path)

    assert linux_like_demo.execute_value(registry, "head sample.txt -n 1")["lines"] == ["agenticli demo"]
    assert linux_like_demo.execute_value(registry, "grep agenticli sample.txt -i")["matches"] == [
        {"path": str(sample.resolve()), "line": 1, "text": "agenticli demo"},
        {"path": str(sample.resolve()), "line": 3, "text": "AGENTICLI upper"},
    ]
    assert linux_like_demo.execute_value(registry, "wc sample.txt -l -w") == {
        "path": str(sample.resolve()),
        "lines": 3,
        "words": 6,
    }


def test_linux_like_demo_cd_state_and_chain(tmp_path):
    subdir = tmp_path / "sub"
    subdir.mkdir()
    (subdir / "nested.txt").write_text("nested\n", encoding="utf-8")

    registry = linux_like_demo.build_registry(tmp_path)

    assert linux_like_demo.execute_value(registry, "cd sub") == {"cwd": str(subdir.resolve())}
    assert linux_like_demo.execute_value(registry, "ls") == {
        "path": str(subdir.resolve()),
        "entries": ["nested.txt"],
    }
    assert registry.execute("cd .. ; pwd ; ls", chain=True) == [
        {"cwd": str(tmp_path.resolve())},
        {"cwd": str(tmp_path.resolve())},
        {"path": str(tmp_path.resolve()), "entries": ["sub"]},
    ]
