---
name: new-capability
description: How to add a new side-effecting capability (filesystem, network, HTTP client, process exec, clock, env, etc.) to statectl as an interface + real module + DI wiring. Use this skill whenever the user asks to add, wrap, or introduce a new capability, interface, or side-effecting dependency — or when a state changer needs to call something like `os`, `pathlib`, `socket`, `subprocess`, `requests`, `time`, etc. that isn't already behind an interface.
---

# Adding a new capability to statectl

A capability is any side-effecting concern (filesystem, network, HTTP, process exec, clock, env, …). State changers and modules must never call stdlib IO directly — every such concern is wrapped behind an ABC and injected.

The reference example is the filesystem capability:
- Interface: `statectl/interfaces/fs/file_system.py` (`FileSystem`)
- Typed errors: `statectl/interfaces/fs/error/` (`FsError` base + leaf classes)
- Real implementation: `statectl/modules/fs/real_file_system.py` (`RealFileSystem`)
- DI registration: `statectl/state_ctl_engine.py` `_Container.filesystem = providers.Singleton(RealFileSystem)`

Read those files before adding a new capability — mirror their shape.

## Steps

### 1. Define the interface

Create `statectl/interfaces/<capability>/<capability>.py` with an ABC. One class per file. Methods describe the capability in domain terms (not stdlib terms — `which` / `run`, not `subprocess_run`). Type-hint every signature.

Small sibling dataclasses or value types used by this interface (e.g. `FileEntry`, `ProcessResult`) **live in their own files** in the same directory — one class per file, snake_case filename. Don't bundle them into the interface module.

**Split methods into query vs action.** This is the load-bearing convention:

- **Query methods never raise.** They return `bool`, `Optional[T]`, or a value type. Examples: `FileSystem.exists`, `FileSystem.is_dir`, `ProcessRunner.which`. State changers' `assess_state()` calls only query methods.
- **Action methods raise typed errors on failure** that the capability cannot meaningfully express as a return value (the executable can't be found, the connection refused, the bytes can't be decoded). Examples: `FileSystem.read_text_file`, `ProcessRunner.run`.

Don't conflate "failure" with "non-success result." A 4xx HTTP response or a non-zero process exit is a *returned status* the caller owns policy over, not an exception. `RealProcessRunner.run` returns a `ProcessResult` with `exit_code=1` — it does **not** raise. Only launch-level problems (no such executable, timeout, OS-level launch failure) raise.

### 2. Define typed errors

Create `statectl/interfaces/<capability>/error/<capability>_error.py` with a base exception class. Add leaf classes (one per file) for each distinct failure mode the interface can raise — e.g. `FsNotFound`, `FsPermissionDenied`, `FsAlreadyExists`, `ProcessNotFound`, `ProcessTimeout`. Callers catch the base; the leaves carry detail.

The real implementation is responsible for translating stdlib exceptions into these typed errors so callers never see `OSError`/`FileNotFoundError`/`subprocess.TimeoutExpired`/etc.

### 3. Implement the real module

Create `statectl/modules/<capability>/real_<capability>.py` with the concrete class. It may import only from `statectl.interfaces.*` — never from another concrete module. If it needs another capability, take it as a constructor parameter typed against that interface.

Every method that implements an interface method needs `@override` (`from typing import override`) — strict pyrefly enforces it.

### 4. Register in the DI container

In `statectl/state_ctl_engine.py`, add a `providers.Singleton(<RealImpl>)` entry to `_Container`, mirroring `logger` and `filesystem`. If the implementation depends on other capabilities, pass them as provider references.

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

## Checklist

- [ ] Interface ABC under `statectl/interfaces/<capability>/`, methods in domain terms, query vs action split
- [ ] Sibling value types (`ProcessResult`-style) in their own files in the same directory
- [ ] Typed error hierarchy under `statectl/interfaces/<capability>/error/` (one class per file, base + leaves)
- [ ] Real implementation under `statectl/modules/<capability>/real_<capability>.py` translating stdlib exceptions to typed errors via a `_translate()` context manager (see `RealFileSystem`)
- [ ] `@override` on every overriding method in the real implementation
- [ ] `providers.Singleton(...)` entry in `_Container`
- [ ] Two fakes under `tests/fakes/` — rich in-memory/scripted + thin failure-injector wrapper
- [ ] No stdlib IO imports leaked into state changers or other modules
- [ ] `task check` passes (pyrefly strict, 0 errors)
