from __future__ import annotations

from typing import override

from statectl import NodeOutcome, StateCtl
from statectl._modules import DefaultLogger, InMemoryVariableRegistry
from statectl._state_changer import (
    ExistingState,
    Result,
    ResultStatus,
    RollbackableStateChanger,
    StateAssessment,
    StateChanger,
)
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_http_client import ScriptedHttpClient
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_archive import ScriptedArchive
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


class _ScriptedChanger(StateChanger):
    def __init__(
        self,
        name: str,
        assessments: list[ExistingState],
        transition_result: Result,
    ) -> None:
        self._name: str = name
        self._assessments: list[ExistingState] = list(assessments)
        self._transition_result: Result = transition_result
        self.transition_calls: int = 0
        self.assess_calls: int = 0

    @override
    def name(self) -> str:
        return self._name

    @override
    def assess_state(self) -> StateAssessment:
        self.assess_calls += 1
        if len(self._assessments) > 1:
            state = self._assessments.pop(0)
        else:
            state = self._assessments[0]
        return StateAssessment(state=state, description=f"{self._name}:{state.value}")

    @override
    def transition(self) -> Result:
        self.transition_calls += 1
        return self._transition_result


class _InverseChanger(StateChanger):
    def __init__(self, name: str, transition_result: Result) -> None:
        self._name: str = name
        self._transition_result: Result = transition_result
        self.transition_calls: int = 0

    @override
    def name(self) -> str:
        return self._name

    @override
    def assess_state(self) -> StateAssessment:
        return StateAssessment(state=ExistingState.READY, description=self._name)

    @override
    def transition(self) -> Result:
        self.transition_calls += 1
        return self._transition_result


class _ScriptedRollbackableChanger(RollbackableStateChanger):
    def __init__(
        self,
        name: str,
        assessments: list[ExistingState],
        transition_result: Result,
        rollback_result: Result,
    ) -> None:
        self._name: str = name
        self._assessments: list[ExistingState] = list(assessments)
        self._transition_result: Result = transition_result
        self._inverse: _InverseChanger = _InverseChanger(
            f"undo-{name}", rollback_result
        )
        self.transition_calls: int = 0
        self.assess_calls: int = 0
        self.rollback_calls: int = 0

    @override
    def name(self) -> str:
        return self._name

    @override
    def assess_state(self) -> StateAssessment:
        self.assess_calls += 1
        if len(self._assessments) > 1:
            state = self._assessments.pop(0)
        else:
            state = self._assessments[0]
        return StateAssessment(state=state, description=f"{self._name}:{state.value}")

    @override
    def transition(self) -> Result:
        self.transition_calls += 1
        return self._transition_result

    @override
    def rollback(self) -> StateChanger:
        self.rollback_calls += 1
        return self._inverse

    @property
    def inverse(self) -> _InverseChanger:
        return self._inverse


def _engine() -> StateCtl:
    return StateCtl(
        logger=DefaultLogger("test"),
        file_system=InMemoryFileSystem(),
        process_runner=ScriptedProcessRunner(),
        http_client=ScriptedHttpClient(),
        env=ScriptedEnv.linux(),
        archive=ScriptedArchive(),
        variable_registry=InMemoryVariableRegistry(),
    )


def test_happy_path_post_assess_already_applied() -> None:
    changer = _ScriptedChanger(
        "happy",
        assessments=[ExistingState.READY, ExistingState.ALREADY_APPLIED],
        transition_result=Result.success(message="done"),
    )
    engine = _engine()
    engine.add(changer)
    result = engine.start(max_workers=1)

    [report] = result.reports
    assert report.outcome is NodeOutcome.SUCCESS
    assert report.result is not None and report.result.status is ResultStatus.SUCCESS
    assert report.post_assess is not None
    assert report.post_assess.state is ExistingState.ALREADY_APPLIED
    assert report.rollback_result is None
    assert changer.assess_calls == 2
    assert changer.transition_calls == 1


def test_post_assess_mismatch_rollbackable_rollback_success() -> None:
    changer = _ScriptedRollbackableChanger(
        "mismatch-ok",
        assessments=[ExistingState.READY, ExistingState.READY],
        transition_result=Result.success(message="claims success"),
        rollback_result=Result.success(message="undone"),
    )
    engine = _engine()
    engine.add(changer)
    result = engine.start(max_workers=1)

    [report] = result.reports
    assert report.outcome is NodeOutcome.FAILED_TRANSITION
    assert report.result is not None
    assert report.result.code == "POST_ASSESS_MISMATCH"
    assert report.post_assess is not None
    assert report.post_assess.state is ExistingState.READY
    assert report.rollback_result is not None
    assert report.rollback_result.status is ResultStatus.SUCCESS
    assert changer.rollback_calls == 1
    assert changer.inverse.transition_calls == 1


