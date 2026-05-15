from __future__ import annotations

import threading

import pytest

from statectl import NodeOutcome, StateCtl
from statectl._engine_error import DeferredWithoutDependenciesError
from statectl._interfaces.registry import VariableRegistry
from statectl._modules import DefaultLogger, InMemoryVariableRegistry
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
from tests.fakes.scripted_clock import ScriptedClock


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


def test_factory_runs_only_after_deps_complete() -> None:
    eng = _engine()
    order: list[str] = []
    order_lock = threading.Lock()

    def record(name: str) -> None:
        with order_lock:
            order.append(name)

    a = ProgrammableChanger(
        "a", on_transition=lambda _self: record("a-run")
    )
    eng.add(a, publishes=publish_value({"a_done": True}))

    def factory(reg: VariableRegistry) -> StateChanger:
        record("factory-ran")
        assert reg.has("a_done")
        return ProgrammableChanger(
            "deferred-child",
            on_transition=lambda _self: record("child-run"),
        )

    eng.add_deferred(factory, depends_on=[a])
    result = eng.start(max_workers=1)
    assert result.ok
    assert order == ["a-run", "factory-ran", "child-run"]


def test_factory_receives_same_registry() -> None:
    eng = _engine()
    a = ProgrammableChanger("a")
    eng.add(a, publishes=publish_value({"x": 1}))
    captured: list[VariableRegistry] = []

    def factory(reg: VariableRegistry) -> StateChanger:
        captured.append(reg)
        return ProgrammableChanger("b")

    eng.add_deferred(factory, depends_on=[a])
    eng.start(max_workers=1)
    assert captured == [eng.registry()]


def test_chained_deferreds() -> None:
    eng = _engine()
    a = ProgrammableChanger("a")
    eng.add(a, publishes=publish_value({"a_v": 1}))

    def factory_b(reg: VariableRegistry) -> StateChanger:
        assert reg.require("a_v", as_type=int) == 1
        return ProgrammableChanger("b")

    b_handle = eng.add_deferred(
        factory_b, depends_on=[a], publishes=publish_value({"b_v": 2})
    )

    def factory_c(reg: VariableRegistry) -> StateChanger:
        assert reg.require("b_v", as_type=int) == 2
        return ProgrammableChanger("c")

    eng.add_deferred(factory_c, depends_on=[b_handle])
    result = eng.start(max_workers=1)
    assert result.ok
    snap = eng.registry().snapshot()
    assert snap["a_v"] == 1
    assert snap["b_v"] == 2


def test_variable_not_found_in_factory_marks_invalid() -> None:
    eng = _engine()
    a = ProgrammableChanger("a")
    eng.add(a)  # does not publish data_dir

    def factory(reg: VariableRegistry) -> StateChanger:
        reg.get("data_dir")  # missing
        return ProgrammableChanger("never")

    handle = eng.add_deferred(factory, depends_on=[a])
    follow = ProgrammableChanger("follow")
    eng.add(follow, depends_on=[handle])
    result = eng.start(max_workers=1)
    assert not result.ok
    by_name = {r.node_name: r for r in result.reports}
    deferred_report = next(
        r for n, r in by_name.items() if n.startswith("deferred#")
    )
    assert deferred_report.outcome is NodeOutcome.FAILED_INVALID
    assert deferred_report.result is not None
    assert deferred_report.result.code == "MISSING_VAR:data_dir"
    assert by_name["follow"].outcome is NodeOutcome.BLOCKED


def test_variable_type_error_in_factory_marks_invalid() -> None:
    eng = _engine()
    a = ProgrammableChanger("a")
    eng.add(a, publishes=publish_value({"v": "a-string"}))

    def factory(reg: VariableRegistry) -> StateChanger:
        reg.require("v", as_type=int)
        return ProgrammableChanger("never")

    eng.add_deferred(factory, depends_on=[a])
    result = eng.start(max_workers=1)
    assert not result.ok
    deferred = next(
        r for r in result.reports if r.node_name.startswith("deferred#")
    )
    assert deferred.outcome is NodeOutcome.FAILED_INVALID
    assert deferred.result is not None
    assert deferred.result.code == "VAR_TYPE:v"
    assert "int" in deferred.result.message
    assert "str" in deferred.result.message


