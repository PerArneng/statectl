from __future__ import annotations

import threading
import time
from typing import override

import pytest

from statectl import NodeOutcome, StateCtl
from statectl._engine_error import DuplicateNodeError, UnknownDependencyError
from statectl._modules import DefaultLogger, InMemoryVariableRegistry
from statectl._state_changer import (
    ExistingState,
    Result,
    StateAssessment,
    StateChanger,
)
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_http_client import ScriptedHttpClient
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_process_runner import ScriptedProcessRunner
from tests.fakes.scripted_clock import ScriptedClock


class _ProgrammableChanger(StateChanger):
    """In-memory changer for DAG tests. Records when `transition` runs and can
    be configured to return any combination of assessment + transition."""

    def __init__(
        self,
        name: str,
        recorder: list[str],
        state: ExistingState = ExistingState.READY,
        succeed: bool = True,
        sleep_s: float = 0.0,
        record_span: list[tuple[str, float, float]] | None = None,
        span_lock: threading.Lock | None = None,
    ) -> None:
        self._name: str = name
        self._recorder: list[str] = recorder
        self._state: ExistingState = state
        self._succeed: bool = succeed
        self._sleep_s: float = sleep_s
        self._record_span: list[tuple[str, float, float]] | None = record_span
        self._span_lock: threading.Lock | None = span_lock

    @override
    def name(self) -> str:
        return self._name

    @override
    def assess_state(self) -> StateAssessment:
        return StateAssessment(state=self._state, description=self._name)

    @override
    def transition(self) -> Result:
        start = time.monotonic()
        if self._sleep_s:
            time.sleep(self._sleep_s)
        end = time.monotonic()
        self._recorder.append(self._name)
        if self._record_span is not None and self._span_lock is not None:
            with self._span_lock:
                self._record_span.append((self._name, start, end))
        if self._succeed:
            self._state = ExistingState.ALREADY_APPLIED
            return Result.success(message=self._name)
        return Result.failure(code="ERR", message=f"{self._name} failed")


def _engine() -> StateCtl:
    return StateCtl(
        logger=DefaultLogger("test"),
        file_system=InMemoryFileSystem(),
        process_runner=ScriptedProcessRunner(),
        http_client=ScriptedHttpClient(),
        env=ScriptedEnv.linux(),
        clock=ScriptedClock(),
        variable_registry=InMemoryVariableRegistry(),
    )


def test_unknown_dependency_raises_at_add_time() -> None:
    recorder: list[str] = []
    a = _ProgrammableChanger("a", recorder)
    b = _ProgrammableChanger("b", recorder)

    engine = _engine()
    with pytest.raises(UnknownDependencyError):
        engine.add(b, depends_on=[a])  # 'a' not added yet


def test_duplicate_changer_raises() -> None:
    recorder: list[str] = []
    a = _ProgrammableChanger("a", recorder)

    engine = _engine()
    engine.add(a)
    with pytest.raises(DuplicateNodeError):
        engine.add(a)


def test_independent_roots_all_run() -> None:
    recorder: list[str] = []
    changers = [_ProgrammableChanger(name, recorder) for name in ("a", "b", "c")]
    engine = _engine()
    for c in changers:
        engine.add(c)

    result = engine.start(max_workers=1)
    assert result.ok
    assert sorted(recorder) == ["a", "b", "c"]
    assert {r.outcome for r in result.reports} == {NodeOutcome.SUCCESS}


def test_linear_chain_runs_in_topological_order() -> None:
    recorder: list[str] = []
    a = _ProgrammableChanger("a", recorder)
    b = _ProgrammableChanger("b", recorder)
    c = _ProgrammableChanger("c", recorder)

    engine = _engine()
    engine.add(a)
    engine.add(b, depends_on=[a])
    engine.add(c, depends_on=[b])
    result = engine.start(max_workers=1)

    assert result.ok
    assert recorder == ["a", "b", "c"]