def test_post_assess_mismatch_rollbackable_rollback_failure() -> None:
    changer = _ScriptedRollbackableChanger(
        "mismatch-rbfail",
        assessments=[ExistingState.READY, ExistingState.INVALID],
        transition_result=Result.success(message="claims success"),
        rollback_result=Result.failure(code="RB_ERR", message="rollback boom"),
    )
    engine = _engine()
    engine.add(changer)
    result = engine.start(max_workers=1)

    [report] = result.reports
    assert report.outcome is NodeOutcome.FAILED_TRANSITION
    assert report.result is not None
    assert report.result.code == "POST_ASSESS_MISMATCH"
    assert report.rollback_result is not None
    assert report.rollback_result.status is ResultStatus.FAILURE
    assert report.rollback_result.code == "RB_ERR"


def test_post_assess_mismatch_non_rollbackable() -> None:
    changer = _ScriptedChanger(
        "mismatch-plain",
        assessments=[ExistingState.READY, ExistingState.READY],
        transition_result=Result.success(message="claims success"),
    )
    engine = _engine()
    engine.add(changer)
    result = engine.start(max_workers=1)

    [report] = result.reports
    assert report.outcome is NodeOutcome.FAILED_TRANSITION
    assert report.result is not None
    assert report.result.code == "POST_ASSESS_MISMATCH"
    assert report.post_assess is not None
    assert report.rollback_result is None


def test_transition_failure_rollbackable_runs_rollback() -> None:
    failing = _ScriptedRollbackableChanger(
        "fail-rb",
        assessments=[ExistingState.READY],
        transition_result=Result.failure(code="BOOM", message="bad"),
        rollback_result=Result.success(message="cleaned up"),
    )
    downstream = _ScriptedChanger(
        "down",
        assessments=[ExistingState.READY, ExistingState.ALREADY_APPLIED],
        transition_result=Result.success(),
    )
    engine = _engine()
    engine.add(failing)
    engine.add(downstream, depends_on=[failing])
    result = engine.start(max_workers=1)

    by_name = {r.node_name: r for r in result.reports}
    fr = by_name["fail-rb"]
    assert fr.outcome is NodeOutcome.FAILED_TRANSITION
    assert fr.result is not None
    assert fr.result.code == "BOOM"
    assert fr.post_assess is None
    assert fr.rollback_result is not None
    assert fr.rollback_result.status is ResultStatus.SUCCESS
    assert by_name["down"].outcome is NodeOutcome.BLOCKED
    assert downstream.transition_calls == 0


def test_transition_failure_non_rollbackable_blocks_descendants() -> None:
    failing = _ScriptedChanger(
        "fail-plain",
        assessments=[ExistingState.READY],
        transition_result=Result.failure(code="NOPE"),
    )
    downstream = _ScriptedChanger(
        "down",
        assessments=[ExistingState.READY],
        transition_result=Result.success(),
    )
    engine = _engine()
    engine.add(failing)
    engine.add(downstream, depends_on=[failing])
    result = engine.start(max_workers=1)

    by_name = {r.node_name: r for r in result.reports}
    fr = by_name["fail-plain"]
    assert fr.outcome is NodeOutcome.FAILED_TRANSITION
    assert fr.post_assess is None
    assert fr.rollback_result is None
    assert by_name["down"].outcome is NodeOutcome.BLOCKED


def test_skipped_transition_does_not_verify_or_rollback() -> None:
    changer = _ScriptedRollbackableChanger(
        "skip",
        assessments=[ExistingState.READY],
        transition_result=Result.skipped(message="benign race"),
        rollback_result=Result.success(),
    )
    downstream = _ScriptedChanger(
        "down",
        assessments=[ExistingState.READY, ExistingState.ALREADY_APPLIED],
        transition_result=Result.success(),
    )
    engine = _engine()
    engine.add(changer)
    engine.add(downstream, depends_on=[changer])
    result = engine.start(max_workers=1)

    by_name = {r.node_name: r for r in result.reports}
    sr = by_name["skip"]
    assert sr.outcome is NodeOutcome.SKIPPED_BY_TRANSITION
    assert sr.post_assess is None
    assert sr.rollback_result is None
    assert changer.rollback_calls == 0
    assert by_name["down"].outcome is NodeOutcome.SUCCESS


def test_initial_already_applied_skips_transition_and_verification() -> None:
    changer = _ScriptedRollbackableChanger(
        "already",
        assessments=[ExistingState.ALREADY_APPLIED],
        transition_result=Result.success(),
        rollback_result=Result.success(),
    )
    engine = _engine()
    engine.add(changer)
    result = engine.start(max_workers=1)

    [report] = result.reports
    assert report.outcome is NodeOutcome.SKIPPED_ALREADY_APPLIED
    assert report.post_assess is None
    assert report.rollback_result is None
    assert changer.transition_calls == 0
    assert changer.rollback_calls == 0
