from __future__ import annotations

from pathlib import Path

from statectl._state_changer import ExistingState
from statectl._statechangers import (
    LiteralMatch,
    RegexMatch,
    ReplaceInFileParameters,
    ReplaceInFileStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem


def _build(fs: InMemoryFileSystem, params: ReplaceInFileParameters) -> ReplaceInFileStateChanger:
    return ReplaceInFileStateChanger(params, file_system=fs)


def test_invalid_when_file_missing() -> None:
    fs = InMemoryFileSystem()
    ch = _build(
        fs,
        ReplaceInFileParameters(
            path=Path("/nope.txt"),
            match=LiteralMatch(needle="x", expected_count=1, replacement="y"),
        ),
    )
    a = ch.assess_state()
    assert a.state is ExistingState.INVALID
    assert any("does not exist" in i for i in a.issues)


def test_invalid_when_path_is_a_directory() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    ch = _build(
        fs,
        ReplaceInFileParameters(
            path=Path("/work"),
            match=LiteralMatch(needle="x", expected_count=1, replacement="y"),
        ),
    )
    a = ch.assess_state()
    assert a.state is ExistingState.INVALID
    assert any("not a regular file" in i for i in a.issues)


def test_invalid_when_file_not_writable() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/w"))
    fs.add_file(Path("/w/c.txt"), content="foo\n", writable=False)
    ch = _build(
        fs,
        ReplaceInFileParameters(
            path=Path("/w/c.txt"),
            match=LiteralMatch(needle="foo", expected_count=1, replacement="bar"),
        ),
    )
    a = ch.assess_state()
    assert a.state is ExistingState.INVALID
    assert any("not writable" in i for i in a.issues)


def test_invalid_when_regex_is_bad() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/w"))
    fs.add_file(Path("/w/c.txt"), content="foo\n")
    ch = _build(
        fs,
        ReplaceInFileParameters(
            path=Path("/w/c.txt"),
            match=RegexMatch(pattern="[", expected_count=1, replacement="x"),
        ),
    )
    a = ch.assess_state()
    assert a.state is ExistingState.INVALID
    assert any("bad regex" in i for i in a.issues)


def test_invalid_when_match_count_mismatch_too_few() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/w"))
    fs.add_file(Path("/w/c.txt"), content="foo\n")
    ch = _build(
        fs,
        ReplaceInFileParameters(
            path=Path("/w/c.txt"),
            match=LiteralMatch(needle="foo", expected_count=3, replacement="bar"),
        ),
    )
    a = ch.assess_state()
    assert a.state is ExistingState.INVALID
    assert any("expected 3 matches, found 1" in i for i in a.issues)


def test_invalid_when_match_count_mismatch_too_many() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/w"))
    fs.add_file(Path("/w/c.txt"), content="foo foo foo\n")
    ch = _build(
        fs,
        ReplaceInFileParameters(
            path=Path("/w/c.txt"),
            match=LiteralMatch(needle="foo", expected_count=1, replacement="bar"),
        ),
    )
    a = ch.assess_state()
    assert a.state is ExistingState.INVALID
    assert any("expected 1 matches, found 3" in i for i in a.issues)


def test_invalid_when_decode_fails() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/w"))
    fs.add_file(Path("/w/c.txt"), content="x", readable_text=False)
    ch = _build(
        fs,
        ReplaceInFileParameters(
            path=Path("/w/c.txt"),
            match=LiteralMatch(needle="x", expected_count=1, replacement="y"),
        ),
    )
    a = ch.assess_state()
    assert a.state is ExistingState.INVALID
    assert any("decode failed" in i for i in a.issues)


def test_invalid_when_expected_count_is_negative() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/w"))
    fs.add_file(Path("/w/c.txt"), content="foo\n")
    ch = _build(
        fs,
        ReplaceInFileParameters(
            path=Path("/w/c.txt"),
            match=LiteralMatch(needle="foo", expected_count=-1, replacement="bar"),
        ),
    )
    a = ch.assess_state()
    assert a.state is ExistingState.INVALID
    assert any("expected_count must be >= 0" in i for i in a.issues)


def test_invalid_when_literal_needle_is_empty() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/w"))
    fs.add_file(Path("/w/c.txt"), content="foo\n")
    ch = _build(
        fs,
        ReplaceInFileParameters(
            path=Path("/w/c.txt"),
            match=LiteralMatch(needle="", expected_count=1, replacement="bar"),
        ),
    )
    a = ch.assess_state()
    assert a.state is ExistingState.INVALID
    assert any("literal needle must not be empty" in i for i in a.issues)


def test_assess_collects_multiple_issues_in_one_pass() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/w"))
    fs.add_file(Path("/w/c.txt"), content="foo\n", writable=False)
    ch = _build(
        fs,
        ReplaceInFileParameters(
            path=Path("/w/c.txt"),
            match=RegexMatch(pattern="[", expected_count=-1, replacement="x"),
        ),
    )
    a = ch.assess_state()
    assert a.state is ExistingState.INVALID
    assert any("not writable" in i for i in a.issues)
    assert any("expected_count must be >= 0" in i for i in a.issues)
    assert any("bad regex" in i for i in a.issues)
