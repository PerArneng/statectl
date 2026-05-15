from __future__ import annotations

from typing import Any, Mapping, override

from statectl._state_changer import (
    ExistingState,
    Result,
    StateAssessment,
    StateChanger,
)


class ProgrammableChanger(StateChanger):
    """Configurable changer for engine tests. Defaults to a happy-path
    SUCCESS run (READY -> ALREADY_APPLIED). Flip fields to model other
    paths (INVALID, transition failure, idempotent rerun, ...)."""

    def __init__(
        self,
        name: str,
        *,
        initial: ExistingState = ExistingState.READY,
        post_assess_state: ExistingState = ExistingState.ALREADY_APPLIED,
        transition_result: Result | None = None,
        on_transition: Any = None,
    ) -> None:
        self._name: str = name
        self._initial: ExistingState = initial
        self._post: ExistingState = post_assess_state
        self._transition_result: Result = transition_result or Result.success(name)
        self._on_transition: Any = on_transition
        self._has_run: bool = False
        self.transition_count: int = 0

    @override
    def name(self) -> str:
        return self._name

    @override
    def assess_state(self) -> StateAssessment:
        state = self._post if self._has_run else self._initial
        return StateAssessment(state=state, description=self._name)

    @override
    def transition(self) -> Result:
        self.transition_count += 1
        self._has_run = True
        if self._on_transition is not None:
            self._on_transition(self)
        return self._transition_result


def publish_value(values: Mapping[str, Any]):
    def cb(_ch: StateChanger, _res: Result) -> Mapping[str, Any]:
        return values

    return cb
