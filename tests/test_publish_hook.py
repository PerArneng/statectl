from __future__ import annotations

from typing import Any, Mapping

import pytest

from statectl import NodeOutcome, StateCtl
from statectl._modules import DefaultLogger, InMemoryVariableRegistry, RealHashing
from statectl._state_changer import (
    ExistingState,
    Result,
    StateChanger,
)
from tests._changer_fixtures import ProgrammableChanger, publish_value
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_http_client import ScriptedHttpClient
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _engine() -> StateCtl:
    return StateCtl(
        logger=DefaultLogger("test"),
        file_system=InMemoryFileSystem(),
        process_runner=ScriptedProcessRunner(),
        http_client=ScriptedHttpClient(),
        env=ScriptedEnv.linux(),
        hashing=RealHashing(),
        variable_registry=InMemoryVariableRegistry(),
    )


def test_publish_runs_on_success() -> None:
    eng = _engine()
    a = ProgrammableChanger("a")
    eng.add(a, publishes=publish_value({"x": 1}))
    result = eng.start(max_workers=1)
    assert result.ok
    assert eng.registry().get("x") == 1


def test_publish_runs_on_already_applied() -> None:
    eng = _engine()
    a = ProgrammableChanger("a", initial=ExistingState.ALREADY_APPLIED)
    eng.add(a, publishes=publish_value({"x": 99}))
    result = eng.start(max_workers=1)
    assert result.ok
    by_name = {r.node_name: r.outcome for r in result.reports}
    assert by_name["a"] is NodeOutcome.SKIPPED_ALREADY_APPLIED
    assert eng.registry().get("x") == 99


def test_publish_does_not_run_on_failed_invalid() -> None:
    eng = _engine()
    a = ProgrammableChanger("a", initial=ExistingState.INVALID)
    eng.add(a, publishes=publish_value({"x": 1}))
    result = eng.start(max_workers=1)
    assert not result.ok
    assert not eng.registry().has("x")


def test_publish_does_not_run_on_failed_transition() -> None:
    eng = _engine()
    a = ProgrammableChanger(
        "a", transition_result=Result.failure("BOOM", "kaboom")
    )
    eng.add(a, publishes=publish_value({"x": 1}))
    result = eng.start(max_workers=1)
    assert not result.ok
    assert not eng.registry().has("x")


def test_publish_does_not_run_on_skipped_by_transition() -> None:
    eng = _engine()
    a = ProgrammableChanger("a", transition_result=Result.skipped("noop"))
    eng.add(a, publishes=publish_value({"x": 1}))
    result = eng.start(max_workers=1)
    by_name = {r.node_name: r.outcome for r in result.reports}
    assert by_name["a"] is NodeOutcome.SKIPPED_BY_TRANSITION
    assert not eng.registry().has("x")


def test_publish_raising_marks_failed_transition_and_blocks_descendants() -> None:
    eng = _engine()
    a = ProgrammableChanger("a")
    b = ProgrammableChanger("b")

    def bad(_ch: StateChanger, _res: Result) -> Mapping[str, Any]:
        raise ValueError("boom!")

    eng.add(a, publishes=bad)
    eng.add(b, depends_on=[a])
    result = eng.start(max_workers=1)
    assert not result.ok
    by_name = {r.node_name: r.outcome for r in result.reports}
    assert by_name["a"] is NodeOutcome.FAILED_TRANSITION
    assert by_name["b"] is NodeOutcome.BLOCKED
    a_report = next(r for r in result.reports if r.node_name == "a")
    assert a_report.result is not None
    assert "PUBLISH_RAISED" in a_report.result.code
    assert "boom!" in a_report.result.message


def test_publish_duplicate_name_marks_failed_transition() -> None:
    eng = _engine()
    eng.registry().bind("x", "already-here")
    a = ProgrammableChanger("a")
    eng.add(a, publishes=publish_value({"x": 1}))
    result = eng.start(max_workers=1)
    assert not result.ok
    a_report = next(r for r in result.reports if r.node_name == "a")
    assert a_report.outcome is NodeOutcome.FAILED_TRANSITION
    assert a_report.result is not None
    assert a_report.result.code == "PUBLISH_DUPLICATE:x"


def test_publish_empty_mapping_is_noop() -> None:
    eng = _engine()
    a = ProgrammableChanger("a")
    eng.add(a, publishes=publish_value({}))
    result = eng.start(max_workers=1)
    assert result.ok
    assert dict(eng.registry().snapshot()) == {}


def test_publish_callback_receives_same_changer_instance() -> None:
    eng = _engine()
    a = ProgrammableChanger("a")
    seen: list[StateChanger] = []

    def cb(ch: StateChanger, _res: Result) -> Mapping[str, Any]:
        seen.append(ch)
        return {}

    eng.add(a, publishes=cb)
    eng.start(max_workers=1)
    assert seen == [a]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
