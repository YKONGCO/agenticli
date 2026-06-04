"""Directory-driven command class discovery for agenticli.

Internal module. Not exported from :mod:`agenticli`; the public surface is
:meth:`agenticli.CommandRegistry.discover`, which delegates here. The split
keeps filesystem walking, module loading, and class filtering out of
``core.py`` and lets this module be unit-tested without instantiating a
registry.

Two existing opt-in markers are recognized:

* ``hasattr(cls, "__command_group__")`` — set by ``@command_group``
* ``issubclass(cls, CliCommand) and cls is not CliCommand`` — set by
  subclassing :class:`agenticli.commands.CliCommand`

No new base class or protocol is introduced.
"""
from __future__ import annotations

import importlib
import importlib.util
import inspect
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Iterator, Literal

from agenticli.commands import CliCommand


@dataclass
class DiscoverError:
    """A single failure encountered while discovering a directory.

    Attributes:
        path: The ``.py`` file involved.
        class_name: Name of the offending class, or ``None`` for module-level
            import failures.
        stage: Which step failed — ``"import"`` (loading the module),
            ``"instantiate"`` (building the target via context_provider),
            or ``"register"`` (the registry rejected the target).
        exception: The underlying exception, retained for inspection.
    """

    path: Path
    class_name: str | None
    stage: Literal["import", "instantiate", "register"]
    exception: BaseException


@dataclass
class DiscoverResult:
    """Aggregate result of a :func:`discover` call.

    Attributes:
        registered: Names of commands newly added to the underlying registry.
            For ``@command_group`` classes this includes the nested
            subcommand names (e.g. ``"calc add"``).
        errors: Per-file failures collected during discovery. Empty when
            every candidate loaded, instantiated, and registered cleanly.
    """

    registered: list[str] = field(default_factory=list)
    errors: list[DiscoverError] = field(default_factory=list)


def _is_command_class(cls: type) -> bool:
    """Return True if ``cls`` carries one of the two opt-in markers."""
    if hasattr(cls, "__command_group__"):
        return True
    if inspect.isclass(cls) and issubclass(cls, CliCommand) and cls is not CliCommand:
        return True
    return False


def iter_module_specs(
    directory: str | Path,
    *,
    recursive: bool = True,
    package: str | None = None,
) -> Iterator[tuple[Path, str]]:
    """Yield ``(file_path, dotted_name)`` for every candidate ``.py`` file.

    Skips:

    * ``__pycache__`` directories and any file inside them
    * Files whose name starts with ``_`` or ``.`` (covers ``__init__.py``,
      ``_helpers.py``, dotfiles)
    * Files that don't end in ``.py``

    When ``package`` is provided, dotted names are computed as
    ``f"{package}.{rel.stem}"``; otherwise a uuid-prefixed synthetic name
    is used so re-imports don't collide in ``sys.modules``.
    """
    root = Path(directory)
    if not root.is_dir():
        return
    candidates = list(root.rglob("*.py") if recursive else (p for p in root.iterdir() if p.suffix == ".py" and p.is_file()))
    for path in candidates:
        if path.name.startswith("_") or path.name.startswith("."):
            continue
        if any(part == "__pycache__" for part in path.parts):
            continue
        if package is not None:
            rel = path.relative_to(root).with_suffix("")
            dotted = ".".join((package, *rel.parts))
        else:
            dotted = f"_discover_{uuid.uuid4().hex[:8]}_{path.stem}"
        yield path, dotted


def _load_module(path: Path, dotted: str, package: str | None) -> ModuleType:
    """Import a single ``.py`` file by path or by package name."""
    if package is not None:
        return importlib.import_module(dotted)
    spec = importlib.util.spec_from_file_location(dotted, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not build import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[dotted] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(dotted, None)
        raise
    return module


def iter_command_classes(module: ModuleType) -> Iterator[type]:
    """Yield command classes defined in ``module``, excluding re-exports."""
    for _, cls in inspect.getmembers(module, inspect.isclass):
        if cls.__module__ != module.__name__:
            continue
        if _is_command_class(cls):
            yield cls


def build_target(cls: type, context_provider: Callable[[type], Any] | None) -> Any:
    """Resolve the registration target for a discovered class.

    If a ``context_provider`` is supplied, call it with the class and
    return whatever it returns (typically a context-bound instance).
    Otherwise return the class itself and let the existing
    :meth:`CommandRegistry.register` / :class:`CommandFactory` handle
    instantiation.
    """
    if context_provider is not None:
        return context_provider(cls)
    return cls


def discover(
    directory: str | Path,
    *,
    context_provider: Callable[[type], Any] | None = None,
    recursive: bool = True,
    package: str | None = None,
    on_error: Literal["ignore", "raise"] = "ignore",
    register: Callable[[Any], Any] | None = None,
) -> DiscoverResult:
    """Scan a directory and register every command class found.

    Args:
        directory: Filesystem path to scan, or a package root when
            ``package`` is provided.
        context_provider: Optional ``(cls) -> target`` callback invoked
            once per discovered class. Return whatever should be passed
            to ``register()`` — typically a context-bound instance.
        recursive: If ``True`` (default), descend into subdirectories.
        package: Optional dotted package name. When set, candidate files
            are imported as ``{package}.{relpath}`` instead of via
            filesystem spec.
        on_error: ``"ignore"`` (default) collects failures into
            ``result.errors`` and continues; ``"raise"`` re-raises the
            first error and abandons the remaining candidates.
        register: Required callable that receives each built target.
            :meth:`CommandRegistry.discover` supplies ``self.register``;
            tests can pass a mock. The callable may return an iterable
            of newly-registered command names (used to populate
            ``result.registered``); any other return value is ignored.

    Returns:
        A :class:`DiscoverResult` aggregating successes and failures.
    """
    if register is None:
        raise TypeError("discover() requires a register= callable")
    if on_error not in ("ignore", "raise"):
        raise ValueError(f"on_error must be 'ignore' or 'raise', got {on_error!r}")

    result = DiscoverResult()

    for path, dotted in iter_module_specs(directory, recursive=recursive, package=package):
        try:
            module = _load_module(path, dotted, package)
        except BaseException as exc:
            result.errors.append(DiscoverError(path=path, class_name=None, stage="import", exception=exc))
            if on_error == "raise":
                raise
            continue

        for cls in iter_command_classes(module):
            try:
                target = build_target(cls, context_provider)
            except BaseException as exc:
                result.errors.append(DiscoverError(path=path, class_name=cls.__name__, stage="instantiate", exception=exc))
                if on_error == "raise":
                    raise
                continue

            try:
                names = register(target)
            except BaseException as exc:
                result.errors.append(DiscoverError(path=path, class_name=cls.__name__, stage="register", exception=exc))
                if on_error == "raise":
                    raise
                continue

            if isinstance(names, (list, tuple)):
                result.registered.extend(names)
            elif names is not None:
                result.registered.append(str(names))

    return result
