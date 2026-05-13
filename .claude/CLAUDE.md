# statectl

A general framework for declarative state transitions, aimed at OS and infrastructure use cases (creating files, installing packages, configuring services, etc.) but not domain-bound. A driver assembles ordered `StateChanger` instances; the engine assesses current state and applies only what's needed.

## Architecture

Three core concepts:

- **`StateChanger`** (`statectl/state_changer.py`) — ABC for one directional state change. Methods: `name()`, `assess_state() -> StateAssessment`, `transition() -> Result`. Bound to a frozen `Parameters` subclass.
- **`RollbackableStateChanger`** — extends `StateChanger` with `rollback() -> StateChanger`. The inverse is a plain `StateChanger`, so the type system forbids rollback-of-rollback.
- **`StateCtlEngine`** (`statectl/state_ctl_engine.py`) — orchestrator built via `StateCtlEngine.create_engine()`. Drivers `engine.add(changer)` then `engine.start()`; the engine dispatches on `assess_state()` (`READY` → run, `ALREADY_APPLIED` → skip, `INVALID` → halt) and halts on transition `FAILURE`.

## Layout

- `statectl/state_changer.py` — core ABCs + `Parameters`, `StateAssessment`, `ExistingState`, `Result`, `ResultStatus`.
- `statectl/state_ctl_engine.py` — `StateCtlEngine` and its private DI container.
- `statectl/interfaces/<capability>/` — ABCs for side-effecting capabilities (e.g. `fs/`, `logger.py`) plus typed errors under `error/`.
- `statectl/modules/<capability>/` — concrete implementations of those interfaces (e.g. `fs/real_file_system.py`).
- `statectl/statechangers/` — concrete `StateChanger` implementations.
- `tests/fakes/` — in-memory / failing fakes used in tests.
- `examples/` — PEP-723 uv scripts depending on the library via `tool.uv.sources = { path = "../", editable = true }`.

## Universal rules

- **No stdlib IO in state changers or modules.** Any filesystem/network/process/clock/env call goes behind an interface in `statectl/interfaces/` with a real impl in `statectl/modules/` and DI wiring in `_Container`. See the `new-capability` skill.
- **No real IO in tests.** Tests drive state changers through fakes (`tests/fakes/`). A test that touches the real disk, network, or process table is a bug.
- **One class per file**, filename = snake_case of class (e.g. `RealFileSystem` → `real_file_system.py`). Small private helpers / sibling dataclasses used only by that class may share the file.
- **`__init__.py` files stay empty.** Import from the actual module path, never via package re-exports.
- Type hints on every signature and class attribute. `assess_state()` is read-only; side effects go in `transition()` / `rollback()`.
- **Run `task check` after completing a plan** (and periodically during longer work) to type-check the project with pyrefly. Fix any errors before reporting the task as done.

## Task-specific guides

Read these only when relevant to the current task:

- Adding a new `StateChanger` → invoke the `new-state-changer` skill.
- Adding a new capability (interface + module + DI wiring) → invoke the `new-capability` skill.
- Reference implementations to read before writing similar code: `statectl/statechangers/new_text_file.py`, `statectl/interfaces/fs/` + `statectl/modules/fs/real_file_system.py`.
