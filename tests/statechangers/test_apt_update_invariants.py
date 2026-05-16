from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from statectl._state_changer import RollbackableStateChanger, StateChanger
from statectl._statechangers import AptUpdateParameters, AptUpdateStateChanger
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_clock import ScriptedClock
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _rig() -> tuple[ScriptedProcessRunner, InMemoryFileSystem, ScriptedEnv, ScriptedClock]:
    pr = ScriptedProcessRunner()
    pr.register_executable("apt-get")
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/var/lib/apt/lists"))
    return pr, fs, ScriptedEnv.linux(), ScriptedClock()


def _build() -> AptUpdateStateChanger:
    pr, fs, env, clock = _rig()
    return AptUpdateStateChanger(
        AptUpdateParameters(),
        process_runner=pr,
        file_system=fs,
        env=env,
        clock=clock,
    )


def test_apt_update_is_a_state_changer() -> None:
    assert isinstance(_build(), StateChanger)


def test_apt_update_is_not_rollbackable() -> None:
    assert not isinstance(_build(), RollbackableStateChanger)


def test_parameters_are_frozen() -> None:
    params = AptUpdateParameters()
    with pytest.raises(Exception):
        params.max_age = timedelta(hours=1)  # type: ignore[misc]


def test_default_parameters() -> None:
    params = AptUpdateParameters()
    assert params.max_age == timedelta(hours=24)
    assert params.lists_dir == Path("/var/lib/apt/lists")
    assert params.allow_releaseinfo_change is False


def test_name_is_pure_and_includes_lists_dir() -> None:
    pr, fs, env, clock = _rig()
    changer = AptUpdateStateChanger(
        AptUpdateParameters(lists_dir=Path("/var/lib/apt/lists")),
        process_runner=pr,
        file_system=fs,
        env=env,
        clock=clock,
    )
    assert changer.name() == "apt-update:/var/lib/apt/lists"
    assert pr.calls == []


def test_assess_state_does_not_invoke_process_run() -> None:
    pr, fs, env, clock = _rig()
    changer = AptUpdateStateChanger(
        AptUpdateParameters(),
        process_runner=pr,
        file_system=fs,
        env=env,
        clock=clock,
    )
    changer.assess_state()
    changer.assess_state()
    assert pr.calls == []
