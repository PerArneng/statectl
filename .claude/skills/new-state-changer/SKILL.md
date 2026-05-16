---
name: new-state-changer
description: How to add a new StateChanger to the statectl project. Use this skill whenever the user asks to create, add, or implement a new state changer, a new RollbackableStateChanger, or any new declarative operation in statectl (creating files, installing packages, configuring services, mutating system state, etc.). Also use proactively when the user describes an OS/infra operation they want wrapped into the statectl framework, even if they don't use the literal phrase "state changer".
---

# Adding a new StateChanger to statectl

## What this skill is for

`statectl` models any reversible-or-one-shot system change as a `StateChanger` that the engine drives. To add a new one, you produce:

1. A frozen `Parameters` dataclass describing the inputs.
2. A `StateChanger` (or `RollbackableStateChanger`) class bound to those parameters.
3. If rollbackable, an inverse plain `StateChanger` that undoes the transition.

The canonical reference implementation is `src/statectl/_statechangers/fs/new_text_file.py` — read it before writing anything new. It demonstrates the full pattern (params dataclass, forward changer, rollback inverse, idempotent assessment).

## File layout

One module per changer family, placed under the target-subsystem subpackage at `src/statectl/_statechangers/<group>/<snake_name>.py`. Put the params dataclass, the forward changer, and (if applicable) the rollback inverse in the same file — they're tightly coupled and a reader benefits from seeing them together.

Pick `<group>` by what the changer targets:

| Target subsystem | Subpackage |
|---|---|
| Portable filesystem (files, dirs, symlinks, modes, in-file edits) | `fs/` |
| Portable network (HTTP fetch/download) | `net/` |
| Archive extraction (tar/zip) | `archive/` |
| Process execution (generic `run_command`-style) | `process/` |
| Git operations | `git/` |
| Cross-Unix user/group/shell management | `posix/` |
| Debian/Ubuntu (`apt`) | `apt/` |
| Homebrew (macOS + Linux) | `brew/` |
| Linux init (`systemd`) | `systemd/` |
| macOS init (`launchd`) | `launchd/` |
| Cross-platform init façade | `service/` |

If none fit, create a new subpackage (empty `__init__.py`) — don't drop files at the `_statechangers/` root.

Re-export the new changer (and its `Parameters`) from `src/statectl/_statechangers/__init__.py` using a relative import of the form `from .<group>.<file> import …`, and add the names to `__all__`. The flat surface is preserved — consumers still import from the package:
```python
from statectl._statechangers import YourStateChanger, YourParameters
```

## Required imports

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import override

from statectl._state_changer import (
    ExistingState,
    Parameters,
    Result,
    ResultStatus,                # only if you build Result() directly (see below)
    RollbackableStateChanger,    # only if your changer has an inverse
    StateAssessment,
    StateChanger,
)
from statectl._interfaces.fs import FileSystem, FsError, FsNotFound  # capability + typed errors
from statectl._modules import RealFileSystem                          # default for `None` capability kwarg
```

Top-level types (`StateChanger`, `Parameters`, …) come from `statectl._state_changer` (file path) — these are no longer re-exported from the public `statectl` package surface, so internal modules and tests must import them from the underscore-prefixed path. Capability ABCs and errors come from their interface package surface (`statectl._interfaces.<cap>`); real impls come from `statectl._modules` (flat — no per-capability subpackage).

`@override` is required on every overriding method (`name`, `assess_state`, `transition`, `rollback`) under the project's strict pyrefly preset.

## The Parameters dataclass

Frozen (immutable), subclasses `Parameters`. Hold only the inputs the operation needs — no derived state, no handles to external resources.

```python
@dataclass(frozen=True)
class YourParameters(Parameters):
    target: SomeType
    # add fields with defaults last
