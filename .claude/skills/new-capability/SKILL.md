---
name: new-capability
description: How to add a new side-effecting capability (filesystem, network, HTTP client, process exec, clock, env, etc.) to statectl as an interface + real module + DI wiring. Use this skill whenever the user asks to add, wrap, or introduce a new capability, interface, or side-effecting dependency — or when a state changer needs to call something like `os`, `pathlib`, `socket`, `subprocess`, `requests`, `time`, etc. that isn't already behind an interface.
---

# Adding a new capability to statectl

A capability is any side-effecting concern (filesystem, network, HTTP, process exec, clock, env, …). State changers and modules must never call stdlib IO directly — every such concern is wrapped behind an ABC and injected.

The reference example is the filesystem capability:
- Interface + value object: `src/statectl/_interfaces/fs/file_system.py` (`FileSystem` ABC and the tightly-coupled `FileEntry` value object live in the same file)
- Typed errors: `src/statectl/_interfaces/fs/fs_errors.py` (`FsError` base + all variants in one file)
- Public surface: `src/statectl/_interfaces/fs/__init__.py` (re-exports the ABC, value types, and every error with `__all__`)
- Real implementation: `src/statectl/_modules/real_file_system.py` (`RealFileSystem`), re-exported from `src/statectl/_modules/__init__.py` (flat — modules do not have per-capability subpackages)
- DI registration: `src/statectl/state_ctl.py` `_Container.filesystem = providers.Singleton(RealFileSystem)`

Read those files before adding a new capability — mirror their shape.

## Steps

### 1. Define the interface

Create `src/statectl/_interfaces/<capability>/<capability>.py` with an ABC. Methods describe the capability in domain terms (not stdlib terms — `which` / `run`, not `subprocess_run`). Type-hint every signature.

Small value types tightly coupled to this ABC (e.g. `FileEntry` for `FileSystem`, `ProcessResult` for `ProcessRunner`) live **in the same file as the ABC**, not in separate files. Re-export them alongside the interface from the capability's `__init__.py`.

**Split methods into query vs action.** This is the load-bearing convention:

- **Query methods never raise.** They return `bool`, `Optional[T]`, or a value type. Examples: `FileSystem.exists`, `FileSystem.is_dir`, `ProcessRunner.which`. State changers' `assess_state()` calls only query methods.
- **Action methods raise typed errors on failure** that the capability cannot meaningfully express as a return value (the executable can't be found, the connection refused, the bytes can't be decoded). Examples: `FileSystem.read_text_file`, `ProcessRunner.run`.

**Pair raising methods with non-raising probes when assess needs them.** If a state changer's `assess_state` needs to inspect something that the capability currently only exposes via a raising action method (e.g. `FileSystem.list_files` raises, but assess needs to know "is this directory empty?"), add a non-raising sibling (`is_empty_dir(path) -> bool`) rather than letting assess catch exceptions. The non-raiser collapses every error path to a single sensible default (`False` / `None`) so callers stay branch-free. This came up adding `EnsureDirectory`: rollback assess needed an emptiness probe, so `is_empty_dir` (returns `False` on any error) was added alongside the existing raising `list_files`.

Don't conflate "failure" with "non-success result." A 4xx HTTP response or a non-zero process exit is a *returned status* the caller owns policy over, not an exception. `RealProcessRunner.run` returns a `ProcessResult` with `exit_code=1` — it does **not** raise. Only launch-level problems (no such executable, timeout, OS-level launch failure) raise.

### 2. Define typed errors

Create `src/statectl/_interfaces/<capability>/<capability>_errors.py` with the base exception class **and every variant in the same file** — e.g. `FsError` plus `FsNotFound`, `FsPermissionDenied`, `FsAlreadyExists`, …; or `ProcessError` plus `ProcessNotFound`, `ProcessTimeout`, …. Callers catch the base; the variants carry detail. Re-export every class from the capability's `__init__.py`.

The real implementation is responsible for translating stdlib exceptions into these typed errors so callers never see `OSError`/`FileNotFoundError`/`subprocess.TimeoutExpired`/etc.

### 3. Implement the real module

