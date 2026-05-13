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

Create `statectl/interfaces/<capability>/<capability>.py` with an ABC. One class per file. Methods describe the capability in domain terms (not stdlib terms). Type-hint every signature.

Small sibling dataclasses used only by this interface (e.g. `FileEntry`) live in their own files in the same directory.

### 2. Define typed errors

Create `statectl/interfaces/<capability>/error/<capability>_error.py` with a base exception class. Add leaf classes (one per file) for each distinct failure mode the interface can raise — e.g. `FsNotFound`, `FsPermissionDenied`, `FsAlreadyExists`. Callers catch the base; the leaves carry detail.

The real implementation is responsible for translating stdlib exceptions into these typed errors so callers never see `OSError`/`FileNotFoundError`/etc.

### 3. Implement the real module

Create `statectl/modules/<capability>/real_<capability>.py` with the concrete class. It may import only from `statectl.interfaces.*` — never from another concrete module. If it needs another capability, take it as a constructor parameter typed against that interface.

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

## Checklist

- [ ] Interface ABC under `statectl/interfaces/<capability>/`
- [ ] Typed error hierarchy under `statectl/interfaces/<capability>/error/` (one class per file)
- [ ] Real implementation under `statectl/modules/<capability>/real_<capability>.py` translating stdlib exceptions to typed errors
- [ ] `providers.Singleton(...)` entry in `_Container`
- [ ] At least one fake under `tests/fakes/` so consumers can be tested without real IO
- [ ] No stdlib IO imports leaked into state changers or other modules
