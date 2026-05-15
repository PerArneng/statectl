---
name: statectl-architecture
description: Complete architectural reference for the statectl codebase — folder layout (src/ layout), core abstractions (StateChanger, capabilities, engine), the DAG execution model, the DI container wiring split, testing strategy with fakes, and the universal rules (no stdlib IO in changers outside modules/, @override on overrides, curated __init__.py re-exports with __all__, type hints everywhere). Use this skill whenever the user asks about how statectl is organized, where something belongs, why a pattern exists, how the engine executes nodes, how dependency injection is wired, how testing works, what the difference between an interface and a module is, or any architectural / design question about this repo. Also use proactively before designing a new feature, reviewing a non-trivial change, or onboarding to the codebase — knowing the architecture up front prevents shaped-wrong proposals. Triggers include phrases like "how does X work in statectl", "where should I put …", "why is …", "what's the pattern for …", "review this design", and any question that names types like StateChanger, StateCtl, Parameters, FileSystem, ProcessRunner.
---

# statectl Architecture

statectl is a small, opinionated framework for **declarative state transitions** — operations that compute the difference between current state and desired state, apply only what's needed, and (where reversible) can be undone. It's aimed at OS / infrastructure work (creating files, running commands, installing packages, configuring services) but the core types are domain-agnostic.

This skill is the architectural reference. CLAUDE.md is the short version; this is the long version. When in doubt about *where* something belongs or *why* a pattern exists, this is the source of truth.

## Mental model

Three layers, with dependencies flowing strictly downward:

```
┌──────────────────────────────────────────────────────────┐
│  Driver code (examples/, user code)                      │
│  Constructs changers, calls engine.add(changer, deps),   │
│  then engine.start()                                     │
└──────────────────────────────────────────────────────────┘
                            │ uses
                            ▼
┌──────────────────────────────────────────────────────────┐
│  Orchestration       statectl/state_ctl.py        │
│  StateCtl — schedules nodes, fail-isolates         │
│  ExecutionNode      statectl/_execution_node.py (internal)│
└──────────────────────────────────────────────────────────┘
                            │ runs
                            ▼
┌──────────────────────────────────────────────────────────┐
│  State changers      statectl/_statechangers/             │
│  Concrete StateChanger / RollbackableStateChanger impls  │
│  — the units of work. Pure logic + capability calls.     │
└──────────────────────────────────────────────────────────┘
                            │ depends on (via DI)
                            ▼
┌──────────────────────────────────────────────────────────┐
│  Capability interfaces     statectl/_interfaces/          │
│  ABCs for side-effecting concerns (fs, process, logger)  │
│  plus typed errors                                       │
└──────────────────────────────────────────────────────────┘
                            │ implemented by
                            ▼
┌──────────────────────────────────────────────────────────┐
│  Real modules        statectl/_modules/                   │
│  Concrete impls (RealFileSystem, RealProcessRunner, …)   │
│  The *only* place stdlib IO is allowed to live.          │
└──────────────────────────────────────────────────────────┘
```

**The cardinal property:** *nothing* in `interfaces/` or `state_changer.py` or `state_ctl.py` imports anything from `modules/`. Side effects live behind ABCs.

**Wiring split — read this carefully, it's a common point of confusion:**

- The **DI container** (`_Container` at the bottom of `state_ctl.py`) wires engine-internal singletons: `logger`, `filesystem`, `process_runner`, and the `engine` itself. The capabilities are threaded into the `StateCtl` constructor (`StateCtl(logger=…, file_system=…, process_runner=…)`). `StateCtl.new(file_system=…, process_runner=…)` lets tests override the providers.
- **The engine owns the capabilities and exposes them via `ctl.changers()`** → a `StateChangers` factory whose methods (`new_file`, `run`, …) flatten the `Parameters` + `StateChanger` ceremony and thread the engine's fs/process-runner through to each changer. This is the recommended driver path for built-in changers.
- **State changers also still accept capabilities as constructor kwargs**, defaulting `None` to the real impl (e.g. `self._fs: FileSystem = file_system or RealFileSystem()`). This is the path the factory uses internally and the path drivers use when constructing a changer by hand (or when tests inject fakes per-changer).
- **Consequence:** it is *expected and intentional* that `statechangers/*.py` imports concrete classes from `src/statectl/_modules/` for those defaults. The package-level dependency graph will show `statechangers/ → modules/` edges; these are not a layering violation, they are the ergonomic seam.

