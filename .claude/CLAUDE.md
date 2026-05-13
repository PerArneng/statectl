# statectl

A general framework for declarative state transitions, aimed at OS and infrastructure use cases (creating files, installing packages, configuring services, etc.) but not domain-bound. A driver assembles ordered `StateChanger` instances; the engine assesses current state and applies only what's needed.

## Architecture

Three core concepts:

- **`StateChanger`** (`statectl/state_changer.py`) — ABC for one directional state change. Methods: `name()`, `assess_state() -> StateAssessment`, `transition() -> Result`. Each implementation is bound to its own `Parameters` dataclass (frozen, subclasses `Parameters`).
- **`RollbackableStateChanger`** — extends `StateChanger` with `rollback() -> StateChanger`. The returned inverse is a plain `StateChanger` so the type system forbids rollback-of-rollback.
- **`StateCtlEngine`** (`statectl/state_ctl_engine.py`) — orchestrator. Built via `StateCtlEngine.create_engine()` (DI factory wiring `DefaultLogger` as `Logger`). Callers `engine.add(changer)` then `engine.start()`; the engine iterates in order, dispatches on `assess_state()`, halts on `INVALID` or transition `FAILURE`.

### State assessment model
`assess_state()` returns a `StateAssessment(state, description, issues)` where `state: ExistingState` is one of:
- `READY` — preconditions met, run `transition()`.
- `ALREADY_APPLIED` — desired end state already in place; skip (idempotency).
- `INVALID` — cannot proceed; `issues: list[str]` describes why.

`transition()` and `rollback()` return `Result(status, code, message, details)` with `ResultStatus` of `SUCCESS | FAILURE | SKIPPED`.

### Layout
- `statectl/state_changer.py` — core ABCs + `Parameters`, `StateAssessment`, `ExistingState`, `Result`, `ResultStatus`.
- `statectl/state_ctl_engine.py` — `StateCtlEngine` and its private DI container.
- `statectl/interfaces/` — abstract interfaces injected via DI (e.g. `logger.py:Logger`).
- `statectl/modules/` — concrete implementations of interfaces (e.g. `logger/default_logger.py:DefaultLogger` wraps stdlib `logging`).
- `statectl/statechangers/` — concrete `StateChanger` implementations (e.g. `new_text_file.py`).
- `examples/` — PEP-723 uv scripts that depend on the library via `tool.uv.sources = { path = "../", editable = true }`.

## Conventions
- Type hints on every signature and class attribute. `from __future__ import annotations` where helpful.
- Prefer pure functions; concentrate side effects in `transition()` / `rollback()`. `assess_state()` is read-only.
- Dependency injection via `dependency-injector`. The DI container lives inside `StateCtlEngine` and is built by the static `create_engine()` factory. New runtime dependencies should be added as `Logger`-style ABCs in `interfaces/` with a default impl in `modules/`.
- `__init__.py` files stay **empty**. Import each class from its actual module path (e.g. `from statectl.state_ctl_engine import StateCtlEngine`), never via package re-exports.
- **One class per file.** Each public class lives in its own module whose filename is the snake_case form of the class name (e.g. `FsDecodeError` → `fs_decode_error.py`, `FileEntry` → `file_entry.py`, `RealFileSystem` → `real_file_system.py`). Closely-scoped helpers (private `_translate`-style functions, small `@dataclass` siblings used only by that class) may share the file. This applies to interfaces, modules, state changers, and exception hierarchies.
- New `StateChanger` implementations: pair the class with a frozen `Parameters` subclass, place under `statectl/statechangers/<name>.py`, collect all assessment issues before returning so callers see the full picture.
- **Capabilities are defined as interfaces.** Any side-effecting capability — filesystem, network, HTTP client, OS / process exec, clock, env — is an ABC under `statectl/interfaces/<capability>/` with the concrete real-world implementation under `statectl/modules/<capability>/`. `statectl/interfaces/fs/` (`FileSystem`) paired with `statectl/modules/fs/real_file_system.py` (`RealFileSystem`) is the reference example. Never call `pathlib`, `os`, `socket`, `requests`, `subprocess`, `time`, etc. directly from a state changer or module — wrap it behind an interface first. Errors raised by these interfaces follow the one-class-per-file typed-exception pattern under `statectl/interfaces/<capability>/error/` (see `statectl/interfaces/fs/error/`) so callers catch a single library-defined base instead of stdlib exception types.
- **Modules depend on interfaces and receive them via DI.** A module under `statectl/modules/` may only import from `statectl.interfaces.*`, never another concrete module. Cross-module wiring lives in `StateCtlEngine._Container` (`statectl/state_ctl_engine.py`) using `dependency-injector` providers — mirror the existing `logger` and `filesystem` `providers.Singleton(...)` entries. A new capability registers its real implementation as a `providers.Singleton(<RealImpl>)`; a module that consumes another capability declares it as a constructor parameter typed against the interface and the container injects it.
- **State changers depend on interfaces and receive them via constructor injection with real defaults.** Drivers instantiate state changers by hand (the engine does not own them), so every state changer accepts its interfaces as constructor parameters whose default is the real implementation — e.g. `def __init__(self, params: P, file_system: FileSystem | None = None) -> None: self._fs = file_system or RealFileSystem()`. Production stays ergonomic; tests inject fakes (see `tests/fakes/in_memory_file_system.py`, `tests/fakes/failing_file_system.py`). State changers must not call stdlib IO directly.
- **No real IO in tests.** Tests must drive state changers through fake implementations of the relevant interface(s). A test that touches the real disk, network, or process table is a bug.
