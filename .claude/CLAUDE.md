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
- New `StateChanger` implementations: pair the class with a frozen `Parameters` subclass, place under `statectl/statechangers/<name>.py`, collect all assessment issues before returning so callers see the full picture.