If you ever need a capability to be a true singleton shared across changers (e.g. a connection pool, a clock with a fixed epoch), promote it: have the driver construct it once and pass it into each changer explicitly. Don't add it to `_Container` and don't reach into the container from a changer.

## Folder layout

Repo uses the PyPA-recommended **`src/` layout** — the importable package lives at `src/statectl/`, not at the repo root. This prevents accidental imports of the working-tree copy when running from the repo root and forces tests/examples to use the installed package via `uv sync` / `pip install -e .`.

```
src/statectl/
├── py.typed                    # marks the package as typed (PEP 561)
├── __init__.py                 # public surface — re-exports exactly: StateCtl, EngineResult, NodeReport, NodeOutcome
│
├── _state_changer.py           # core ABCs + value types (StateChanger, Parameters, Result, …)  [internal]
├── _execution_node.py          # ExecutionNode (internal graph node — engine builds these per add())
├── _deferred_handle.py         # DeferredHandle (opaque return type of ctl.add_deferred)
├── state_ctl.py                # StateCtl + private _Container  [re-exported as public]
├── _engine_result.py           # EngineResult, NodeReport, NodeOutcome  [re-exported via __init__]
├── _engine_error.py            # EngineConfigurationError + UnknownDependencyError, DuplicateNodeError,
│                               # DeferredWithoutDependenciesError (raised at add()/add_deferred() time)
│
├── _interfaces/                # Capability ABCs. No real IO allowed here.  [internal]
│   ├── __init__.py             # re-exports Logger
│   ├── logger.py
│   ├── fs/                     # FileSystem ABC + FileEntry value type + fs_errors
│   ├── process/                # ProcessRunner ABC + ProcessResult value type + process_errors
│   ├── archive/                # Archive ABC + archive_errors (tar/zip extraction & creation)
│   └── registry/               # VariableRegistry ABC + registry_errors (typed cross-changer outputs)
│
├── _modules/                   # Concrete impls. Only place stdlib IO lives.  [internal]
│   ├── __init__.py             # re-exports DefaultLogger, RealFileSystem, RealProcessRunner,
│   │                           # RealArchive, InMemoryVariableRegistry
│   ├── default_logger.py
│   ├── real_file_system.py
│   ├── real_process_runner.py
│   ├── real_archive.py
│   └── in_memory_variable_registry.py    # default impl; "real" enough — dict + threading.Lock
│
└── _statechangers/             # Concrete StateChanger implementations  [internal]
    ├── __init__.py             # re-exports all concrete changers + Parameters + value types + StateChangers
    ├── state_changers.py       # StateChangers factory — ergonomic surface for the built-in changers
    │                           # (new_file, ensure_directory, run, delete_path,
    │                           #  ensure_line_in_file, replace_in_file)
    ├── new_text_file.py        # rollbackable, single capability, content-equivalence idempotency
    ├── ensure_directory.py     # rollbackable, single capability
    ├── ensure_line_in_file.py  # rollbackable; uses Placement discriminated union (AtStart/AtEnd/BeforeRegex/AfterRegex)
    ├── replace_in_file.py      # rollbackable; uses Match union (LiteralMatch/RegexMatch)
    ├── delete_path.py          # non-rollbackable; uses PathKind discriminator
    └── run_command.py          # non-rollbackable, multi-capability, sentinel idempotency

tests/
├── _changer_fixtures.py        # shared ProgrammableChanger + publish_value helper used by engine-level tests
├── fakes/                      # In-memory / failing capability fakes — test-only.
│   ├── in_memory_file_system.py
│   ├── failing_file_system.py
│   ├── scripted_process_runner.py
│   ├── failing_process_runner.py
│   ├── scripted_archive.py
│   └── failing_archive.py
├── statechangers/              # Per-changer behavior tests — one file per axis
│                               # (assess_invalid, assess_ready_and_applied, transition_success,
│                               # transition_error_matrix, rollback, invariants, end_to_end_through_engine)
├── test_dag_engine.py          # Engine-level DAG / scheduling tests
├── test_engine_post_assess.py  # Engine ALREADY_APPLIED / SKIPPED handling
├── test_publish_hook.py        # publishes= callback behavior
├── test_variable_registry.py   # VariableRegistry capability behavior
├── test_variable_flow.py       # End-to-end publish → consume across nodes
├── test_add_deferred.py        # add_deferred + DeferredHandle scheduling
└── test_archive.py             # Archive capability behavior

examples/                       # PEP-723 uv scripts using the library — import only from `statectl`
diagrams/                       # Generated (gitignored) — pydeps + pyreverse outputs
```

