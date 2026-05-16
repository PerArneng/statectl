from __future__ import annotations

from statectl import NodeOutcome, StateCtl
from statectl._interfaces.registry import VariableRegistry
from statectl._modules import DefaultLogger, InMemoryVariableRegistry, RealHashing
from statectl._state_changer import (
    ExistingState,
    Result,
    StateChanger,
)
from tests._changer_fixtures import ProgrammableChanger, publish_value
from tests.fakes.scripted_clock import ScriptedClock
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_archive import ScriptedArchive
from tests.fakes.scripted_http_client import ScriptedHttpClient
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _engine(registry: VariableRegistry | None = None) -> StateCtl:
    return StateCtl(
        logger=DefaultLogger("test"),
        file_system=InMemoryFileSystem(),
        process_runner=ScriptedProcessRunner(),
        http_client=ScriptedHttpClient(),
        env=ScriptedEnv.linux(),
        archive=ScriptedArchive(),
        hashing=RealHashing(),
        clock=ScriptedClock(),
        variable_registry=registry or InMemoryVariableRegistry(),
    )


def test_diamond_publishes_and_defers_consistent_values() -> None:
    eng = _engine()
    root = ProgrammableChanger("root")
    eng.add(root, publishes=publish_value({"v": 7}))

    seen_left: list[int] = []
    seen_right: list[int] = []

    def left_factory(reg: VariableRegistry) -> StateChanger:
        seen_left.append(reg.require("v", as_type=int))
        return ProgrammableChanger("left")

    def right_factory(reg: VariableRegistry) -> StateChanger:
        seen_right.append(reg.require("v", as_type=int))
        return ProgrammableChanger("right")

    left = eng.add_deferred(left_factory, depends_on=[root])
    right = eng.add_deferred(right_factory, depends_on=[root])

    seen_sink: list[int] = []

    def sink_factory(reg: VariableRegistry) -> StateChanger:
        seen_sink.append(reg.require("v", as_type=int))
        return ProgrammableChanger("sink")

    eng.add_deferred(sink_factory, depends_on=[left, right])
    result = eng.start(max_workers=4)
    assert result.ok
    assert seen_left == [7]
    assert seen_right == [7]
    assert seen_sink == [7]


def test_fail_isolation_blocks_only_failing_chain() -> None:
    eng = _engine()
    a = ProgrammableChanger(
        "a", transition_result=Result.failure("ERR", "a-fail")
    )
    b = ProgrammableChanger("b")
    eng.add(a, publishes=publish_value({"x": 1}))
    eng.add(b, publishes=publish_value({"y": 2}))

    def c_factory(reg: VariableRegistry) -> StateChanger:
        reg.require("x", as_type=int)
        return ProgrammableChanger("c")

    eng.add_deferred(c_factory, depends_on=[a])
    d = ProgrammableChanger("d")
    eng.add(d, depends_on=[b])

    result = eng.start(max_workers=2)
    assert not result.ok
    by_name = {r.node_name: r.outcome for r in result.reports}
    assert by_name["a"] is NodeOutcome.FAILED_TRANSITION
    assert by_name["b"] is NodeOutcome.SUCCESS
    assert by_name["d"] is NodeOutcome.SUCCESS
    # c is BLOCKED, name should be its deferred placeholder
    c_outcome = next(
        v for k, v in by_name.items() if k.startswith("deferred#")
    )
    assert c_outcome is NodeOutcome.BLOCKED
    assert eng.registry().has("y")
    assert not eng.registry().has("x")


def test_idempotent_rerun_publishes_again_on_already_applied() -> None:
    """First run: SUCCESS publishes x. Second run with a separate registry:
    initial state is ALREADY_APPLIED, but publish still fires (idempotent
    rerun preserves the downstream contract)."""
    # First run.
    eng1 = _engine()
    a1 = ProgrammableChanger("a")
    eng1.add(a1, publishes=publish_value({"x": "first"}))
    r1 = eng1.start(max_workers=1)
    assert r1.ok
    assert eng1.registry().get("x") == "first"

    # Second run, fresh engine + fresh registry, but the changer reports
    # ALREADY_APPLIED (state was reached by the prior run).
    eng2 = _engine()
    a2 = ProgrammableChanger(
        "a", initial=ExistingState.ALREADY_APPLIED
    )
    eng2.add(a2, publishes=publish_value({"x": "second"}))

    def factory(reg: VariableRegistry) -> StateChanger:
        # Downstream factory only succeeds if upstream re-published x.
        assert reg.require("x", as_type=str) == "second"
        return ProgrammableChanger("b")

    eng2.add_deferred(factory, depends_on=[a2])
    r2 = eng2.start(max_workers=1)
    assert r2.ok
    by_name = {r.node_name: r.outcome for r in r2.reports}
    assert by_name["a"] is NodeOutcome.SKIPPED_ALREADY_APPLIED
    assert by_name["b"] is NodeOutcome.SUCCESS


def test_snapshot_reflects_every_successful_publish() -> None:
    eng = _engine()
    a = ProgrammableChanger("a")
    b = ProgrammableChanger("b")
    eng.add(a, publishes=publish_value({"a": 1}))
    eng.add(b, publishes=publish_value({"b": 2}))
    result = eng.start(max_workers=2)
    assert result.ok
    snap = eng.registry().snapshot()
    assert dict(snap) == {"a": 1, "b": 2}
