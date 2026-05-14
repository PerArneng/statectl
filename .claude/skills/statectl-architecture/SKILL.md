---
name: statectl-architecture
description: Complete architectural reference for the statectl codebase — folder layout (src/ layout), core abstractions (StateChanger, ExecutionNode, capabilities, engine), the DAG execution model, the DI container wiring split, testing strategy with fakes, and the universal rules (no stdlib IO in changers outside modules/, @override on overrides, curated __init__.py re-exports with __all__, type hints everywhere). Use this skill whenever the user asks about how statectl is organized, where something belongs, why a pattern exists, how the engine executes nodes, how dependency injection is wired, how testing works, what the difference between an interface and a module is, or any architectural / design question about this repo. Also use proactively before designing a new feature, reviewing a non-trivial change, or onboarding to the codebase — knowing the architecture up front prevents shaped-wrong proposals. Triggers include phrases like "how does X work in statectl", "where should I put …", "why is …", "what's the pattern for …", "review this design", and any question that names types like StateChanger, ExecutionNode, StateCtlEngine, Parameters, FileSystem, ProcessRunner.
---

# statectl Architecture

statectl is a small, opinionated framework for **declarative state transitions** — operations that compute the difference between current state and desired state, apply only what's needed, and (where reversible) can be undone. It's aimed at OS / infrastructure work (creating files, running commands, installing packages, configuring services) but the core types are domain-agnostic.

This skill is the architectural reference. CLAUDE.md is the short version; this is the long version. When in doubt about *where* something belongs or *why* a pattern exists, this is the source of truth.

## Mental model

Three layers, with dependencies flowing strictly downward:

```
┌──────────────────────────────────────────────────────────┐
│  Driver code (examples/, user code)                      │
│  Builds ExecutionNodes, wires the DAG, calls start()     │
└──────────────────────────────────────────────────────────┘
                            │ uses
                            ▼
┌──────────────────────────────────────────────────────────┐
│  Orchestration       statectl/state_ctl_engine.py        │
│  StateCtlEngine — validates the graph, schedules nodes   │
│  ExecutionNode      statectl/execution_node.py           │
└──────────────────────────────────────────────────────────┘
                            │ runs
                            ▼
┌──────────────────────────────────────────────────────────┐
│  State changers      statectl/statechangers/             │
│  Concrete StateChanger / RollbackableStateChanger impls  │
│  — the units of work. Pure logic + capability calls.     │
└──────────────────────────────────────────────────────────┘
                            │ depends on (via DI)
                            ▼
┌──────────────────────────────────────────────────────────┐
│  Capability interfaces     statectl/interfaces/          │
│  ABCs for side-effecting concerns (fs, process, logger)  │
│  plus typed errors                                       │
└──────────────────────────────────────────────────────────┘
                            │ implemented by
                            ▼
┌──────────────────────────────────────────────────────────┐
│  Real modules        statectl/modules/                   │
│  Concrete impls (RealFileSystem, RealProcessRunner, …)   │
│  The *only* place stdlib IO is allowed to live.          │
└──────────────────────────────────────────────────────────┘
```

**The cardinal property:** *nothing* in `interfaces/` or `state_changer.py` or `state_ctl_engine.py` imports anything from `modules/`. Side effects live behind ABCs.

**Wiring split — read this carefully, it's a common point of confusion:**

- The **DI container** (`_Container` at the bottom of `state_ctl_engine.py`) wires only **engine-internal** singletons: the logger and the engine itself. It also declares `filesystem` and `process_runner` providers, but those exist as a convenience — the engine doesn't inject them into state changers.
- **State changers are wired manually by the driver.** Each changer accepts its capabilities as constructor kwargs and defaults `None` to the real impl (e.g. `self._fs: FileSystem = file_system or RealFileSystem()`). This keeps driver code terse — `NewTextFileStateChanger(params)` just works — while tests inject fakes through the same kwargs.
- **Consequence:** it is *expected and intentional* that `statechangers/*.py` imports concrete classes from `src/statectl/modules/` for those defaults. The package-level dependency graph will show `statechangers/ → modules/` edges; these are not a layering violation, they are the ergonomic seam.