Create `src/statectl/_modules/real_<capability>.py` (flat — no per-capability subpackage) with the concrete class, and add a re-export to `src/statectl/_modules/__init__.py` (`from .real_<capability> import Real<Capability> as Real<Capability>` + extend `__all__`). It may import only from `statectl._interfaces.*` — never from another concrete module. If it needs another capability, take it as a constructor parameter typed against that interface.

Every method that implements an interface method needs `@override` (`from typing import override`) — strict pyrefly enforces it.

### 4. Register in the DI container

In `src/statectl/state_ctl.py`, add a `providers.Singleton(<RealImpl>)` entry to `_Container`, mirroring `logger` and `filesystem`. If the implementation depends on other capabilities, pass them as provider references.

**If state changers (or the `StateChangers` factory) need this capability at runtime**, also: (a) add it to the `StateCtl.__init__` signature and thread it from the `engine` provider, (b) add an optional override parameter to `StateCtl.new()` that calls `container.<capability>.override(providers.Object(...))` when supplied. This is the same pattern used for `file_system` and `process_runner` — it's how tests inject fakes through the engine-level entry point. Pure infra capabilities (e.g. clock used only by another module) don't need step (a)/(b) — only ones that flow into changers do.

### 5. Consume the capability

- **In a module:** declare the dependency as a constructor parameter typed against the interface; the container injects it.
- **In a state changer:** accept it as a constructor parameter with a real-implementation default, e.g.
  ```python
  def __init__(self, params: P, file_system: FileSystem | None = None) -> None:
      self._fs = file_system or RealFileSystem()
  ```
  Drivers instantiate state changers by hand, so the real default keeps production ergonomic. Tests inject fakes (see `tests/fakes/in_memory_file_system.py`, `tests/fakes/failing_file_system.py`).

State changers must not call stdlib IO directly under any circumstance.

### 6. Provide two fakes

A new capability ships with **two** test fakes, not one. The pair pattern from `tests/fakes/in_memory_file_system.py` + `tests/fakes/failing_file_system.py` (and the process equivalents `scripted_process_runner.py` + `failing_process_runner.py`) is the template:

- **Rich in-memory / scripted fake** — a full implementation of the interface backed by an in-memory data structure. Supports happy-path tests and state-driven scenarios. Examples: `InMemoryFileSystem` (path → node map), `ScriptedProcessRunner` (argv-prefix → result map, records every call for assertions).
- **Thin failure-injector wrapper** — wraps *any* implementation of the interface and lets tests register one-shot exceptions via `.fail(method, error)`. Examples: `FailingFileSystem`, `FailingProcessRunner`.

The canonical test setup composes them: `FailingFs(InMemoryFs(...))` / `FailingPr(ScriptedPr(...))`. This gives the rich state-driven base plus surgical error injection without each test having to build its own broken impl.

**When you add a method to an existing capability, update both fakes in the same change.** The failure-injector wrapper inherits from the ABC and will become abstract-incomplete the moment you add an ABC method without adding a passthrough — but pyrefly may not flag this until something actually instantiates it. The in-memory fake needs real behavior; the wrapper needs a one-line passthrough (plus a `self._maybe_fail(...)` call for action methods). Easy to forget — the test suite for the original capability won't exercise the new method.

## Checklist

- [ ] Interface ABC under `src/statectl/_interfaces/<capability>/`, methods in domain terms, query vs action split
- [ ] Tightly-coupled value types (`FileEntry`, `ProcessResult`-style) live in the **same file** as the ABC
- [ ] Typed error hierarchy in one file: `src/statectl/_interfaces/<capability>/<capability>_errors.py` (base + all variants)
- [ ] `src/statectl/_interfaces/<capability>/__init__.py` re-exports the ABC, value types, and every error with `__all__` (relative imports)
- [ ] Real implementation at `src/statectl/_modules/real_<capability>.py` (flat, no subpackage) translating stdlib exceptions to typed errors via a `_translate()` context manager (see `RealFileSystem`)
- [ ] `src/statectl/_modules/__init__.py` extended to re-export the new real impl in `__all__`
- [ ] `@override` on every overriding method in the real implementation
- [ ] `providers.Singleton(...)` entry in `_Container`
- [ ] Two fakes under `tests/fakes/` — rich in-memory/scripted + thin failure-injector wrapper
- [ ] No stdlib IO imports leaked into state changers or other modules
- [ ] `task check` passes (pyrefly strict, 0 errors)