```

### Parameters must be self-sufficient for `assess_state`

This is the most easily-missed property of a well-designed `Parameters`. The rule:

> **`Parameters` must encode every choice `transition` will make** — not just the desired end state, but also the placement / identity / disambiguation rules that locate where the change applies. And `assess_state` must verify every assumption `transition` will rely on — including the ambiguity cases (zero matches, multiple matches, anchor missing).

Why this matters: the engine assesses **once** and acts **once** based on that assessment. If `transition` has to guess at runtime (pick "the right" regex match, default to the end of the file when an anchor is ambiguous, choose a port when one isn't specified), then the post-state isn't determined by the inputs and the changer is no longer idempotent — re-running can land in a different state than the first run, and `ALREADY_APPLIED` detection becomes unreliable.

Practical test: read the Parameters dataclass alone. Can a reader predict the final byte-for-byte state of the affected resource? If "it depends on what's there" applies to anything besides whether the changer needs to run at all, the parameters are underspecified.

**Worked example — `EnsureLineInFile`.** Naïve params look like `(path, line)`. That's underspecified: where does the line go? At the end? After a specific section? The fix is to make placement part of the contract:

```python
@dataclass(frozen=True)
class AfterRegex:
    pattern: str          # must match exactly one line

@dataclass(frozen=True)
class BeforeRegex:
    pattern: str

@dataclass(frozen=True)
class AtEnd: ...

@dataclass(frozen=True)
class AtStart: ...

Placement = AfterRegex | BeforeRegex | AtEnd | AtStart

@dataclass(frozen=True)
class EnsureLineInFileParameters(Parameters):
    path: Path
    line: str
    placement: Placement
    strict_anchor: bool = True   # if False, "line already present elsewhere" → ALREADY_APPLIED
```

`assess_state` then collects (as one pass, per the standard rule):

- `path` doesn't exist / isn't a file / isn't writable → INVALID
- placement is `AfterRegex(p)` and `p` matches **0** lines → INVALID ("anchor not found")
- placement is `AfterRegex(p)` and `p` matches **>1** lines → INVALID ("anchor is ambiguous, matches N lines")
- the line is already present at the exact insertion point implied by `placement` → ALREADY_APPLIED
- the line is present in the file but not at the anchor:
  - if `strict_anchor=True` → INVALID ("line exists at wrong location: line N")
  - if `strict_anchor=False` → ALREADY_APPLIED
- otherwise → READY

Notice how every disambiguation that `transition` would otherwise face has been pushed up into either the Parameters (the `placement` choice, the `strict_anchor` toggle) or the assessment (the multi-match / zero-match INVALID branches). `transition` itself becomes mechanical: re-read the file, locate the single anchor (or end/start), splice the line, write back.

**Smell list — signs your Parameters are underspecified:**

- `transition` contains "if X then Y else Z" branches that depend on *current state* in a way that changes the resulting state (not just whether to act).
- A second run after a successful first run can produce a different end state.
- `assess_state` can't enumerate every INVALID case because some are only discoverable at apply time.
- Two reasonable people would write different `transition` code for the same `Parameters` because something was left to interpretation.

When in doubt, prefer **more explicit Parameters** over a clever changer. A `Placement` ADT or a `match_strategy: Literal["unique", "first", "last"]` field is cheaper than debugging a non-idempotent changer in production.

## Choosing the base class

- **`StateChanger`** — one-shot operation, no meaningful inverse. Examples: emit a log line, fire-and-forget API call, restart a process, run an arbitrary command.
- **`RollbackableStateChanger`** — the operation has a sensible inverse. Examples: create a file (inverse: delete it), install a package (inverse: uninstall), add a firewall rule (inverse: remove it).

If the inverse is unclear, ambiguous, or unsafe (e.g. arbitrary shell commands, HTTP POSTs whose effect is server-defined), prefer plain `StateChanger`. Drivers can queue an explicit cleanup changer instead of pretending an inverse exists.

The inverse returned by `rollback()` is itself a plain `StateChanger`. The type system intentionally prevents rollback-of-rollback — an inverse is terminal.

## Constructor: capabilities go in, params is the API

```python
def __init__(
    self,
    params: YourParameters,
    file_system: FileSystem | None = None,
    process_runner: ProcessRunner | None = None,
) -> None:
    self._params = params
    self._fs: FileSystem = file_system or RealFileSystem()
    self._pr: ProcessRunner = process_runner or RealProcessRunner()
