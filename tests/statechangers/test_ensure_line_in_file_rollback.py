from __future__ import annotations

from pathlib import Path

from statectl._state_changer import ExistingState, ResultStatus
from statectl._statechangers import (
    AfterRegex,
    AtEnd,
    EnsureLineInFileParameters,
    EnsureLineInFileStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem


P = Path("/w/c.txt")


def _fs(content: str) -> InMemoryFileSystem:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/w"))
    fs.add_file(P, content=content)
    return fs


def test_rollback_already_applied_when_file_missing() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/w"))
    ch = EnsureLineInFileStateChanger(
        EnsureLineInFileParameters(path=P, line="z", placement=AtEnd()),
        file_system=fs,
    )
    assert ch.rollback().assess_state().state is ExistingState.ALREADY_APPLIED


def test_rollback_already_applied_when_line_absent() -> None:
    fs = _fs("a\nb\n")
    ch = EnsureLineInFileStateChanger(
        EnsureLineInFileParameters(path=P, line="z", placement=AtEnd()),
        file_system=fs,
    )
    assert ch.rollback().assess_state().state is ExistingState.ALREADY_APPLIED


def test_rollback_removes_line_at_end() -> None:
    fs = _fs("a\nb\nz\n")
    ch = EnsureLineInFileStateChanger(
        EnsureLineInFileParameters(path=P, line="z", placement=AtEnd()),
        file_system=fs,
    )
    result = ch.rollback().transition()
    assert result.status is ResultStatus.SUCCESS
    assert fs.read_text_file(P) == "a\nb\n"


def test_rollback_removes_line_after_anchor() -> None:
    fs = _fs("hdr\nins\nbody\n")
    ch = EnsureLineInFileStateChanger(
        EnsureLineInFileParameters(
            path=P, line="ins", placement=AfterRegex(pattern="^hdr$")
        ),
        file_system=fs,
    )
    assert ch.rollback().transition().status is ResultStatus.SUCCESS
    assert fs.read_text_file(P) == "hdr\nbody\n"


def test_rollback_removes_only_the_targeted_occurrence() -> None:
    # `strict_anchor=False` is what tolerates dupes during apply; rollback
    # must remove only the copy at the placement-implied position.
    fs = _fs("ins\nhdr\nins\nbody\n")
    ch = EnsureLineInFileStateChanger(
        EnsureLineInFileParameters(
            path=P,
            line="ins",
            placement=AfterRegex(pattern="^hdr$"),
            strict_anchor=False,
        ),
        file_system=fs,
    )
    assert ch.rollback().transition().status is ResultStatus.SUCCESS
    # only the copy after hdr is removed; the earlier copy remains
    assert fs.read_text_file(P) == "ins\nhdr\nbody\n"


def test_apply_then_rollback_round_trips() -> None:
    fs = _fs("hdr\nbody\n")
    ch = EnsureLineInFileStateChanger(
        EnsureLineInFileParameters(
            path=P, line="ins", placement=AfterRegex(pattern="^hdr$")
        ),
        file_system=fs,
    )
    original = fs.read_text_file(P)

    assert ch.transition().status is ResultStatus.SUCCESS
    assert ch.assess_state().state is ExistingState.ALREADY_APPLIED

    assert ch.rollback().transition().status is ResultStatus.SUCCESS
    assert fs.read_text_file(P) == original