Why this split: state changers shouldn't know whether they're running against the real filesystem or an in-memory fake, and the engine shouldn't know anything about specific capabilities at all. Keeping interfaces and modules in sibling trees (rather than co-located) makes it physically obvious which is which during code review.

## Core abstractions

### `StateChanger` (`src/statectl/_state_changer.py`)

A directional, idempotent unit of work:

```python
class StateChanger(ABC):
    def name(self) -> str: ...
    def assess_state(self) -> StateAssessment: ...   # READ-ONLY
    def transition(self) -> Result: ...              # side effects live here
```

`assess_state()` returns one of three `ExistingState` values:

| `ExistingState` | Meaning                                           | Engine behavior   |
|-----------------|---------------------------------------------------|-------------------|
| `READY`         | Desired state not yet reached; safe to transition | calls `transition()` |
| `ALREADY_APPLIED` | Already in desired state                        | skip; report SKIPPED_ALREADY_APPLIED |
| `INVALID`       | Preconditions broken; cannot proceed safely       | fail node; block descendants |

`transition()` returns a `Result` whose `ResultStatus` is `SUCCESS`, `SKIPPED`, or `FAILURE`. Use `Result.success(msg)`, `Result.skipped(msg)`, `Result.failure(code, msg)` rather than building dataclasses by hand.

The contract is **idempotency at the assessment layer**: `assess_state` must be cheap, side-effect-free, and reflect whatever the current world looks like, so running the same engine twice does the right thing on the second run.

### `RollbackableStateChanger`

```python
class RollbackableStateChanger(StateChanger):
    def rollback(self) -> StateChanger: ...
```

The inverse of a rollbackable changer is a *plain* `StateChanger`, not another `RollbackableStateChanger`. This is intentional: the type system forbids rollback-of-rollback (which is semantically just "the original change" and would invite bugs). If you find yourself wanting to undo a rollback, you wanted the original changer.

### `Parameters` (frozen dataclass base)

Every changer is constructed with a frozen `Parameters` subclass holding its inputs (paths, argv, text, sentinels, …). Two reasons it's frozen:

1. **Equality semantics.** Changers can be compared and deduplicated by their params.
2. **No surprises mid-run.** A changer that mutated its params during `transition()` would make `assess_state()` non-deterministic.

### `ExecutionNode` (`src/statectl/_execution_node.py`) — internal

