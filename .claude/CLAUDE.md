# statectl

A general framework for declarative state transitions, aimed at OS and infrastructure use cases (creating files, installing packages, configuring services, etc.) but not domain-bound. A driver assembles ordered `StateChanger` instances; the engine assesses current state and applies only what's needed.

## Public API

The `statectl` package re-exports exactly four names — and nothing else — from its top-level `__init__.py`: `StateCtl`, `EngineResult`, `NodeReport`, `NodeOutcome`. Everything else lives under underscore-prefixed modules (`_state_changer`, `_engine_error`, `_execution_node`, `_interfaces`, `_modules`, `_statechangers`) and is internal — it may move or change without notice. Internal modules are still importable for tests and introspection but must not be relied on by external drivers.

## Architecture

Three core concepts:

- **`StateChanger`** (`src/statectl/_state_changer.py`) — ABC for one directional state change. Methods: `name()`, `assess_state() -> StateAssessment`, `transition() -> Result`. Bound to a frozen `Parameters` subclass.
- **`RollbackableStateChanger`** — extends `StateChanger` with `rollback() -> StateChanger`. The inverse is a plain `StateChanger`, so the type system forbids rollback-of-rollback.
- **`StateCtl`** (`src/statectl/state_ctl.py`) — orchestrator built via `StateCtl.new()` (which accepts optional `file_system=` / `process_runner=` overrides for tests). The engine owns capability instances and exposes them via `ctl.changers()` → a `StateChangers` factory, and via `ctl.registry()` → the shared `VariableRegistry`. Drivers call `ctl.add(changer, depends_on=[other_changer, ...])` then `ctl.start(max_workers=...)`. Changers themselves are the dependency handles — there is no user-facing node type. Because dependencies must point to already-added changers, cycles are impossible by construction; the only configuration errors are `UnknownDependencyError` (dep not added) and `DuplicateNodeError` (same changer instance added twice), both raised at `add()` time. The engine runs roots in a `ThreadPoolExecutor` and **fail-isolates** — a failed or `INVALID` node marks only its transitive descendants `BLOCKED`; siblings keep running. `start()` returns an `EngineResult` with per-node `NodeReport`s.
- **`StateChangers`** (`src/statectl/_statechangers/state_changers.py`) — ergonomic factory for the built-in state changers. Obtained via `ctl.changers()`. Each method (e.g. `sc.new_file(path, text)`, `sc.run("ls -la")`) flattens the `Parameters` + `StateChanger` two-step into one call and threads the engine's capabilities through, so drivers don't repeat `file_system=` per call. Reached only via `ctl.changers()`.
- **`VariableRegistry`** (`src/statectl/_interfaces/registry/variable_registry.py`) — capability for sharing typed outputs between changers. Real impl `InMemoryVariableRegistry` is a `dict` + `threading.Lock`. Engine exposes its registry via `ctl.registry()`. Drivers attach a `publishes=lambda ch, res: {...}` to `ctl.add(...)` to capture outputs after `SUCCESS` / `SKIPPED_ALREADY_APPLIED`, and call `ctl.add_deferred(factory, depends_on=[...])` to construct a changer once its inputs are known (factory receives the registry and runs just before scheduling). `add_deferred` returns a `DeferredHandle` that is itself a valid `depends_on` target. Factory raises `VariableNotFoundError` / `VariableTypeError` → `FAILED_INVALID`; publish callback raises or returns a duplicate name → `FAILED_TRANSITION`. See `examples/variable_registry_db_provision.py`.
- **`ExecutionNode`** (`src/statectl/_execution_node.py`) — internal graph node the engine constructs per `add()`. Not part of the user-facing construction surface; importable from the underscore-prefixed module for introspection only.
- **`DeferredHandle`** (`src/statectl/_deferred_handle.py`) — opaque value returned by `ctl.add_deferred(...)`. Drivers pass it back as a `depends_on` element; they never construct or import it directly. Not part of the curated public surface.

## Layout

Repo uses the **`src/` layout** — the importable package lives at `src/statectl/`, not at the repo root.

- `src/statectl/_state_changer.py` — core ABCs + `Parameters`, `StateAssessment`, `ExistingState`, `Result`, `ResultStatus`.
- `src/statectl/state_ctl.py` — `StateCtl` and its private DI container.
- `src/statectl/_engine_result.py` — `EngineResult`, `NodeReport`, `NodeOutcome` (re-exported from root).
- `src/statectl/_engine_error.py` — `EngineConfigurationError`, `UnknownDependencyError`, `DuplicateNodeError`, `DeferredWithoutDependenciesError`.
- `src/statectl/_deferred_handle.py` — `DeferredHandle` (opaque return type of `add_deferred`).
- `src/statectl/_interfaces/<capability>/` — ABCs for side-effecting capabilities (e.g. `fs/`, `registry/`, `logger.py`) plus the typed error hierarchy in `<capability>_errors.py` (e.g. `fs_errors.py`, `registry_errors.py`, `process_errors.py`). Value objects tightly coupled to an ABC (e.g. `FileEntry`, `ProcessResult`) live in the same file as that ABC, not a separate file.
- `src/statectl/_modules/` — concrete implementations of those interfaces as flat files (e.g. `real_file_system.py`, `default_logger.py`, `real_process_runner.py`). No per-capability subpackages — each impl is a single file at the `_modules/` root, re-exported via `_modules/__init__.py`.
- `src/statectl/_statechangers/` — concrete `StateChanger` implementations.
- `tests/fakes/` — in-memory / failing fakes used in tests.
- `examples/` — PEP-723 uv scripts depending on the library via `tool.uv.sources = { path = "../", editable = true }`. Examples import only from the public `statectl` namespace.