def test_diamond_runs_all_with_join_last() -> None:
    recorder: list[str] = []
    a = _ProgrammableChanger("a", recorder)
    b = _ProgrammableChanger("b", recorder)
    c = _ProgrammableChanger("c", recorder)
    d = _ProgrammableChanger("d", recorder)

    engine = _engine()
    engine.add(a)
    engine.add(b, depends_on=[a])
    engine.add(c, depends_on=[a])
    engine.add(d, depends_on=[b, c])

    result = engine.start(max_workers=1)
    assert result.ok
    assert recorder[0] == "a"
    assert recorder[-1] == "d"
    assert set(recorder) == {"a", "b", "c", "d"}


def test_failure_isolates_descendants_but_lets_siblings_run() -> None:
    recorder: list[str] = []
    a = _ProgrammableChanger("a", recorder, succeed=False)
    b = _ProgrammableChanger("b", recorder)
    c = _ProgrammableChanger("c", recorder)
    sib = _ProgrammableChanger("sib", recorder)

    engine = _engine()
    engine.add(a)
    engine.add(b, depends_on=[a])
    engine.add(c, depends_on=[b])
    engine.add(sib)

    result = engine.start(max_workers=1)
    assert not result.ok
    assert "a" in recorder and "sib" in recorder
    assert "b" not in recorder and "c" not in recorder

    by_name = {r.node_name: r.outcome for r in result.reports}
    assert by_name["a"] is NodeOutcome.FAILED_TRANSITION
    assert by_name["b"] is NodeOutcome.BLOCKED
    assert by_name["c"] is NodeOutcome.BLOCKED
    assert by_name["sib"] is NodeOutcome.SUCCESS


def test_invalid_assessment_blocks_descendants_only() -> None:
    recorder: list[str] = []
    a = _ProgrammableChanger("a", recorder, state=ExistingState.INVALID)
    b = _ProgrammableChanger("b", recorder)
    sib = _ProgrammableChanger("sib", recorder)

    engine = _engine()
    engine.add(a)
    engine.add(b, depends_on=[a])
    engine.add(sib)

    result = engine.start(max_workers=1)
    by_name = {r.node_name: r.outcome for r in result.reports}
    assert by_name["a"] is NodeOutcome.FAILED_INVALID
    assert by_name["b"] is NodeOutcome.BLOCKED
    assert by_name["sib"] is NodeOutcome.SUCCESS
    assert "a" not in recorder  # transition not called for INVALID


def test_already_applied_propagates_as_success() -> None:
    recorder: list[str] = []
    a = _ProgrammableChanger("a", recorder, state=ExistingState.ALREADY_APPLIED)
    b = _ProgrammableChanger("b", recorder)

    engine = _engine()
    engine.add(a)
    engine.add(b, depends_on=[a])

    result = engine.start(max_workers=1)
    assert result.ok
    by_name = {r.node_name: r.outcome for r in result.reports}
    assert by_name["a"] is NodeOutcome.SKIPPED_ALREADY_APPLIED
    assert by_name["b"] is NodeOutcome.SUCCESS
    assert recorder == ["b"]  # 'a' never ran transition


def test_real_parallelism_overlaps_root_nodes() -> None:
    recorder: list[str] = []
    spans: list[tuple[str, float, float]] = []
    lock = threading.Lock()

    def make(name: str) -> _ProgrammableChanger:
        return _ProgrammableChanger(
            name,
            recorder,
            sleep_s=0.1,
            record_span=spans,
            span_lock=lock,
        )

    engine = _engine()
    for c in (make("a"), make("b"), make("c")):
        engine.add(c)

    t0 = time.monotonic()
    result = engine.start(max_workers=3)
    elapsed = time.monotonic() - t0

    assert result.ok
    assert len(spans) == 3
    # Three 100ms sleeps in parallel should finish well under the sequential 300ms.
    assert elapsed < 0.25
