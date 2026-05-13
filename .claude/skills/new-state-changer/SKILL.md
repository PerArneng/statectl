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

The canonical reference implementation is `statectl/statechangers/new_text_file.py` — read it before writing anything new. It demonstrates the full pattern (params dataclass, forward changer, rollback inverse, idempotent assessment).

## File layout

One module per changer family, placed at `statectl/statechangers/<snake_name>.py`. Put the params dataclass, the forward changer, and (if applicable) the rollback inverse in the same file — they're tightly coupled and a reader benefits from seeing them together.

`statectl/statechangers/__init__.py` stays **empty**. Consumers import via the full module path:
```python
from statectl.statechangers.your_module import YourStateChanger, YourParameters
```

## Required imports

```python
from __future__ import annotations

from dataclasses import dataclass

from statectl.state_changer import (
    ExistingState,
    Parameters,
    Result,
    RollbackableStateChanger,  # only if your changer has an inverse
    StateAssessment,
    StateChanger,
)
```

## The Parameters dataclass

Frozen (immutable), subclasses `Parameters`. Hold only the inputs the operation needs — no derived state, no handles to external resources.

```python
@dataclass(frozen=True)
class YourParameters(Parameters):
    target: SomeType
    # add fields with defaults last
```

## Choosing the base class

- **`StateChanger`** — one-shot operation, no meaningful inverse. Examples: emit a log line, fire-and-forget API call, restart a process.
- **`RollbackableStateChanger`** — the operation has a sensible inverse. Examples: create a file (inverse: delete it), install a package (inverse: uninstall), add a firewall rule (inverse: remove it).

The inverse returned by `rollback()` is itself a plain `StateChanger`. The type system intentionally prevents rollback-of-rollback — an inverse is terminal.

## The three required methods

Every changer implements:

### `name() -> str`
A human-readable identifier that appears in engine logs. Encode enough context to disambiguate instances. Pattern: `f"{kind}:{primary_param}"`, e.g. `f"new-text-file:{self._params.path}"`.

### `assess_state() -> StateAssessment`
**Read-only.** Inspect current system state and return one of three verdicts:

- `ExistingState.READY` — preconditions met, end-state not yet in place. Engine will call `transition()`.
- `ExistingState.ALREADY_APPLIED` — desired end-state is already in place. Engine will skip. This is the idempotency hook; check for *content equivalence*, not mere existence (a file that exists with the wrong content is **not** ALREADY_APPLIED, it's INVALID).
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

### `transition() -> Result`
Where the side effect lives. Return:

- `Result.success(message)` on success.
- `Result.failure(code, message)` on a real failure. `code` is a short SCREAMING_SNAKE string (`WRITE_FAILED`, `UNLINK_FAILED`, `API_4XX`); `message` is the human detail.
- `Result.skipped(message)` for benign races (e.g. the thing you were about to delete vanished between assess and transition). Engines treat SKIPPED like success — they continue.

Wrap the side-effecting call in `try/except` for the specific exceptions it can raise (`OSError`, library-specific errors). Don't catch `Exception` broadly.

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
engine = StateCtlEngine.create_engine()
engine.add(YourStateChanger(YourParameters(...)))
engine.start()
```

The engine logs each step via the injected `Logger`, halts on `INVALID` or transition `FAILURE`, and skips on `ALREADY_APPLIED`.

## Conventions worth re-stating

- Type hints on every signature and attribute.
- `from __future__ import annotations` if the file uses forward references (e.g., the forward changer referencing the rollback class defined below it).
- Constructor is `__init__(self, params: YourParameters) -> None: self._params = params`. Don't accept loose kwargs; the params dataclass *is* the API.
- Concentrate side effects in `transition()` / rollback `transition()`. `assess_state` and `name` are pure.
- Empty `__init__.py` files. Full-path imports.
- No re-exports from `statectl/__init__.py` or `statectl/statechangers/__init__.py`.

## Checklist before declaring done

- [ ] New file at `statectl/statechangers/<name>.py`.
- [ ] Frozen `Parameters` subclass with only inputs.
- [ ] Forward changer extends correct base (`StateChanger` vs `RollbackableStateChanger`).
- [ ] `name()`, `assess_state()`, `transition()` implemented; `rollback()` if applicable.
- [ ] `assess_state` collects *all* issues, distinguishes `ALREADY_APPLIED` via content/state equivalence (not just existence).
- [ ] Rollback class (if any) is plain `StateChanger`, takes same `Parameters`, has inverted assessment semantics.
- [ ] No mutation in `assess_state` or `name`.
- [ ] Smoke test: build an instance, run through `assess_state` → `transition` → re-`assess_state` (expect `ALREADY_APPLIED`); for rollbackable, also exercise `rollback()`.

## Canonical example

`statectl/statechangers/new_text_file.py` — read it. It is the worked example for every pattern above:
- `NewTextFileParameters(path, text, encoding)` — frozen dataclass.
- `NewTextFileStateChanger` — extends `RollbackableStateChanger`. Assess collects all parent-side issues (missing / not-a-dir / not-writable); detects `ALREADY_APPLIED` by reading existing content and comparing with `params.text`; treats mismatched content as `INVALID`.
- `NewTextFileRollbackStateChanger` — extends `StateChanger`. Assess returns `ALREADY_APPLIED` when the file is already gone, `INVALID` if the path turned into something unexpected, `READY` otherwise. Transition tolerates the race where the file disappears between assess and unlink (returns `SKIPPED`).

When in doubt, mirror its structure.
