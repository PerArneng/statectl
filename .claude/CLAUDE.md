# statectl

A general framework for declarative state transitions, aimed at OS and infrastructure use cases (creating files, installing packages, configuring services, etc.) but not domain-bound. A driver assembles ordered `StateChanger` instances; the engine assesses current state and applies only what's needed.

## Architecture

Three core concepts:

- **`StateChanger`** (`statectl/state_changer.py`) — ABC for one directional state change. Methods: `name()`, `assess_state() -> StateAssessment`, `transition() -> Result`. Bound to a frozen `Parameters` subclass.
- **`RollbackableStateChanger`** — extends `StateChanger` with `rollback() -> StateChanger`. The inverse is a plain `StateChanger`, so the type system forbids rollback-of-rollback.
- **`ExecutionNode`** (`statectl/execution_node.py`) — graph node wrapping one `StateChanger` with upstream `depends_on` references. The graph lives outside the changer.
- **`StateCtlEngine`** (`statectl/state_ctl_engine.py`) — orchestrator built via `StateCtlEngine.create_engine()`. Drivers `engine.add(node)` then `engine.start(max_workers=...)`; the engine validates the graph (Kahn's, raises `CycleDetectedError` / `UnknownDependencyError`), runs roots in a `ThreadPoolExecutor`, and **fail-isolates** — a failed or `INVALID` node marks only its transitive descendants `BLOCKED`; siblings keep running. `start()` returns an `EngineResult` with per-node `NodeReport`s.

## Layout

- `statectl/state_changer.py` — core ABCs + `Parameters`, `StateAssessment`, `ExistingState`, `Result`, `ResultStatus`.
- `statectl/state_ctl_engine.py` — `StateCtlEngine` and its private DI container.
- `statectl/interfaces/<capability>/` — ABCs for side-effecting capabilities (e.g. `fs/`, `logger.py`) plus typed errors under `error/`.
- `statectl/modules/<capability>/` — concrete implementations of those interfaces (e.g. `fs/real_file_system.py`).
- `statectl/statechangers/` — concrete `StateChanger` implementations.
- `tests/fakes/` — in-memory / failing fakes used in tests.
- `examples/` — PEP-723 uv scripts depending on the library via `tool.uv.sources = { path = "../", editable = true }`.

## Universal rules

- **No stdlib IO in state changers or modules.** Any filesystem/network/process/clock/env call goes behind an interface in `statectl/interfaces/` with a real impl in `statectl/modules/`. See the `new-capability` skill.
- **Wiring split:** the DI `_Container` wires only engine-internal singletons (logger, engine). State changers are wired manually by the driver — they accept capabilities as constructor kwargs and default `None` to the real impl (e.g. `RealFileSystem()`) so trivial driver code stays terse. Tests inject fakes through the same kwargs. This means it's expected and intentional for `statechangers/*.py` to import from `statectl/modules/`.
- **No real IO in tests.** Tests drive state changers through fakes (`tests/fakes/`). A test that touches the real disk, network, or process table is a bug.
- **One class per file**, filename = snake_case of class (e.g. `RealFileSystem` → `real_file_system.py`). Small private helpers / sibling dataclasses used only by that class may share the file.
- **`__init__.py` files stay empty.** Import from the actual module path, never via package re-exports.
- Type hints on every signature and class attribute. `assess_state()` is read-only; side effects go in `transition()` / `rollback()`.
- **`@override` on every method that overrides an ABC/parent method** (`from typing import override`). Pyrefly is configured with the **strict** preset and rejects unannotated overrides.
- **Run `task check` after completing a plan** (and periodically during longer work) to type-check the project with pyrefly (strict). Fix any errors before reporting the task as done.

## Task-specific guides

Read these only when relevant to the current task:

- Adding a new `StateChanger` → invoke the `new-state-changer` skill.
- Adding a new capability (interface + module + DI wiring) → invoke the `new-capability` skill.
- Reference implementations to read before writing similar code:
  - `statectl/statechangers/new_text_file.py` — rollbackable, single capability, content-equivalence idempotency.
  - `statectl/statechangers/run_command.py` — non-rollbackable, two capabilities, sentinel-based (`creates`/`removes`) idempotency.
  - `statectl/interfaces/fs/` + `statectl/modules/fs/real_file_system.py` — capability shape (interface + typed errors + real impl + `_translate()` context manager).
