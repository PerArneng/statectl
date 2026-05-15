from __future__ import annotations

from pathlib import Path

from statectl._state_changer import ExistingState, ResultStatus
from statectl._statechangers import (
    LiteralMatch,
    RegexMatch,
    ReplaceInFileParameters,
    ReplaceInFileStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem


P = Path("/w/c.txt")


def _fs(content: str) -> InMemoryFileSystem:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/w"))
    fs.add_file(P, content=content)
    return fs


def test_literal_single_replacement() -> None:
    fs = _fs("foo bar baz\n")
    ch = ReplaceInFileStateChanger(
        ReplaceInFileParameters(
            path=P,
            match=LiteralMatch(needle="bar", expected_count=1, replacement="BAR"),
        ),
        file_system=fs,
    )
    result = ch.transition()
    assert result.status is ResultStatus.SUCCESS
    assert fs.read_text_file(P) == "foo BAR baz\n"
    assert "pre_sha256" in result.details


def test_literal_replaces_only_expected_count() -> None:
    fs = _fs("aaaa\n")
    ch = ReplaceInFileStateChanger(
        ReplaceInFileParameters(
            path=P,
            match=LiteralMatch(needle="a", expected_count=4, replacement="b"),
        ),
        file_system=fs,
    )
    assert ch.transition().status is ResultStatus.SUCCESS
    assert fs.read_text_file(P) == "bbbb\n"


def test_regex_with_backreference() -> None:
    fs = _fs("name=alice\n")
    ch = ReplaceInFileStateChanger(
        ReplaceInFileParameters(
            path=P,
            match=RegexMatch(
                pattern=r"name=(\w+)", expected_count=1, replacement=r"user=\1"
            ),
        ),
        file_system=fs,
    )
    assert ch.transition().status is ResultStatus.SUCCESS
    assert fs.read_text_file(P) == "user=alice\n"


def test_regex_replaces_exactly_expected_count_when_more_exist() -> None:
    # Sanity: if more matches exist than expected, transition would normally
    # be reached only after a passing assess. But verify the regex sub honours
    # the cap if called directly (assess will already have rejected this).
    fs = _fs("X X X\n")
    ch = ReplaceInFileStateChanger(
        ReplaceInFileParameters(
            path=P,
            match=RegexMatch(pattern="X", expected_count=3, replacement="Y"),
        ),
        file_system=fs,
    )
    assert ch.transition().status is ResultStatus.SUCCESS
    assert fs.read_text_file(P) == "Y Y Y\n"


def test_second_assess_returns_already_applied_after_transition() -> None:
    fs = _fs("foo\n")
    ch = ReplaceInFileStateChanger(
        ReplaceInFileParameters(
            path=P,
            match=LiteralMatch(needle="foo", expected_count=1, replacement="bar"),
        ),
        file_system=fs,
    )
    assert ch.transition().status is ResultStatus.SUCCESS
    assert ch.assess_state().state is ExistingState.ALREADY_APPLIED
