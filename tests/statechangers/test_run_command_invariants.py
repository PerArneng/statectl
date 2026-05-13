from __future__ import annotations

from pathlib import Path

import pytest

from statectl.state_changer import RollbackableStateChanger, StateChanger
from statectl.statechangers.run_command import (
    RunCommandParameters,
    RunCommandStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _rig() -> tuple[ScriptedProcessRunner, InMemoryFileSystem]:
    pr = ScriptedProcessRunner()
    pr.register_executable("echo")
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    return pr, fs


def test_run_command_is_a_state_changer() -> None:
    pr, fs = _rig()
    changer = RunCommandStateChanger(
        RunCommandParameters(argv=("echo", "hi")),
        process_runner=pr,
        file_system=fs,
    )

    assert isinstance(changer, StateChanger)


def test_run_command_is_not_rollbackable() -> None:
    """Documents the design decision: arbitrary commands have no inverse."""
    pr, fs = _rig()
    changer = RunCommandStateChanger(
        RunCommandParameters(argv=("echo", "hi")),
        process_runner=pr,
        file_system=fs,
    )

    assert not isinstance(changer, RollbackableStateChanger)


def test_parameters_are_frozen() -> None:
    params = RunCommandParameters(argv=("echo",))

    with pytest.raises(Exception):
        params.argv = ("ls",)  # type: ignore[misc]


def test_name_is_pure() -> None:
    pr, fs = _rig()
    changer = RunCommandStateChanger(
        RunCommandParameters(argv=("echo", "hi")),
        process_runner=pr,
        file_system=fs,
    )

    n1 = changer.name()
    n2 = changer.name()

    assert n1 == n2 == "run-command:echo"
    assert pr.calls == []


def test_name_handles_empty_argv_without_indexing_error() -> None:
    pr, fs = _rig()
    changer = RunCommandStateChanger(
        RunCommandParameters(argv=()),
        process_runner=pr,
        file_system=fs,
    )

    assert changer.name() == "run-command:<empty>"


def test_assess_state_does_not_invoke_process_run() -> None:
    pr, fs = _rig()
    changer = RunCommandStateChanger(
        RunCommandParameters(argv=("echo", "hi")),
        process_runner=pr,
        file_system=fs,
    )

    changer.assess_state()
    changer.assess_state()

    assert pr.calls == []


def test_assess_state_does_not_mutate_filesystem() -> None:
    pr, fs = _rig()
    changer = RunCommandStateChanger(
        RunCommandParameters(argv=("echo",), creates=Path("/work/marker")),
        process_runner=pr,
        file_system=fs,
    )

    snapshot_before = set(fs._nodes.keys())  # noqa: SLF001 (test boundary)
    changer.assess_state()
    snapshot_after = set(fs._nodes.keys())  # noqa: SLF001

    assert snapshot_before == snapshot_after