An internal graph node the engine constructs from each `engine.add(changer, depends_on=...)` call. **Not part of the user-facing API** — `statectl.__init__` does not re-export it. Users never instantiate `ExecutionNode` directly; the changer itself is the dependency handle. The class is still importable from `statectl._execution_node` for introspection (e.g. tests that inspect the engine's internal graph).

Keeping `ExecutionNode` private means changers stay pure (no graph state on them) and the user-facing API has exactly one construction surface (`engine.add`).

### `StateCtl` (`src/statectl/state_ctl.py`)

Orchestrator. The driver-facing API is `changers()` + `add` + `start`:

```python
ctl = StateCtl.new()
sc = ctl.changers()

a = sc.new_file("/tmp/a.txt", "a\n")
b = sc.new_file("/tmp/b.txt", "b\n")

ctl.add(a)
ctl.add(b, depends_on=[a])       # 'a' must already be added
result = ctl.start(max_workers=4)
```

Direct construction (`NewTextFileStateChanger(NewTextFileParameters(...))`) still works and is the path for custom changers not yet surfaced through `StateChangers`.

**Configuration errors are raised eagerly at `add()` time, before any changer runs:**
- Same changer instance added twice → `DuplicateNodeError`.
- A `depends_on` reference to a changer not yet added → `UnknownDependencyError`.

These are the *only* configuration errors. **Cycles are structurally impossible** because every dependency must point to an already-added changer — the graph is built in topological order by construction. There is no separate validation phase at `start()` time.

**Execution — parallel scheduling:**
- `ThreadPoolExecutor` with `max_workers` (defaults to `os.cpu_count() or 1`).
- All bookkeeping (in-degree, outcomes, blocked-set) lives on the main thread; worker threads only run `_run_node(node)` and return a `NodeReport`. **No locks needed inside the engine** because of this discipline — preserve it.
- **Fail-isolation:** when a node returns `FAILED_INVALID` or `FAILED_TRANSITION`, its transitive descendants are BFS-marked `BLOCKED` and never submitted. Sibling branches keep running.
- Final `EngineResult.ok` is False iff any node ended in a failure or blocked state.

`StateCtl.new()` is the recommended construction path — it uses the `_Container` and wires the real logger, filesystem, and process runner. For tests, `StateCtl.new(file_system=fake_fs, process_runner=fake_pr)` overrides the providers so the engine (and any changer obtained via `ctl.changers()`) sees the fakes.

### `StateChangers` (`src/statectl/_statechangers/state_changers.py`)

Ergonomic factory for the built-in changers, obtained via `ctl.changers()`. Methods flatten the `Parameters` + `StateChanger` two-step and thread the engine's capabilities through:

```python
sc = ctl.changers()
sc.new_file("/tmp/x.txt", "hi")              # → NewTextFileStateChanger
sc.ensure_directory("/tmp/data")             # → EnsureDirectoryStateChanger
sc.run("ls -la")                             # → RunCommandStateChanger (shlex-split string)
sc.run(["echo", "hi there"], creates=p)      # → RunCommandStateChanger (sequence form)
sc.delete_path("/tmp/junk", "file")          # → DeletePathStateChanger
sc.ensure_line_in_file("/etc/cfg", "x", AtEnd())  # → EnsureLineInFileStateChanger
sc.replace_in_file("/etc/cfg", LiteralMatch(...))  # → ReplaceInFileStateChanger
```

The factory surfaces every built-in changer: `new_file`, `ensure_directory`, `run`, `delete_path`, `ensure_line_in_file`, and `replace_in_file`. The discriminated-union inputs (`Placement` for `ensure_line_in_file`, `Match` for `replace_in_file`, `PathKind` for `delete_path`) are passed through as-is — the union itself is the ergonomic surface, so the factory does not try to flatten it further.

Coercions at the boundary: `str | Path` paths are wrapped to `Path`; `Iterable[int]` exit codes are frozen; a string command is `shlex.split`, a sequence is taken verbatim. The factory is **not** re-exported from top-level `statectl` — the engine is the public entry point, and that direction will tighten further (hiding the concrete changer/Parameters classes too) as the library matures.

### `VariableRegistry` (`src/statectl/_interfaces/registry/`)

A capability for sharing typed outputs between changers. The ABC lives at `_interfaces/registry/variable_registry.py`; the default impl `InMemoryVariableRegistry` (a `dict` guarded by `threading.Lock`) lives at `_modules/in_memory_variable_registry.py` and is wired through `_Container` like any other capability. The engine exposes its instance via `ctl.registry()`.

Two driver-facing surfaces use it:

- **`publishes=`** on `ctl.add(changer, depends_on=[...], publishes=lambda ch, res: {...})`. The callback runs only after `SUCCESS` / `SKIPPED_ALREADY_APPLIED` and stores its returned `Mapping[str, Any]` in the registry. Raising from the callback, or returning a duplicate name, marks the node `FAILED_TRANSITION`.
- **`ctl.add_deferred(factory, depends_on=[...])`** schedules a changer that doesn't yet exist. The `factory(registry)` callable runs just before the node would be scheduled — all `depends_on` nodes have already completed and published. The factory's `VariableNotFoundError` / `VariableTypeError` become `FAILED_INVALID`. `add_deferred` requires a non-empty `depends_on` (else `DeferredWithoutDependenciesError` at configuration time) and returns an opaque `DeferredHandle` that is itself a valid `depends_on` target.

This is how data flows between changers without coupling them: upstream publishes a typed name, downstream pulls it from the registry. The DAG edge sequences execution; the registry carries the value. See `examples/variable_registry_db_provision.py`.

### `Archive` (`src/statectl/_interfaces/archive/`)

Capability for archive extraction/creation (tar, zip). ABC + typed errors in `_interfaces/archive/`, real impl `RealArchive` in `_modules/real_archive.py`, fakes `ScriptedArchive` + `FailingArchive` in `tests/fakes/`. Wired through `_Container` like the other capabilities; state changers that need archive operations accept `archive: Archive | None = None` and default to `RealArchive()`.

### `NodeOutcome` / `NodeReport` / `EngineResult` (`src/statectl/_engine_result.py`)

| `NodeOutcome`              | When                                           |
|----------------------------|------------------------------------------------|
| `SUCCESS`                  | transition returned `SUCCESS`                  |
| `SKIPPED_ALREADY_APPLIED`  | assess returned `ALREADY_APPLIED`              |
| `SKIPPED_BY_TRANSITION`    | transition returned `SKIPPED`                  |
| `FAILED_INVALID`           | assess returned `INVALID`                      |
| `FAILED_TRANSITION`        | transition returned `FAILURE`                  |
| `BLOCKED`                  | upstream failed; this node never ran          |

Drivers introspect `EngineResult.reports` (a tuple preserving insertion order). For ad-hoc logs, the engine already prints per-node status lines.

## Capability pattern

Anything that touches the outside world (filesystem, network, processes, clock, env, randomness) goes through a capability:

1. **Interface** in `src/statectl/_interfaces/<capability>/<capability>.py` — pure ABC, type hints, no IO.
2. **Typed errors** in `src/statectl/_interfaces/<capability>/<capability>_errors.py` — a single file containing the base error (`FsError`, `ProcessError`) and every variant (`FsNotFound`, `FsPermissionDenied`, …). Re-export them all from the capability's `__init__.py`.
3. **Real impl** in `src/statectl/_modules/real_<capability>.py` (flat — no per-capability subpackage) — the *only* legal location for stdlib calls related to that capability. Typically uses a `_translate()` context manager that converts stdlib exceptions to typed interface errors. Re-export from `src/statectl/_modules/__init__.py`.
4. **DI wiring** in `_Container` at the bottom of `state_ctl.py` — `providers.Singleton(RealFileSystem)`, etc.
5. **Test fake** in `tests/fakes/` — in-memory implementation honoring the same interface.

The capability error hierarchy is what lets changers `try/except` precisely (e.g. catch `FsNotFound` to mean "file isn't there yet" vs. catch `FsError` for any FS problem). When proposing a new capability, see the `new-capability` skill.

## Universal rules

These rules are non-negotiable because they preserve the layering above. Pyrefly enforces some of them at the type level; reviewers enforce the rest.

1. **No stdlib IO in state changers — only inside `src/statectl/_modules/`.** Any `os`, `pathlib`, `subprocess`, `socket`, `requests`, `time`, `datetime.now()`, `random`, `os.environ` call belongs behind an interface. If you reach for stdlib IO outside `modules/`, that's a missing capability.
   - **Note on imports:** a state changer is allowed (and expected) to `import` a real impl from `modules/` *for the sole purpose* of defaulting a `None` capability kwarg. It must not call stdlib directly.
2. **No real IO in tests.** Tests drive changers through fakes. A test that touches the real disk, network, or process table is a bug — it'll be flaky, slow, and environment-dependent.
3. **Top-level types live in their own file**, filename = snake_case of the class (`RealFileSystem` → `real_file_system.py`), with two exceptions: (a) error hierarchies share one `<group>_errors.py` file (e.g. `fs_errors.py` holds `FsError` plus every variant); (b) value objects tightly coupled to a single ABC live in the same file as that ABC (e.g. `FileEntry` in `file_system.py`, `ProcessResult` in `process_runner.py`). Small private helpers used only by one class may also share that class's file (e.g. `RecordedCall` next to `ScriptedProcessRunner`).
4. **`__init__.py` is the curated public surface of its package.** Each subpackage's `__init__.py` re-exports its classes using relative imports and `__all__`:
   ```python
   # statectl/_interfaces/fs/__init__.py
   from .file_system import FileEntry as FileEntry, FileSystem as FileSystem
   from .fs_errors import FsError as FsError, FsNotFound as FsNotFound, ...
   __all__ = ["FileEntry", "FileSystem", "FsError", "FsNotFound", ...]
   ```
   Internal callers (tests, cross-subpackage source) import from the package surface: `from statectl._interfaces.fs import FileSystem, FsNotFound`. Top-level types are imported from their file (`from statectl._state_changer import StateChanger`) — not via `from statectl import ...` — both to avoid circular-load issues with the partially-initialized `src/statectl/__init__.py` *and* because `statectl.__all__` only exposes the four public names (`StateCtl`, `EngineResult`, `NodeReport`, `NodeOutcome`); everything else is internal. External driver code therefore only ever does `from statectl import StateCtl`.
5. **Type hints on every signature and class attribute.** No bare `def foo(x):`. No untyped `self._x = None` either — annotate the attribute.
6. **`@override` on every method that overrides an ABC or parent method** (`from typing import override`). Pyrefly is configured strict and rejects unannotated overrides. This catches typos in method names (`asses_state` vs `assess_state`) before runtime.
7. **`assess_state()` is read-only.** Side effects belong in `transition()` / `rollback()`. Violating this breaks idempotency.
8. **Frozen `Parameters`.** Always `@dataclass(frozen=True)`.
9. **Run `task check` before declaring work done.** Pyrefly (strict) is the gate; fix errors before reporting. `task diagrams` regenerates the architecture pictures if you want to see your change visually.

## Testing strategy

Two layers of tests, both fully in-process:

**Per-changer tests** (`tests/statechangers/`): construct a changer with fakes, exercise `assess_state` and `transition`, assert on fake state (e.g. `fs.read_text(path)`) or recorded calls (e.g. `pr.calls`). The convention is one file per axis per changer: `test_<changer>_assess_invalid.py`, `_assess_ready_and_applied.py`, `_transition_success.py`, `_transition_error_matrix.py`, `_rollback.py` (for rollbackables), `_invariants.py`, `_end_to_end_through_engine.py`. The fakes are deliberately simple:

- `InMemoryFileSystem` — dict-backed, with `add_dir` / `add_file` helpers and `set_writable` / `set_readable_text` to simulate permission failures.
- `ScriptedProcessRunner` — register executables (`which` succeeds), register results by argv prefix, every `run` call records to `.calls`.
- `ScriptedArchive` — register archive contents by source path; records extract/create calls.
- `FailingFileSystem` / `FailingProcessRunner` / `FailingArchive` — every operation raises a configured error. Useful for error-matrix tests.

**Engine-level tests** are split by concern:

- `tests/test_dag_engine.py` — scheduling, fail-isolation, parallelism. Uses a file-local `_ProgrammableChanger`.
- `tests/test_engine_post_assess.py` — `ALREADY_APPLIED` / `SKIPPED` handling.
- `tests/test_publish_hook.py` — `publishes=` callback semantics.
- `tests/test_variable_registry.py` + `tests/test_variable_flow.py` — registry capability + end-to-end publish→consume flow.
- `tests/test_add_deferred.py` — `add_deferred` + `DeferredHandle`.
- `tests/test_archive.py` — Archive capability.

Engine tests that need a configurable test changer beyond a single file import from `tests/_changer_fixtures.py`, which exports `ProgrammableChanger` (and a `publish_value(...)` helper for `publishes=` callbacks). When adding a new engine-level test that needs a programmable changer, prefer the shared fixture over re-defining one. Set `max_workers=1` for determinism unless you're specifically testing parallelism.

**Don't add a test-only side door to production code** to make testing easier. If you can't test something through the public interface, the interface is probably wrong (or you need a new capability fake). The fakes give you enough lateral surface area without compromising the production API.

## Reference implementations to read

When writing similar code, read the closest existing reference first:

- `src/statectl/_statechangers/new_text_file.py` — rollbackable, single capability (FileSystem), content-equivalence idempotency (compares actual file content to desired text).
- `src/statectl/_statechangers/run_command.py` — non-rollbackable, two capabilities (FileSystem + ProcessRunner), sentinel-based idempotency via `creates` / `removes` paths. Demonstrates the multi-capability pattern.
- `src/statectl/_statechangers/ensure_line_in_file.py` — rollbackable; demonstrates a `Placement` discriminated union (`AtStart` / `AtEnd` / `BeforeRegex` / `AfterRegex`) for expressing where a line goes when it's missing.
- `src/statectl/_statechangers/replace_in_file.py` — rollbackable; demonstrates a `Match` union (`LiteralMatch` / `RegexMatch`) for selecting the substring to replace.
- `src/statectl/_interfaces/fs/` (ABC + `FileEntry` in `file_system.py`, errors in `fs_errors.py`, public surface in `__init__.py`) + `src/statectl/_modules/real_file_system.py` — the full capability shape: ABC, typed error hierarchy, real impl, `_translate()` context manager that maps stdlib exceptions to typed interface errors.

## Task-specific guides

These task-flavored skills cover the *how* of common changes — this skill covers the *why* of the structure:

- **Adding a new `StateChanger`** → `new-state-changer` skill.
- **Adding a new capability (interface + module + DI wiring + fake)** → `new-capability` skill.
- **Generating architecture diagrams** → `generate-diagrams` skill (PNG / Mermaid / PlantUML via pydeps + pyreverse).

## Common questions, briefly answered

**"Where does X live?"**  
Decision tree: side-effecting? → capability. Configuration error? → `engine_error.py`. Value type returned by the engine? → `engine_result.py`. Pure unit of work? → `statechangers/`. Anything else is probably wrong.

**"Why does `__init__.py` re-export the public surface?"**  
This matches mainstream Python (stdlib, requests, pydantic, httpx) and keeps imports terse. The trade is that the package-level dependency graph (pydeps) now shows package-to-package edges rather than file-to-file — that's the intended representation. For file-level granularity when debugging, `pyreverse`'s class diagram still works at the class level.

**"Why is the engine fail-isolating instead of fail-fast?"**  
With a DAG, fail-fast wastes the work of parallel branches that have nothing to do with the failure. Descendants of a failing node *should* be skipped (their preconditions are gone), but siblings shouldn't be. The driver gets a complete `EngineResult` and can decide what to do with partial success.

**"Can a changer depend on another changer's output?"**  
Implicitly, via the world. `RunCommandStateChanger(creates=marker)` followed by another changer that reads `marker` works because both see the real filesystem. The dependency edge in the DAG just sequences them; data flow goes through capabilities, not through node return values. This is intentional — it keeps changers loosely coupled and replayable.

**"Why use threads instead of asyncio?"**  
Changers are synchronous and largely IO-bound. Async would force every changer and every capability ABC to be async, which is a huge refactor for no real throughput gain at our scale. Threads + the GIL are fine: capabilities release the GIL during real IO, and pure-Python work between IO calls is negligible.