If you ever need a capability to be a true singleton shared across changers (e.g. a connection pool, a clock with a fixed epoch), promote it: have the driver construct it once and pass it into each changer explicitly. Don't add it to `_Container` and don't reach into the container from a changer.

## Folder layout

Repo uses the PyPA-recommended **`src/` layout** — the importable package lives at `src/statectl/`, not at the repo root. This prevents accidental imports of the working-tree copy when running from the repo root and forces tests/examples to use the installed package via `uv sync` / `pip install -e .`.

```
src/statectl/
├── py.typed                    # marks the package as typed (PEP 561)
├── state_changer.py            # core ABCs + value types (StateChanger, Parameters, Result, …)
├── execution_node.py           # ExecutionNode (graph node wrapping one changer)
├── state_ctl_engine.py         # StateCtlEngine + private _Container
├── engine_result.py            # EngineResult, NodeReport, NodeOutcome
├── engine_error.py             # CycleDetectedError, UnknownDependencyError, DuplicateNodeError
│
├── __init__.py                 # public surface (re-exports top-level types with __all__)
│
├── interfaces/                 # Capability ABCs. No real IO allowed here.
│   ├── __init__.py             # re-exports Logger
│   ├── logger.py
│   ├── fs/
│   │   ├── __init__.py         # re-exports FileSystem, FileEntry, FsError + variants
│   │   ├── file_system.py      # the ABC + FileEntry value object (coupled, lives together)
│   │   └── fs_errors.py        # FsError base + all variants in one file
│   └── process/
│       ├── __init__.py         # re-exports ProcessRunner, ProcessResult, ProcessError + variants
│       ├── process_runner.py   # the ABC + ProcessResult value object (coupled, lives together)
│       └── process_errors.py   # ProcessError base + all variants in one file
│
├── modules/                    # Concrete impls. Only place stdlib IO lives.
│   ├── __init__.py             # re-exports RealFileSystem, DefaultLogger, RealProcessRunner
│   ├── real_file_system.py
│   ├── default_logger.py
│   └── real_process_runner.py
│
└── statechangers/              # Concrete StateChanger implementations
    ├── __init__.py             # re-exports all concrete changers + Parameters
    ├── new_text_file.py        # rollbackable, single capability
    └── run_command.py          # non-rollbackable, multi-capability, sentinel idempotency

tests/
├── fakes/                      # In-memory / failing capability fakes — test-only.
│   ├── in_memory_file_system.py
│   ├── failing_file_system.py
│   ├── scripted_process_runner.py
│   └── failing_process_runner.py
├── statechangers/              # Per-changer behavior tests
└── test_dag_engine.py          # Engine-level DAG tests

examples/                       # PEP-723 uv scripts using the library
diagrams/                       # Generated (gitignored) — pydeps + pyreverse outputs
```

Why this split: state changers shouldn't know whether they're running against the real filesystem or an in-memory fake, and the engine shouldn't know anything about specific capabilities at all. Keeping interfaces and modules in sibling trees (rather than co-located) makes it physically obvious which is which during code review.

## Core abstractions

### `StateChanger` (`src/statectl/state_changer.py`)

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

### `ExecutionNode` (`src/statectl/execution_node.py`)

A node in the engine's execution DAG. Wraps exactly one `StateChanger` and holds upstream node references. Identity is the node object itself — *not* the wrapped changer's name. (You could legitimately have two nodes wrapping different instances of the same changer type with different parameters.)

```python
node_a = ExecutionNode(changer_a)
node_b = ExecutionNode(changer_b, depends_on=[node_a])
node_c = ExecutionNode(changer_c).depends_on(node_a, node_b)
```

