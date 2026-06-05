"""Measure prompt-token cost of agenticli vs. raw JSON-Schema tool lists.

The benchmark builds a representative tool catalog (15 tools spanning file,
network, and data operations), then compares the tokens required to expose
the same toolset to an LLM in two ways:

1. As an OpenAI-style ``tools=[]`` array of JSON Schemas.
2. As the text returned by ``CommandRegistry.render_llm_context()``.

Both payloads are tokenized with ``cl100k_base`` (the tokenizer used by
``gpt-4`` / ``gpt-4o`` family) so the comparison reflects what an actual
inference call would see in the prompt.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import tiktoken

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agenticli import CommandRegistry, Option, command, command_group  # noqa: E402

ENCODER = tiktoken.get_encoding("cl100k_base")


# --- A representative tool catalog -------------------------------------------------
# Each entry pairs an OpenAI-style schema with the agenticli command that
# implements the same tool. Descriptions and parameter sets are kept
# comparable so the only variable is the prompt representation.

TOOL_CATALOG: list[dict] = [
    {
        "name": "read_file",
        "description": "Read the contents of a file at the given path. Returns the text content encoded as UTF-8.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute or relative path to the file."},
                "encoding": {"type": "string", "description": "Text encoding to use.", "enum": ["utf-8", "ascii", "latin-1"], "default": "utf-8"},
                "max_bytes": {"type": "integer", "description": "Maximum number of bytes to read.", "minimum": 1},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write the given content to a file, creating parent directories as needed and overwriting existing files.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path of the file to write."},
                "content": {"type": "string", "description": "Text content to write."},
                "append": {"type": "boolean", "description": "Append to the file instead of overwriting.", "default": False},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_directory",
        "description": "List the entries in a directory, optionally filtered by extension and including hidden files.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory to list."},
                "recursive": {"type": "boolean", "description": "Recurse into subdirectories.", "default": False},
                "ext": {"type": "string", "description": "Filter by file extension, e.g. '.log'."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_files",
        "description": "Recursively search for files whose name matches the given glob pattern under a directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "directory": {"type": "string", "description": "Root directory to search from."},
                "pattern": {"type": "string", "description": "Glob pattern, e.g. '*.py'."},
                "max_results": {"type": "integer", "description": "Cap on number of results returned.", "default": 100},
            },
            "required": ["directory", "pattern"],
        },
    },
    {
        "name": "delete_file",
        "description": "Delete a file or empty directory. Refuses to operate on paths outside the working directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to delete."},
                "recursive": {"type": "boolean", "description": "Recursively delete directories.", "default": False},
            },
            "required": ["path"],
        },
    },
    {
        "name": "http_get",
        "description": "Send an HTTP GET request to the given URL and return the response body and status code.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Target URL, must include scheme."},
                "headers": {"type": "object", "description": "Optional request headers as key/value pairs.", "additionalProperties": {"type": "string"}},
                "timeout_s": {"type": "number", "description": "Request timeout in seconds.", "default": 30.0},
            },
            "required": ["url"],
        },
    },
    {
        "name": "http_post",
        "description": "Send an HTTP POST request with a JSON body to the given URL and return the response.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Target URL, must include scheme."},
                "body": {"type": "object", "description": "JSON-serializable request body."},
                "headers": {"type": "object", "description": "Optional request headers.", "additionalProperties": {"type": "string"}},
                "timeout_s": {"type": "number", "description": "Request timeout in seconds.", "default": 30.0},
            },
            "required": ["url", "body"],
        },
    },
    {
        "name": "run_command",
        "description": "Execute a shell command in the working directory and return its combined stdout and stderr.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command line to execute."},
                "timeout_s": {"type": "integer", "description": "Maximum execution time in seconds.", "default": 60},
                "env": {"type": "object", "description": "Additional environment variables.", "additionalProperties": {"type": "string"}},
            },
            "required": ["command"],
        },
    },
    {
        "name": "sql_query",
        "description": "Run a read-only SQL query against the configured database and return the rows as a list of objects.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "SQL SELECT statement. Mutations are rejected."},
                "params": {"type": "array", "description": "Positional bind parameters.", "items": {"type": ["string", "number", "boolean", "null"]}},
                "limit": {"type": "integer", "description": "Maximum number of rows to return.", "default": 1000},
            },
            "required": ["query"],
        },
    },
    {
        "name": "git_status",
        "description": "Return the porcelain status of the git repository at the given path, including branch and staged/unstaged changes.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path inside a git working tree."},
                "include_untracked": {"type": "boolean", "description": "Include untracked files in the output.", "default": True},
            },
            "required": ["path"],
        },
    },
    {
        "name": "git_diff",
        "description": "Show the unified diff for the working tree or a specific commit, optionally filtered to a path.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path inside a git working tree."},
                "commit": {"type": "string", "description": "Commit ref to diff against, defaults to HEAD."},
                "file": {"type": "string", "description": "Restrict the diff to a single file."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_web",
        "description": "Run a web search query and return the top results with title, URL, and a short snippet.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural-language search query."},
                "max_results": {"type": "integer", "description": "Number of results to return.", "default": 10, "minimum": 1, "maximum": 50},
                "recency_days": {"type": "integer", "description": "Restrict to results newer than this many days, 0 for no limit.", "default": 0},
            },
            "required": ["query"],
        },
    },
    {
        "name": "fetch_url",
        "description": "Download a URL and return its plain text content with HTML stripped.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "HTTP or HTTPS URL to fetch."},
                "max_chars": {"type": "integer", "description": "Truncate the returned text to this many characters.", "default": 50000},
            },
            "required": ["url"],
        },
    },
    {
        "name": "create_todo",
        "description": "Append an item to the agent's task list with optional priority and tags.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short description of the task."},
                "priority": {"type": "string", "description": "Priority bucket.", "enum": ["low", "medium", "high"], "default": "medium"},
                "tags": {"type": "array", "description": "Free-form labels for the task.", "items": {"type": "string"}},
            },
            "required": ["title"],
        },
    },
    {
        "name": "send_email",
        "description": "Send a plain-text email to the given recipients with the given subject and body.",
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "array", "description": "Recipient email addresses.", "items": {"type": "string", "format": "email"}, "minItems": 1},
                "subject": {"type": "string", "description": "Email subject line."},
                "body": {"type": "string", "description": "Plain-text email body."},
                "cc": {"type": "array", "description": "Optional CC recipients.", "items": {"type": "string", "format": "email"}},
            },
            "required": ["to", "subject", "body"],
        },
    },
]


def build_openai_tools_payload(catalog: list[dict]) -> str:
    """Render the catalog as an OpenAI-style tools=[] JSON payload."""
    tools = [
        {"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}}
        for t in catalog
    ]
    return json.dumps(tools, separators=(",", ":"))


@command_group(name="files", description="File system read, write, and search operations.")
class Files:
    @command(name="read_file", description="Read the contents of a file at the given path. Returns the text content encoded as UTF-8.")
    def read_file(
        self,
        path: Annotated[str, Option(positional=True, description="Absolute or relative path to the file.")],
        encoding: Annotated[str, Option(short="e", description="Text encoding to use.")] = "utf-8",
        max_bytes: Annotated[int, Option(description="Maximum number of bytes to read.")] = 0,
    ) -> str:
        return ""

    @command(name="write_file", description="Write the given content to a file, creating parent directories as needed and overwriting existing files.")
    def write_file(
        self,
        path: Annotated[str, Option(positional=True, description="Path of the file to write.")],
        content: Annotated[str, Option(positional=True, description="Text content to write.")],
        append: Annotated[bool, Option(short="a", description="Append to the file instead of overwriting.")] = False,
    ) -> str:
        return ""

    @command(name="list_directory", description="List the entries in a directory, optionally filtered by extension and including hidden files.")
    def list_directory(
        self,
        path: Annotated[str, Option(positional=True, description="Directory to list.")],
        recursive: Annotated[bool, Option(short="r", description="Recurse into subdirectories.")] = False,
        ext: Annotated[str, Option(description="Filter by file extension, e.g. '.log'.")] = "",
    ) -> list[str]:
        return []

    @command(name="search_files", description="Recursively search for files whose name matches the given glob pattern under a directory.")
    def search_files(
        self,
        directory: Annotated[str, Option(positional=True, description="Root directory to search from.")],
        pattern: Annotated[str, Option(positional=True, description="Glob pattern, e.g. '*.py'.")],
        max_results: Annotated[int, Option(description="Cap on number of results returned.")] = 100,
    ) -> list[str]:
        return []

    @command(name="delete_file", description="Delete a file or empty directory. Refuses to operate on paths outside the working directory.")
    def delete_file(
        self,
        path: Annotated[str, Option(positional=True, description="Path to delete.")],
        recursive: Annotated[bool, Option(short="r", description="Recursively delete directories.")] = False,
    ) -> str:
        return ""


@command_group(name="http", description="HTTP requests and web fetching.")
class Http:
    @command(name="http_get", description="Send an HTTP GET request to the given URL and return the response body and status code.")
    def http_get(
        self,
        url: Annotated[str, Option(positional=True, description="Target URL, must include scheme.")],
        timeout_s: Annotated[float, Option(description="Request timeout in seconds.")] = 30.0,
    ) -> dict:
        return {}

    @command(name="http_post", description="Send an HTTP POST request with a JSON body to the given URL and return the response.")
    def http_post(
        self,
        url: Annotated[str, Option(positional=True, description="Target URL, must include scheme.")],
        body: Annotated[str, Option(positional=True, description="JSON-serializable request body as a JSON string.")] = "{}",
        timeout_s: Annotated[float, Option(description="Request timeout in seconds.")] = 30.0,
    ) -> dict:
        return {}

    @command(name="search_web", description="Run a web search query and return the top results with title, URL, and a short snippet.")
    def search_web(
        self,
        query: Annotated[str, Option(positional=True, description="Natural-language search query.")],
        max_results: Annotated[int, Option(description="Number of results to return.")] = 10,
        recency_days: Annotated[int, Option(description="Restrict to results newer than this many days, 0 for no limit.")] = 0,
    ) -> list[dict]:
        return []

    @command(name="fetch_url", description="Download a URL and return its plain text content with HTML stripped.")
    def fetch_url(
        self,
        url: Annotated[str, Option(positional=True, description="HTTP or HTTPS URL to fetch.")],
        max_chars: Annotated[int, Option(description="Truncate the returned text to this many characters.")] = 50000,
    ) -> str:
        return ""


@command_group(name="exec", description="Local execution: shell, git, and database queries.")
class Exec:
    @command(name="run_command", description="Execute a shell command in the working directory and return its combined stdout and stderr.")
    def run_command(
        self,
        command: Annotated[str, Option(positional=True, description="Shell command line to execute.")],
        timeout_s: Annotated[int, Option(description="Maximum execution time in seconds.")] = 60,
    ) -> str:
        return ""

    @command(name="sql_query", description="Run a read-only SQL query against the configured database and return the rows as a list of objects.")
    def sql_query(
        self,
        query: Annotated[str, Option(positional=True, description="SQL SELECT statement. Mutations are rejected.")],
        limit: Annotated[int, Option(description="Maximum number of rows to return.")] = 1000,
    ) -> list[dict]:
        return []

    @command(name="git_status", description="Return the porcelain status of the git repository at the given path, including branch and staged/unstaged changes.")
    def git_status(
        self,
        path: Annotated[str, Option(positional=True, description="Path inside a git working tree.")],
        include_untracked: Annotated[bool, Option(description="Include untracked files in the output.")] = True,
    ) -> str:
        return ""

    @command(name="git_diff", description="Show the unified diff for the working tree or a specific commit, optionally filtered to a path.")
    def git_diff(
        self,
        path: Annotated[str, Option(positional=True, description="Path inside a git working tree.")],
        commit: Annotated[str, Option(description="Commit ref to diff against, defaults to HEAD.")] = "HEAD",
        file: Annotated[str, Option(description="Restrict the diff to a single file.")] = "",
    ) -> str:
        return ""


@command_group(name="agent", description="Agent self-management: tasks and outbound notifications.")
class Agent:
    @command(name="create_todo", description="Append an item to the agent's task list with optional priority and tags.")
    def create_todo(
        self,
        title: Annotated[str, Option(positional=True, description="Short description of the task.")],
        priority: Annotated[str, Option(description="Priority bucket.")] = "medium",
    ) -> str:
        return ""

    @command(name="send_email", description="Send a plain-text email to the given recipients with the given subject and body.")
    def send_email(
        self,
        to: Annotated[str, Option(positional=True, description="Comma-separated recipient email addresses.")],
        subject: Annotated[str, Option(positional=True, description="Email subject line.")],
        body: Annotated[str, Option(positional=True, description="Plain-text email body.")],
    ) -> str:
        return ""


def build_agenticli_context() -> str:
    registry = CommandRegistry()
    registry.register(Files)
    registry.register(Http)
    registry.register(Exec)
    registry.register(Agent)
    return registry.render_llm_context()


# --- A representative single tool call -------------------------------------------
# Same tool, same arguments — only the wire format differs.

SAMPLE_CALL = {
    "name": "read_file",
    "path": "/etc/hosts",
    "encoding": "utf-8",
    "max_bytes": 4096,
}


def build_openai_call(call: dict) -> str:
    return json.dumps(
        {"name": call["name"], "arguments": json.dumps({k: v for k, v in call.items() if k != "name"})},
        separators=(",", ":"),
    )


def build_agenticli_call(call: dict) -> str:
    return f"files {call['name']} {call['path']} --encoding {call['encoding']} --max_bytes {call['max_bytes']}"


def count_tokens(text: str) -> int:
    return len(ENCODER.encode(text))


def main() -> int:
    n_tools = len(TOOL_CATALOG)
    openai_def = build_openai_tools_payload(TOOL_CATALOG)
    agenticli_def = build_agenticli_context()
    openai_call = build_openai_call(SAMPLE_CALL)
    agenticli_call = build_agenticli_call(SAMPLE_CALL)

    def_t = count_tokens(openai_def)
    call_t = count_tokens(openai_call)
    cli_def_t = count_tokens(agenticli_def)
    cli_call_t = count_tokens(agenticli_call)

    def_saved = def_t - cli_def_t
    call_saved = call_t - cli_call_t
    def_pct = (1 - cli_def_t / def_t) * 100
    call_pct = (1 - cli_call_t / call_t) * 100

    print(f"tools catalog  : {n_tools} tools, sample call: read_file with 3 args\n")
    print("                 Definition (system prompt)        Call (model output)")
    print(f"openai          {def_t:>6} tokens                      {call_t:>4} tokens")
    print(f"agenticli       {cli_def_t:>6} tokens                      {cli_call_t:>4} tokens")
    print(f"reduction       {def_pct:>5.1f}% ({def_saved:>4} saved)             {call_pct:>4.1f}% ({call_saved} saved)")
    print()
    print("--- agenticli context (definition) ---")
    print(agenticli_def)
    print()
    print("--- openai call output ---")
    print(openai_call)
    print("--- agenticli call output ---")
    print(agenticli_call)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
