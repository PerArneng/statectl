from __future__ import annotations

from pathlib import Path

from statectl._state_changer import ResultStatus
from statectl._statechangers import (
    SetFileModeParameters,
    SetFileModeStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem


def test_transition_chmods_and_records_pre_mode() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/x"), mode=0o600)

    ch = SetFileModeStateChanger(
        SetFileModeParameters(path=Path("/work/x"), mode=0o644),
        file_system=fs,
    )

    result = ch.transition()

    assert result.status is ResultStatus.SUCCESS
    assert result.code == "OK"
    assert result.details.get("pre_mode") == oct(0o600)
    assert fs.stat_mode(Path("/work/x")) == 0o644


def test_transition_on_symlink_with_follow_false_changes_link_mode() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_symlink(Path("/work/lnk"), mode=0o644, link_mode=0o777)

    ch = SetFileModeStateChanger(
        SetFileModeParameters(path=Path("/work/lnk"), mode=0o700, follow_symlinks=False),
        file_system=fs,
    )

    result = ch.transition()

    assert result.status is ResultStatus.SUCCESS
    assert result.details.get("pre_mode") == oct(0o777)
    assert fs.stat_mode(Path("/work/lnk"), follow_symlinks=False) == 0o700
    # target mode unchanged
    assert fs.stat_mode(Path("/work/lnk"), follow_symlinks=True) == 0o644


def test_reassess_after_transition_is_already_applied() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/x"), mode=0o600)

    ch = SetFileModeStateChanger(
        SetFileModeParameters(path=Path("/work/x"), mode=0o644),
        file_system=fs,
    )
    ch.transition()

    from statectl._state_changer import ExistingState

    assert ch.assess_state().state is ExistingState.ALREADY_APPLIED
