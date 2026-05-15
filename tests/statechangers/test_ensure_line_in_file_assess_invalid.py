from __future__ import annotations

from pathlib import Path

from statectl._state_changer import ExistingState
from statectl._statechangers import (
    AfterRegex,
    AtEnd,
    BeforeRegex,
    EnsureLineInFileParameters,
    EnsureLineInFileStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem


def _build(fs: InMemoryFileSystem, params: EnsureLineInFileParameters) -> EnsureLineInFileStateChanger:
    return EnsureLineInFileStateChanger(params, file_system=fs)


def test_invalid_when_file_missing() -> None:
    fs = InMemoryFileSystem()
    ch = _build(
        fs,
        EnsureLineInFileParameters(path=Path("/nope.txt"), line="x", placement=AtEnd()),
    )
    a = ch.assess_state()
    assert a.state is ExistingState.INVALID
    assert any("does not exist" in i for i in a.issues)


def test_invalid_when_path_is_a_directory() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    ch = _build(
        fs,
        EnsureLineInFileParameters(path=Path("/work"), line="x", placement=AtEnd()),
    )
    a = ch.assess_state()
    assert a.state is ExistingState.INVALID
    assert any("not a regular file" in i for i in a.issues)


def test_invalid_when_file_not_writable() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/w"))
    fs.add_file(Path("/w/c.txt"), content="a\n", writable=False)
    ch = _build(
        fs,
        EnsureLineInFileParameters(path=Path("/w/c.txt"), line="x", placement=AtEnd()),
    )
    a = ch.assess_state()
    assert a.state is ExistingState.INVALID
    assert any("not writable" in i for i in a.issues)


def test_invalid_when_line_contains_newline() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/w"))
    fs.add_file(Path("/w/c.txt"), content="a\n")
    ch = _build(
        fs,
        EnsureLineInFileParameters(
            path=Path("/w/c.txt"), line="a\nb", placement=AtEnd()
        ),
    )
    a = ch.assess_state()
    assert a.state is ExistingState.INVALID
    assert any("must not contain newline" in i for i in a.issues)


def test_invalid_when_anchor_matches_zero_lines() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/w"))
    fs.add_file(Path("/w/c.txt"), content="foo\nbar\n")
    ch = _build(
        fs,
        EnsureLineInFileParameters(
            path=Path("/w/c.txt"),
            line="new",
            placement=AfterRegex(pattern="zzz"),
        ),
    )
    a = ch.assess_state()
    assert a.state is ExistingState.INVALID
    assert any("anchor not found" in i for i in a.issues)


def test_invalid_when_anchor_matches_multiple_lines() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/w"))
    fs.add_file(Path("/w/c.txt"), content="foo\nfoo\nbar\n")
    ch = _build(
        fs,
        EnsureLineInFileParameters(
            path=Path("/w/c.txt"),
            line="new",
            placement=AfterRegex(pattern="foo"),
        ),
    )
    a = ch.assess_state()
    assert a.state is ExistingState.INVALID
    assert any("ambiguous" in i for i in a.issues)


def test_invalid_when_anchor_regex_is_invalid() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/w"))
    fs.add_file(Path("/w/c.txt"), content="x\n")
    ch = _build(
        fs,
        EnsureLineInFileParameters(
            path=Path("/w/c.txt"),
            line="new",
            placement=BeforeRegex(pattern="["),
        ),
    )
    a = ch.assess_state()
    assert a.state is ExistingState.INVALID
    assert any("invalid anchor regex" in i for i in a.issues)


def test_invalid_when_line_exists_at_wrong_location_with_strict_anchor() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/w"))
    fs.add_file(Path("/w/c.txt"), content="want\nfoo\nbar\n")
    ch = _build(
        fs,
        EnsureLineInFileParameters(
            path=Path("/w/c.txt"),
            line="want",
            placement=AfterRegex(pattern="bar"),
            strict_anchor=True,
        ),
    )
    a = ch.assess_state()
    assert a.state is ExistingState.INVALID
    assert any("wrong location" in i for i in a.issues)


def test_assess_collects_multiple_issues_in_one_pass() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/w"))
    fs.add_file(Path("/w/c.txt"), content="x", writable=False)
    ch = _build(
        fs,
        EnsureLineInFileParameters(
            path=Path("/w/c.txt"),
            line="bad\nline",
            placement=AtEnd(),
        ),
    )
    a = ch.assess_state()
    assert a.state is ExistingState.INVALID
    assert any("not writable" in i for i in a.issues)
    assert any("must not contain newline" in i for i in a.issues)