## Universal rules

- **No stdlib IO in state changers.** Any filesystem/network/process/clock/env call goes behind an interface in `src/statectl/_interfaces/` with a real impl in `src/statectl/_modules/`. `_modules/` is the *only* place stdlib IO is allowed to live. See the `new-capability` skill.
- **Wiring split:** the DI `_Container` wires engine-internal singletons (logger, filesystem, process_runner, engine) and threads the capabilities into the `StateCtl` constructor; the engine then hands them to the `StateChangers` factory via `ctl.changers()`. State changers themselves still accept capabilities as constructor kwargs defaulting to `None` → real impl, so driver code that constructs changers directly stays terse and tests can inject fakes (either via `StateCtl.new(file_system=fake, ...)` for the factory path, or per-changer kwargs for direct construction). This means it's expected and intentional for `_statechangers/*.py` to import from `src/statectl/_modules/`.
- **No real IO in tests.** Tests drive state changers through fakes (`tests/fakes/`). A test that touches the real disk, network, or process table is a bug.
- **Top-level types live in their own file** (snake_case name; `RealFileSystem` → `real_file_system.py`), with two exceptions: (1) error hierarchies share one file named `<group>_errors.py` (e.g. `fs_errors.py` holds `FsError` and all its variants); (2) value objects tightly coupled to a single ABC share that ABC's file (e.g. `FileEntry` lives in `file_system.py`, `ProcessResult` in `process_runner.py`). Small private helpers used only by one class may share that class's file.
- **`__init__.py` is the curated public surface of its package.** Each subpackage's `__init__.py` re-exports its classes with `__all__` using relative imports (`from .file_system import FileSystem as FileSystem`). Internal callers (tests, cross-subpackage source) import from the package: `from statectl._interfaces.fs import FileSystem, FsNotFound`. Top-level types imported across modules inside `src/statectl/` use the file path (`from statectl._state_changer import StateChanger`) to avoid `src/statectl/__init__.py` circular-load issues. External code (examples) only imports the public four from `statectl` directly: `from statectl import StateCtl`.
- Type hints on every signature and class attribute. `assess_state()` is read-only; side effects go in `transition()` / `rollback()`.
- **`@override` on every method that overrides an ABC/parent method** (`from typing import override`). Pyrefly is configured with the **strict** preset and rejects unannotated overrides.
- **Run `task check` after completing a plan** (and periodically during longer work) to type-check the project with pyrefly (strict). Fix any errors before reporting the task as done.
- **Run `task complexity` to check cyclomatic complexity** (ruff `C901`, max-complexity = 10). Fix any violations before reporting the task as done.
- **As part of linting (before final testing), regenerate `diagrams/packages_statectl.mmd`** via `task diagram-uml-mmd` and review it against the architecture described above. Flag any unexpected cross-package imports or layering violations (e.g. `_interfaces` depending on `_modules`, `_statechangers` bypassing `_interfaces`) and fix them before running the final tests.

## Work tracking

Work is driven by **GitHub Issues** on `PerArneng/statectl`, organized on a Project v2 Kanban board (`Todo` → `In Progress` → `Done`) at https://github.com/users/PerArneng/projects/1. Issues carry `tier-N` and `kind:*` labels. Before starting code, move the card to `In Progress` and link a branch; on merge, `Closes #N` in the PR moves it to `Done`. **Every commit must reference its issue number** (e.g. `Add FileSystem.chmod (#1)`) so commits show up on the issue timeline. For the full workflow (URLs, GraphQL mutations, branch naming) → invoke the `github-task-workflow` skill.

## Task-specific guides

Read these only when relevant to the current task:

- Picking up / progressing / closing a roadmap issue → invoke the `github-task-workflow` skill.
- Adding a new `StateChanger` → invoke the `new-state-changer` skill.
- Adding a new capability (interface + module + DI wiring) → invoke the `new-capability` skill.
- Reference implementations to read before writing similar code:
  - `src/statectl/_statechangers/new_text_file.py` — rollbackable, single capability, content-equivalence idempotency.
  - `src/statectl/_statechangers/run_command.py` — non-rollbackable, two capabilities, sentinel-based (`creates`/`removes`) idempotency.
  - `src/statectl/_interfaces/fs/` (ABC + `fs_errors.py` + `__init__.py` re-exports) + `src/statectl/_modules/real_file_system.py` — capability shape (interface + typed errors + real impl + `_translate()` context manager).