```

Take each injected capability as its own keyword param with a real-implementation default. This keeps driver code ergonomic (no DI required to instantiate by hand) while letting tests inject fakes. Order is convention, not contract; pick one and be consistent across the file. The `Parameters` dataclass is still the public API — don't accept loose kwargs.

## The three required methods

Every changer implements:

### `name() -> str`
A human-readable identifier that appears in engine logs. Encode enough context to disambiguate instances. Pattern: `f"{kind}:{primary_param}"`, e.g. `f"new-text-file:{self._params.path}"`.

### `assess_state() -> StateAssessment`
**Read-only, and uses only non-raising capability methods.** "Read-only" is the necessary condition; the stronger rule is that `assess_state` calls only query methods that can't raise (e.g. `FileSystem.exists`, `ProcessRunner.which`). An exception escaping from assess masquerades as a crash, not an INVALID verdict — keep raising methods (`read_text_file`, `run`) inside `transition()` only.

Return one of three verdicts:

- `ExistingState.READY` — preconditions met, end-state not yet in place. Engine will call `transition()`.
- `ExistingState.ALREADY_APPLIED` — desired end-state is already in place. Engine will skip. This is the idempotency hook. Two valid detection strategies:
  - **Content equivalence** — read current state and compare to params (a file that exists with the wrong content is **not** ALREADY_APPLIED, it's INVALID). Best when the operation's end-state is directly inspectable.
  - **Sentinel-based (Ansible-style `creates` / `removes`)** — a path or marker indicates the operation already ran. Best for operations whose effect is hard or impossible to inspect (running a command, calling an API, building an artifact). See `RunCommandStateChanger` for the canonical example.
- `ExistingState.INVALID` — cannot safely proceed. Populate `issues: list[str]` with one human-readable string per problem.

**Collect all issues in one pass.** Drivers and humans benefit from seeing the full picture in one shot, not playing whack-a-mole as they fix one problem at a time. Append to a local `issues: list[str]` and check it at the end:

```python
def assess_state(self) -> StateAssessment:
    issues: list[str] = []
    if not precondition_a():
        issues.append("a is missing: ...")
    if not precondition_b():
        issues.append("b is wrong: ...")
    if issues:
        return StateAssessment(state=ExistingState.INVALID, description="cannot apply X", issues=issues)
    if already_applied():
        return StateAssessment(state=ExistingState.ALREADY_APPLIED, description="X already in place")
    return StateAssessment(state=ExistingState.READY, description="ready to apply X")
```

`assess_state` must not mutate anything. If you need a probe that has side effects, that's a code smell — find a read-only check or push the side effect into `transition()`.

**Only check preconditions on branches `transition` will actually exercise.** If a precondition is only relevant when the changer needs to take a specific action, gate the check on that action being needed. Example: `EnsureDirectory` only needs the parent directory writable when it has to *create* the target; if the target already exists and the changer is just adjusting mode (or is ALREADY_APPLIED), parent writability is irrelevant and reporting it as an INVALID issue is a false positive. The pattern: compute `path_exists`/`path_state` first, then `if not path_exists: check_parent_writability()`. Over-checking yields confusing diagnostics for cases that would actually succeed.

### `transition() -> Result`
Where the side effect lives. Return:

- `Result.success(message)` on success.
- `Result.failure(code, message)` on a real failure. `code` is a short SCREAMING_SNAKE string (`WRITE_FAILED`, `UNLINK_FAILED`, `API_4XX`); `message` is the human detail.
- `Result.skipped(message)` for benign races (e.g. the thing you were about to delete vanished between assess and transition). Engines treat SKIPPED like success — they continue.

Wrap the side-effecting call in `try/except` for the specific exceptions it can raise (`OSError`, library-specific errors, typed capability errors like `FsError` / `ProcessError`). Don't catch `Exception` broadly — letting unexpected exceptions propagate surfaces real bugs instead of masking them as transition failures.

#### Attaching `details` to a Result

`Result.success(...)` / `Result.failure(...)` factories don't take a `details` dict. When you need to attach structured information (exit codes, byte counts, durations, truncated stdout/stderr), construct `Result(...)` directly:

```python
return Result(
    status=ResultStatus.SUCCESS,
    code="OK",
    message=f"command exited {exit_code}",
    details={
        "exit_code": str(exit_code),
        "stdout": _truncate(stdout),
        "duration_ms": str(duration_ms),
    },
)
```

`details` values are `str`-typed by contract — stringify integers and other scalars at the boundary.

#### Bound any unbounded fields

If a `details` value can be arbitrarily large (process stdout, file diff, HTTP body), truncate before attaching. `Result` objects end up in logs and may be passed around — a 100MB stdout in `details` is a bug waiting to happen. Define a small constant and helper at the top of the file:

```python
_OUTPUT_CAP = 4096