def test_arbitrary_exception_in_factory_does_not_crash_engine() -> None:
    eng = _engine()
    a = ProgrammableChanger("a")
    eng.add(a)

    def factory(_reg: VariableRegistry) -> StateChanger:
        raise KeyError("nope")

    eng.add_deferred(factory, depends_on=[a])
    result = eng.start(max_workers=1)
    assert not result.ok
    deferred = next(
        r for r in result.reports if r.node_name.startswith("deferred#")
    )
    assert deferred.outcome is NodeOutcome.FAILED_INVALID
    assert deferred.result is not None
    assert "KeyError" in deferred.result.code
    assert "nope" in deferred.result.message


def test_factory_returning_none_marks_invalid() -> None:
    eng = _engine()
    a = ProgrammableChanger("a")
    eng.add(a)

    def factory(_reg: VariableRegistry) -> StateChanger:
        return None  # type: ignore[return-value]

    eng.add_deferred(factory, depends_on=[a])
    result = eng.start(max_workers=1)
    deferred = next(
        r for r in result.reports if r.node_name.startswith("deferred#")
    )
    assert deferred.outcome is NodeOutcome.FAILED_INVALID
    assert deferred.result is not None
    assert deferred.result.code == "DEFERRED_FACTORY_TYPE"
    assert "NoneType" in deferred.result.message


def test_factory_returning_non_state_changer_marks_invalid() -> None:
    eng = _engine()
    a = ProgrammableChanger("a")
    eng.add(a)

    def factory(_reg: VariableRegistry) -> StateChanger:
        return "not-a-changer"  # type: ignore[return-value]

    eng.add_deferred(factory, depends_on=[a])
    result = eng.start(max_workers=1)
    deferred = next(
        r for r in result.reports if r.node_name.startswith("deferred#")
    )
    assert deferred.outcome is NodeOutcome.FAILED_INVALID
    assert deferred.result is not None
    assert deferred.result.code == "DEFERRED_FACTORY_TYPE"
    assert "str" in deferred.result.message


def test_deferred_handle_is_valid_depends_on_target() -> None:
    eng = _engine()
    a = ProgrammableChanger("a")
    eng.add(a, publishes=publish_value({"v": 1}))
    handle = eng.add_deferred(
        lambda _reg: ProgrammableChanger("b"),
        depends_on=[a],
    )
    c = ProgrammableChanger("c")
    eng.add(c, depends_on=[handle])
    result = eng.start(max_workers=1)
    assert result.ok
    by_name = {r.node_name: r.outcome for r in result.reports}
    assert by_name["c"] is NodeOutcome.SUCCESS


def test_add_deferred_without_dependencies_raises() -> None:
    eng = _engine()
    with pytest.raises(DeferredWithoutDependenciesError):
        eng.add_deferred(
            lambda _reg: ProgrammableChanger("b"),
            depends_on=[],
        )


def test_assess_state_invalid_after_resolve_marks_invalid() -> None:
    """Defensive: if the resolved changer reports INVALID, the deferred node
    becomes FAILED_INVALID through the normal assess path."""
    eng = _engine()
    a = ProgrammableChanger("a")
    eng.add(a)

    def factory(_reg: VariableRegistry) -> StateChanger:
        return ProgrammableChanger("bad", initial=ExistingState.INVALID)

    eng.add_deferred(factory, depends_on=[a])
    result = eng.start(max_workers=1)
    deferred = next(
        r for r in result.reports if r.node_name == "bad"
    )
    assert deferred.outcome is NodeOutcome.FAILED_INVALID


def test_factory_transition_result_propagates() -> None:
    eng = _engine()
    a = ProgrammableChanger("a")
    eng.add(a)

    def factory(_reg: VariableRegistry) -> StateChanger:
        return ProgrammableChanger(
            "bad-trans",
            transition_result=Result.failure("ERR", "bad"),
        )

    eng.add_deferred(factory, depends_on=[a])
    result = eng.start(max_workers=1)
    deferred = next(r for r in result.reports if r.node_name == "bad-trans")
    assert deferred.outcome is NodeOutcome.FAILED_TRANSITION


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
