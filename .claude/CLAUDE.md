# statectl

A general framework for declarative state transitions, aimed at OS and infrastructure use cases (creating files, installing packages, configuring services, etc.) but not domain-bound. A driver assembles ordered `StateChanger` instances; the engine assesses current state and applies only what's needed.

## Architecture

Three core concepts:

- **`StateChanger`** (`src/statectl/state_changer.py`) — ABC for one directional state change. Methods: `name()`, `assess_state() -> StateAssessment`, `transition() -> Result`. Bound to a frozen `Parameters` subclass.
- **`RollbackableStateChanger`** — extends `StateChanger` with `rollback() -> StateChanger`. The inverse is a plain `StateChanger`, so the type system forbids rollback-of-rollback.
- **`ExecutionNode`** (`src/statectl/execution_node.py`) — graph node wrapping one `StateChanger` with upstream `depends_on` references. The graph lives outside the changer.
- **`StateCtlEngine`** (`src/statectl/state_ctl_engine.py`) — orchestrator built via `StateCtlEngine.create_engine()`. Drivers `engine.add(node)` then `engine.start(max_workers=...)`; the engine validates the graph (Kahn's, raises `CycleDetectedError` / `UnknownDependencyError`), runs roots in a `ThreadPoolExecutor`, and **fail-isolates** — a failed or `INVALID` node marks only its transitive descendants `BLOCKED`; siblings keep running. `start()` returns an `EngineResult` with per-node `NodeReport`s.

## Layout

Repo uses the **`src/` layout** — the importable package lives at `src/statectl/`, not at the repo root.

- `src/statectl/state_changer.py` — core ABCs + `Parameters`, `StateAssessment`, `ExistingState`, `Result`, `ResultStatus`.
- `src/statectl/state_ctl_engine.py` — `StateCtlEngine` and its private DI container.
- `src/statectl/interfaces/<capability>/` — ABCs for side-effecting capabilities (e.g. `fs/`, `logger.py`) plus the typed error hierarchy in `<capability>_errors.py` (e.g. `fs_errors.py`, `process_errors.py`).
- `src/statectl/modules/<capability>/` — concrete implementations of those interfaces (e.g. `fs/real_file_system.py`).
- `src/statectl/statechangers/` — concrete `StateChanger` implementations.
- `tests/fakes/` — in-memory / failing fakes used in tests.
- `examples/` — PEP-723 uv scripts depending on the library via `tool.uv.sources = { path = "../", editable = true }`.

## Universal rules

- **No stdlib IO in state changers or modules.** Any filesystem/network/process/clock/env call goes behind an interface in `src/statectl/interfaces/` with a real impl in `src/statectl/modules/`. See the `new-capability` skill.
- **Wiring split:** the DI `_Container` wires only engine-internal singletons (logger, engine). State changers are wired manually by the driver — they accept capabilities as constructor kwargs and default `None` to the real impl (e.g. `RealFileSystem()`) so trivial driver code stays terse. Tests inject fakes through the same kwargs. This means it's expected and intentional for `statechangers/*.py` to import from `src/statectl/modules/`.
- **No real IO in tests.** Tests drive state changers through fakes (`tests/fakes/`). A test that touches the real disk, network, or process table is a bug.
- **Top-level types live in their own file** (snake_case name; `RealFileSystem` → `real_file_system.py`). Tightly-coupled groups — error hierarchies, small value-object clusters — share one file named `<group>.py` (e.g. `fs_errors.py` holds `FsError` and all its variants). Small private helpers used only by one class may share that class's file.
- **`__init__.py` is the curated public surface of its package.** Each subpackage's `__init__.py` re-exports its classes with `__all__` using relative imports (`from .file_system import FileSystem as FileSystem`). Callers (tests, examples, cross-subpackage source) import from the package: `from statectl.interfaces.fs import FileSystem, FsNotFound`. Exception: top-level types (`StateChanger`, `Result`, `ExecutionNode`, `StateCtlEngine`, …) are imported from their file (`from statectl.state_changer import StateChanger`) inside source files under `statectl/` to avoid `src/statectl/__init__.py` circular-load issues. External code (tests, examples) imports them from `statectl` directly: `from statectl import StateChanger, ExecutionNode`.
- Type hints on every signature and class attribute. `assess_state()` is read-only; side effects go in `transition()` / `rollback()`.
- **`@override` on every method that overrides an ABC/parent method** (`from typing import override`). Pyrefly is configured with the **strict** preset and rejects unannotated overrides.
- **Run `task check` after completing a plan** (and periodically during longer work) to type-check the project with pyrefly (strict). Fix any errors before reporting the task as done.

## Task-specific guides

Read these only when relevant to the current task:

- Adding a new `StateChanger` → invoke the `new-state-changer` skill.
- Adding a new capability (interface + module + DI wiring) → invoke the `new-capability` skill.
- Reference implementations to read before writing similar code:
  - `src/statectl/statechangers/new_text_file.py` — rollbackable, single capability, content-equivalence idempotency.
  - `src/statectl/statechangers/run_command.py` — non-rollbackable, two capabilities, sentinel-based (`creates`/`removes`) idempotency.
  - `src/statectl/interfaces/fs/` (ABC + `fs_errors.py` + `__init__.py` re-exports) + `src/statectl/modules/fs/real_file_system.py` — capability shape (interface + typed errors + real impl + `_translate()` context manager).
