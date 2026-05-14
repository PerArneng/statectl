# statectl

A general framework for declarative state transitions, aimed at OS and infrastructure use cases (creating files, installing packages, configuring services, etc.) but not domain-bound. A driver assembles ordered `StateChanger` instances; the engine assesses current state and applies only what's needed.

## Architecture

Three core concepts:

- **`StateChanger`** (`src/statectl/state_changer.py`) — ABC for one directional state change. Methods: `name()`, `assess_state() -> StateAssessment`, `transition() -> Result`. Bound to a frozen `Parameters` subclass.
- **`RollbackableStateChanger`** — extends `StateChanger` with `rollback() -> StateChanger`. The inverse is a plain `StateChanger`, so the type system forbids rollback-of-rollback.
- **`StateCtl`** (`src/statectl/state_ctl.py`) — orchestrator built via `StateCtl.new()` (which accepts optional `file_system=` / `process_runner=` overrides for tests). The engine owns capability instances and exposes them via `ctl.changers()` → a `StateChangers` factory. Drivers call `ctl.add(changer, depends_on=[other_changer, ...])` then `ctl.start(max_workers=...)`. Changers themselves are the dependency handles — there is no user-facing node type. Because dependencies must point to already-added changers, cycles are impossible by construction; the only configuration errors are `UnknownDependencyError` (dep not added) and `DuplicateNodeError` (same changer instance added twice), both raised at `add()` time. The engine runs roots in a `ThreadPoolExecutor` and **fail-isolates** — a failed or `INVALID` node marks only its transitive descendants `BLOCKED`; siblings keep running. `start()` returns an `EngineResult` with per-node `NodeReport`s.
- **`StateChangers`** (`src/statectl/statechangers/state_changers.py`) — ergonomic factory for the built-in state changers. Obtained via `ctl.changers()`. Each method (e.g. `sc.new_file(path, text)`, `sc.run("ls -la")`) flattens the `Parameters` + `StateChanger` two-step into one call and threads the engine's capabilities through, so drivers don't repeat `file_system=` per call. Not exposed at top-level `statectl` — reached via `ctl.changers()`.
- **`ExecutionNode`** (`src/statectl/execution_node.py`) — internal graph node the engine constructs per `add()`. Not part of the user-facing construction surface (not re-exported from `statectl`); importable from `statectl.execution_node` for introspection only.

## Layout

Repo uses the **`src/` layout** — the importable package lives at `src/statectl/`, not at the repo root.

- `src/statectl/state_changer.py` — core ABCs + `Parameters`, `StateAssessment`, `ExistingState`, `Result`, `ResultStatus`.
- `src/statectl/state_ctl.py` — `StateCtl` and its private DI container.
- `src/statectl/interfaces/<capability>/` — ABCs for side-effecting capabilities (e.g. `fs/`, `logger.py`) plus the typed error hierarchy in `<capability>_errors.py` (e.g. `fs_errors.py`, `process_errors.py`). Value objects tightly coupled to an ABC (e.g. `FileEntry`, `ProcessResult`) live in the same file as that ABC, not a separate file.
- `src/statectl/modules/` — concrete implementations of those interfaces as flat files (e.g. `real_file_system.py`, `default_logger.py`, `real_process_runner.py`). No per-capability subpackages — each impl is a single file at the `modules/` root, re-exported via `modules/__init__.py`.
- `src/statectl/statechangers/` — concrete `StateChanger` implementations.
- `tests/fakes/` — in-memory / failing fakes used in tests.
- `examples/` — PEP-723 uv scripts depending on the library via `tool.uv.sources = { path = "../", editable = true }`.

## Universal rules

- **No stdlib IO in state changers or modules.** Any filesystem/network/process/clock/env call goes behind an interface in `src/statectl/interfaces/` with a real impl in `src/statectl/modules/`. See the `new-capability` skill.
- **Wiring split:** the DI `_Container` wires engine-internal singletons (logger, filesystem, process_runner, engine) and threads the capabilities into the `StateCtl` constructor; the engine then hands them to the `StateChangers` factory via `ctl.changers()`. State changers themselves still accept capabilities as constructor kwargs defaulting to `None` → real impl, so driver code that constructs changers directly stays terse and tests can inject fakes (either via `StateCtl.new(file_system=fake, ...)` for the factory path, or per-changer kwargs for direct construction). This means it's expected and intentional for `statechangers/*.py` to import from `src/statectl/modules/`.
- **No real IO in tests.** Tests drive state changers through fakes (`tests/fakes/`). A test that touches the real disk, network, or process table is a bug.
- **Top-level types live in their own file** (snake_case name; `RealFileSystem` → `real_file_system.py`), with two exceptions: (1) error hierarchies share one file named `<group>_errors.py` (e.g. `fs_errors.py` holds `FsError` and all its variants); (2) value objects tightly coupled to a single ABC share that ABC's file (e.g. `FileEntry` lives in `file_system.py`, `ProcessResult` in `process_runner.py`). Small private helpers used only by one class may share that class's file.
- **`__init__.py` is the curated public surface of its package.** Each subpackage's `__init__.py` re-exports its classes with `__all__` using relative imports (`from .file_system import FileSystem as FileSystem`). Callers (tests, examples, cross-subpackage source) import from the package: `from statectl.interfaces.fs import FileSystem, FsNotFound`. Exception: top-level types (`StateChanger`, `Result`, `StateCtl`, …) are imported from their file (`from statectl.state_changer import StateChanger`) inside source files under `src/statectl/` to avoid `src/statectl/__init__.py` circular-load issues. External code (tests, examples) imports them from `statectl` directly: `from statectl import StateChanger, StateCtl`.
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
  - `src/statectl/interfaces/fs/` (ABC + `fs_errors.py` + `__init__.py` re-exports) + `src/statectl/modules/real_file_system.py` — capability shape (interface + typed errors + real impl + `_translate()` context manager).