def _truncate(text: str) -> str:
    if len(text) <= _OUTPUT_CAP:
        return text
    return text[:_OUTPUT_CAP] + f"...[truncated, total {len(text)} chars]"
```

## Rollback (RollbackableStateChanger only)

The forward class implements `rollback() -> StateChanger` and returns an instance of the inverse class, **constructed with the same `Parameters`**:

```python
def rollback(self) -> StateChanger:
    return YourRollbackStateChanger(self._params)
```

The inverse class:
- Inherits from `StateChanger` (not `RollbackableStateChanger`).
- Takes the same `Parameters` type.
- `name()`: prefix with `rollback-` or suffix with `-rollback` so logs make the direction obvious.
- `assess_state()`: typically inverted. If the forward op returns `ALREADY_APPLIED` when the file exists with matching content, the rollback returns `ALREADY_APPLIED` when the file is *absent* (nothing to undo). `READY` when there's work to do. `INVALID` when state is inconsistent with what we expected to roll back (e.g. path is a directory, not the file we wrote).
- `transition()`: applies the inverse side effect.

## Engine integration

You don't have to wire anything new — drivers consume your changer like any other:

```python
ctl = StateCtl.new()
ctl.add(YourStateChanger(YourParameters(...)))
ctl.start()
```

The engine logs each step via the injected `Logger`, halts on `INVALID` or transition `FAILURE`, and skips on `ALREADY_APPLIED`.

### Optional: surface it through the `StateChangers` factory

If your changer is a candidate for the ergonomic built-in surface, add a method to `src/statectl/_statechangers/state_changers.py` that flattens its `Parameters` into keyword args, coerces `str | Path` etc. at the boundary, and threads `self._fs` / `self._pr` to the constructor. This is optional — custom / project-specific changers can stay outside the factory and be constructed directly as shown above.

## Tests are part of the deliverable

A state changer ships with its test suite. The reference is `tests/statechangers/test_new_text_file_*.py` (and `test_run_command_*.py` for a two-capability changer). Split tests by concern, one file per concern — the existing files are the size benchmark (~50–150 lines each). The recommended split:

- `test_<name>_invariants.py` — type-contract checks (right base class, frozen `Parameters`, `name()` and `assess_state()` are pure / don't invoke action methods on capabilities)
- `test_<name>_assess_invalid.py` — every INVALID branch plus a multi-issue case asserting all issues appear at once
- `test_<name>_assess_ready_and_applied.py` — the idempotency truth table (parametrized)
- `test_<name>_assess_fs_errors.py` / `_capability_errors.py` — sentinel test that `assess_state` doesn't call any raising capability methods (configure a failing fake to raise on action methods; assess must still not raise)
- `test_<name>_transition_success.py` — happy path, including that `details` carry the expected fields and that capability fakes recorded exactly the expected calls
- `test_<name>_transition_<failure-mode>.py` — one file per failure axis (e.g. unexpected exit, error matrix)
- `test_<name>_transition_error_matrix.py` — parametrize over every typed-error subclass the capability raises; assert each maps to a specific failure `code`; include a negative test that a non-typed exception (`RuntimeError`) propagates
- `test_<name>_end_to_end_through_engine.py` — integration: queue the changer in a real `StateCtl` with fakes injected; assert engine behavior (skip on ALREADY_APPLIED, halt on FAILURE, halt on INVALID). The engine reports outcomes via `NodeOutcome` — the members are **`SUCCESS`, `SKIPPED_ALREADY_APPLIED`, `SKIPPED_BY_TRANSITION`, `FAILED_INVALID`, `FAILED_TRANSITION`, `BLOCKED`** (not the natural-guess names `SKIPPED` / `INVALID`). Match those exactly.

Tests must use only fakes — no real disk, no real subprocess, no real network. If a fake doesn't exist for a capability you need, see the `new-capability` skill.

## Conventions worth re-stating

- Type hints on every signature and attribute.
- `from __future__ import annotations` if the file uses forward references (e.g., the forward changer referencing the rollback class defined below it).
- `@override` on every overriding method — strict pyrefly enforces it.
- Constructor takes `params: YourParameters` plus one keyword param per injected capability, each defaulting to its real impl. Don't accept loose kwargs; the params dataclass *is* the public API.
- Concentrate side effects in `transition()` / rollback `transition()`. `assess_state` and `name` are pure.
- Re-export the new changer + its `Parameters` from `src/statectl/_statechangers/__init__.py` using `from .<group>.<file> import …` + `__all__`.
- Inside the changer file, import capability ABCs/errors/real impls from the package surface (`from statectl._interfaces.fs import ...`); import top-level types from their file path (`from statectl._state_changer import StateChanger`).

## Checklist before declaring done

- [ ] New file at `src/statectl/_statechangers/<group>/<name>.py`, re-exported from `src/statectl/_statechangers/__init__.py` with `__all__`.
- [ ] Frozen `Parameters` subclass with only inputs.
- [ ] Forward changer extends correct base (`StateChanger` vs `RollbackableStateChanger`).
- [ ] `@override` decorator on every overriding method.
- [ ] Constructor takes `params` plus each injected capability as its own keyword param with a real-impl default.
- [ ] `name()`, `assess_state()`, `transition()` implemented; `rollback()` if applicable.
- [ ] `assess_state` collects *all* issues, uses only non-raising capability methods, distinguishes `ALREADY_APPLIED` via content-equivalence OR sentinel (`creates`/`removes`) — not via "did we run it".
- [ ] `transition` catches narrow typed exceptions per failure mode, maps each to a specific SCREAMING_SNAKE failure `code`, lets unexpected exceptions propagate.
- [ ] If `details` carry unbounded fields, they are truncated.
- [ ] Rollback class (if any) is plain `StateChanger`, takes same `Parameters`, has inverted assessment semantics.
- [ ] No mutation in `assess_state` or `name`.
- [ ] Test suite split by concern (see "Tests are part of the deliverable"); uses fakes only.
- [ ] Smoke test: build an instance, run through `assess_state` → `transition` → re-`assess_state` (expect `ALREADY_APPLIED`); for rollbackable, also exercise `rollback()`.
- [ ] `task check` passes (pyrefly strict, 0 errors).

## Canonical example

`src/statectl/_statechangers/fs/new_text_file.py` — read it. It is the worked example for every pattern above:
- `NewTextFileParameters(path, text, encoding)` — frozen dataclass.
- `NewTextFileStateChanger` — extends `RollbackableStateChanger`. Assess collects all parent-side issues (missing / not-a-dir / not-writable); detects `ALREADY_APPLIED` by reading existing content and comparing with `params.text`; treats mismatched content as `INVALID`.
- `NewTextFileRollbackStateChanger` — extends `StateChanger`. Assess returns `ALREADY_APPLIED` when the file is already gone, `INVALID` if the path turned into something unexpected, `READY` otherwise. Transition tolerates the race where the file disappears between assess and unlink (returns `SKIPPED`).

When in doubt, mirror its structure.
