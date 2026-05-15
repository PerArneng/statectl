from __future__ import annotations

from pathlib import Path

from statectl._state_changer import ExistingState, ResultStatus
from statectl._statechangers import (
    LiteralMatch,
    ReplaceInFileParameters,
    ReplaceInFileRollbackStateChanger,
    ReplaceInFileStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem


P = Path("/w/c.txt")


def _fs(content: str) -> InMemoryFileSystem:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/w"))
    fs.add_file(P, content=content)
    return fs


def _params() -> ReplaceInFileParameters:
    return ReplaceInFileParameters(
        path=P,
        match=LiteralMatch(needle="foo", expected_count=1, replacement="bar"),
    )


def test_rollback_already_applied_when_transition_never_ran() -> None:
    fs = _fs("foo\n")
    ch = ReplaceInFileStateChanger(_params(), file_system=fs)
    assert ch.rollback().assess_state().state is ExistingState.ALREADY_APPLIED


def test_rollback_already_applied_when_file_missing() -> None:
    fs = _fs("foo\n")
    ch = ReplaceInFileStateChanger(_params(), file_system=fs)
    assert ch.transition().status is ResultStatus.SUCCESS
    fs.delete_file(P)
    assert ch.rollback().assess_state().state is ExistingState.ALREADY_APPLIED


def test_rollback_already_applied_when_already_matches_pre_image() -> None:
    fs = _fs("foo\n")
    ch = ReplaceInFileStateChanger(_params(), file_system=fs)
    assert ch.transition().status is ResultStatus.SUCCESS
    # Restore file to pre-image manually.
    fs.add_file(P, content="foo\n")
    assert ch.rollback().assess_state().state is ExistingState.ALREADY_APPLIED


def test_rollback_invalid_when_file_drifted() -> None:
    fs = _fs("foo\n")
    ch = ReplaceInFileStateChanger(_params(), file_system=fs)
    assert ch.transition().status is ResultStatus.SUCCESS
    # File drifts to neither pre- nor post-image
    fs.add_file(P, content="something else entirely\n")
    a = ch.rollback().assess_state()
    assert a.state is ExistingState.INVALID
    assert any("drifted" in i or "refusing" in i for i in a.issues)


def test_rollback_restores_pre_image() -> None:
    fs = _fs("foo\n")
    ch = ReplaceInFileStateChanger(_params(), file_system=fs)
    assert ch.transition().status is ResultStatus.SUCCESS
    assert fs.read_text_file(P) == "bar\n"
    result = ch.rollback().transition()
    assert result.status is ResultStatus.SUCCESS
    assert fs.read_text_file(P) == "foo\n"


def test_apply_then_rollback_round_trips() -> None:
    fs = _fs("hello foo world\n")
    ch = ReplaceInFileStateChanger(_params(), file_system=fs)
    original = fs.read_text_file(P)
    assert ch.transition().status is ResultStatus.SUCCESS
    assert ch.assess_state().state is ExistingState.ALREADY_APPLIED
    assert ch.rollback().transition().status is ResultStatus.SUCCESS
    assert fs.read_text_file(P) == original


def test_rollback_constructed_without_pre_image_is_already_applied() -> None:
    fs = _fs("bar\n")
    rb = ReplaceInFileRollbackStateChanger(_params(), file_system=fs)
    assert rb.assess_state().state is ExistingState.ALREADY_APPLIED


def test_rollback_transition_skipped_without_pre_image() -> None:
    fs = _fs("bar\n")
    rb = ReplaceInFileRollbackStateChanger(_params(), file_system=fs)
    assert rb.transition().status is ResultStatus.SKIPPED
