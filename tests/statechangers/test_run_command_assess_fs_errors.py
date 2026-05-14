from __future__ import annotations

from pathlib import Path

from statectl._interfaces.fs import FsIoError
from statectl._state_changer import ExistingState
from statectl._statechangers import (
    RunCommandParameters,
    RunCommandStateChanger,
)
from tests.fakes.failing_file_system import FailingFileSystem
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _ready_pr() -> ScriptedProcessRunner:
    pr = ScriptedProcessRunner()
    pr.register_executable("echo")
    return pr


def test_assess_uses_only_non_raising_query_methods_on_fs() -> None:
    """assess_state() must call only FileSystem query methods (which never
    raise per the FS contract). Configure FailingFileSystem to raise on
    raising mutating methods — assess_state must not trigger them.
    """
    inner = InMemoryFileSystem()
    inner.add_dir(Path("/work"))
    fs = FailingFileSystem(inner)
    fs.fail("read_text_file", FsIoError("boom"))
    fs.fail("write_text_file", FsIoError("boom"))
    fs.fail("delete_file", FsIoError("boom"))

    changer = RunCommandStateChanger(
        RunCommandParameters(
            argv=("echo",),
            cwd=Path("/work"),
            creates=Path("/work/marker"),
            removes=Path("/work/sentinel"),
        ),
        process_runner=_ready_pr(),
        file_system=fs,
    )

    # Should not raise — only query methods (`exists`, `is_dir`) are used.
    assessment = changer.assess_state()
    assert assessment.state in (
        ExistingState.READY,
        ExistingState.ALREADY_APPLIED,
        ExistingState.INVALID,
    )


def test_creates_path_present_yields_already_applied_via_exists_query() -> None:
    pr = _ready_pr()
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/out"), content="")

    changer = RunCommandStateChanger(
        RunCommandParameters(argv=("echo",), creates=Path("/work/out")),
        process_runner=pr,
        file_system=fs,
    )

    assert changer.assess_state().state is ExistingState.ALREADY_APPLIED


def test_creates_path_is_a_directory_still_counts_as_satisfied() -> None:
    """Ansible's `creates:` is existence-based, not file-type-based. A
    directory at the path also satisfies it. Locks in the documented
    behavior.
    """
    pr = _ready_pr()
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(Path("/work/out"))

    changer = RunCommandStateChanger(
        RunCommandParameters(argv=("echo",), creates=Path("/work/out")),
        process_runner=pr,
        file_system=fs,
    )

    assert changer.assess_state().state is ExistingState.ALREADY_APPLIED


def test_cwd_validation_distinguishes_missing_from_not_a_dir() -> None:
    pr = _ready_pr()
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/file"), content="")

    missing = RunCommandStateChanger(
        RunCommandParameters(argv=("echo",), cwd=Path("/nope")),
        process_runner=pr,
        file_system=fs,
    ).assess_state()
    not_a_dir = RunCommandStateChanger(
        RunCommandParameters(argv=("echo",), cwd=Path("/work/file")),
        process_runner=pr,
        file_system=fs,
    ).assess_state()

    assert any("does not exist" in i for i in missing.issues)
    assert any("not a directory" in i for i in not_a_dir.issues)