Important: the changer is the unit of work, the node is the unit of *graph membership*. Keeping them separate means changers stay pure (no graph state on them) and the same changer instance could in principle appear in multiple nodes — though deliberate, not accidental.

### `StateCtlEngine` (`src/statectl/state_ctl_engine.py`)

Orchestrator. Two-phase execution:

**Phase A — validation (before any changer runs):**
1. Every referenced upstream node must have been `add`ed → else `UnknownDependencyError`.
2. Same node added twice → `DuplicateNodeError` (caught at `add()` time, not `start()`).
3. Run Kahn's algorithm over the graph; if not all nodes get visited, the unvisited set is a cycle → `CycleDetectedError(nodes=[...])`.

These are *configuration* errors — they raise before any side effect happens. Catch them in the driver if you want; don't catch them inside a changer.

**Phase B — parallel scheduling:**
- `ThreadPoolExecutor` with `max_workers` (defaults to `os.cpu_count() or 1`).
- All bookkeeping (in-degree, outcomes, blocked-set) lives on the main thread; worker threads only run `_run_node(node)` and return a `NodeReport`. **No locks needed inside the engine** because of this discipline — preserve it.
- **Fail-isolation:** when a node returns `FAILED_INVALID` or `FAILED_TRANSITION`, its transitive descendants are BFS-marked `BLOCKED` and never submitted. Sibling branches keep running.
- Final `EngineResult.ok` is False iff any node ended in a failure or blocked state.

`StateCtlEngine.create_engine()` is the recommended construction path — it uses the `_Container` and wires the real logger. Driver code rarely needs to inject capabilities by hand; changers accept capabilities as constructor kwargs with `None` → real-impl defaults.

### `NodeOutcome` / `NodeReport` / `EngineResult` (`src/statectl/engine_result.py`)

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

1. **Interface** in `src/statectl/interfaces/<capability>/<capability>.py` — pure ABC, type hints, no IO.
2. **Typed errors** in `src/statectl/interfaces/<capability>/<capability>_errors.py` — a single file containing the base error (`FsError`, `ProcessError`) and every variant (`FsNotFound`, `FsPermissionDenied`, …). Re-export them all from the capability's `__init__.py`.
3. **Real impl** in `src/statectl/modules/real_<capability>.py` (flat — no per-capability subpackage) — the *only* legal location for stdlib calls related to that capability. Typically uses a `_translate()` context manager that converts stdlib exceptions to typed interface errors. Re-export from `src/statectl/modules/__init__.py`.
4. **DI wiring** in `_Container` at the bottom of `state_ctl_engine.py` — `providers.Singleton(RealFileSystem)`, etc.
5. **Test fake** in `tests/fakes/` — in-memory implementation honoring the same interface.

The capability error hierarchy is what lets changers `try/except` precisely (e.g. catch `FsNotFound` to mean "file isn't there yet" vs. catch `FsError` for any FS problem). When proposing a new capability, see the `new-capability` skill.

## Universal rules

These rules are non-negotiable because they preserve the layering above. Pyrefly enforces some of them at the type level; reviewers enforce the rest.

1. **No stdlib IO in state changers — only inside `src/statectl/modules/`.** Any `os`, `pathlib`, `subprocess`, `socket`, `requests`, `time`, `datetime.now()`, `random`, `os.environ` call belongs behind an interface. If you reach for stdlib IO outside `modules/`, that's a missing capability.
   - **Note on imports:** a state changer is allowed (and expected) to `import` a real impl from `modules/` *for the sole purpose* of defaulting a `None` capability kwarg. It must not call stdlib directly.
2. **No real IO in tests.** Tests drive changers through fakes. A test that touches the real disk, network, or process table is a bug — it'll be flaky, slow, and environment-dependent.
3. **Top-level types live in their own file**, filename = snake_case of the class (`RealFileSystem` → `real_file_system.py`), with two exceptions: (a) error hierarchies share one `<group>_errors.py` file (e.g. `fs_errors.py` holds `FsError` plus every variant); (b) value objects tightly coupled to a single ABC live in the same file as that ABC (e.g. `FileEntry` in `file_system.py`, `ProcessResult` in `process_runner.py`). Small private helpers used only by one class may also share that class's file (e.g. `RecordedCall` next to `ScriptedProcessRunner`).
4. **`__init__.py` is the curated public surface of its package.** Each subpackage's `__init__.py` re-exports its classes using relative imports and `__all__`:
   ```python
   # statectl/interfaces/fs/__init__.py
   from .file_system import FileEntry as FileEntry, FileSystem as FileSystem
   from .fs_errors import FsError as FsError, FsNotFound as FsNotFound, ...
   __all__ = ["FileEntry", "FileSystem", "FsError", "FsNotFound", ...]
   ```
   Callers (tests, examples, cross-subpackage source) import from the package surface: `from statectl.interfaces.fs import FileSystem, FsNotFound`. **Exception:** inside source files under `src/statectl/`, top-level types are imported from their file (`from statectl.state_changer import StateChanger`) — not via `from statectl import ...` — to avoid circular-load issues with the partially-initialized `src/statectl/__init__.py`. External code (tests, examples) does `from statectl import StateChanger, ExecutionNode`.
5. **Type hints on every signature and class attribute.** No bare `def foo(x):`. No untyped `self._x = None` either — annotate the attribute.
6. **`@override` on every method that overrides an ABC or parent method** (`from typing import override`). Pyrefly is configured strict and rejects unannotated overrides. This catches typos in method names (`asses_state` vs `assess_state`) before runtime.
7. **`assess_state()` is read-only.** Side effects belong in `transition()` / `rollback()`. Violating this breaks idempotency.
8. **Frozen `Parameters`.** Always `@dataclass(frozen=True)`.
9. **Run `task check` before declaring work done.** Pyrefly (strict) is the gate; fix errors before reporting. `task diagrams` regenerates the architecture pictures if you want to see your change visually.

## Testing strategy

Two layers of tests, both fully in-process:

**Per-changer tests** (`tests/statechangers/`): construct a changer with fakes, exercise `assess_state` and `transition`, assert on fake state (e.g. `fs.read_text(path)`) or recorded calls (e.g. `pr.calls`). The fakes are deliberately simple:

- `InMemoryFileSystem` — dict-backed, with `add_dir` / `add_file` helpers and `set_writable` / `set_readable_text` to simulate permission failures.
- `ScriptedProcessRunner` — register executables (`which` succeeds), register results by argv prefix, every `run` call records to `.calls`.
- `FailingFileSystem` / `FailingProcessRunner` — every operation raises a configured error. Useful for error-matrix tests.

**Engine-level tests** (`tests/test_dag_engine.py`): construct multiple nodes, exercise the scheduler. These use a `_ProgrammableChanger` test fixture (in the same file) rather than real changers — the goal is to test *scheduling*, not state changing. Set `max_workers=1` for determinism unless you're specifically testing parallelism.

**Don't add a test-only side door to production code** to make testing easier. If you can't test something through the public interface, the interface is probably wrong (or you need a new capability fake). The fakes give you enough lateral surface area without compromising the production API.

## Reference implementations to read

When writing similar code, read the closest existing reference first:

- `src/statectl/statechangers/new_text_file.py` — rollbackable, single capability (FileSystem), content-equivalence idempotency (compares actual file content to desired text).
- `src/statectl/statechangers/run_command.py` — non-rollbackable, two capabilities (FileSystem + ProcessRunner), sentinel-based idempotency via `creates` / `removes` paths. Demonstrates the multi-capability pattern.
- `src/statectl/interfaces/fs/` (ABC + `FileEntry` in `file_system.py`, errors in `fs_errors.py`, public surface in `__init__.py`) + `src/statectl/modules/real_file_system.py` — the full capability shape: ABC, typed error hierarchy, real impl, `_translate()` context manager that maps stdlib exceptions to typed interface errors.

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
