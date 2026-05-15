from __future__ import annotations

from pathlib import Path

import pytest

from statectl._state_changer import ExistingState
from statectl._statechangers import (
    LiteralMatch,
    Match,
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


def _ch(fs: InMemoryFileSystem, match: Match) -> ReplaceInFileStateChanger:
    return ReplaceInFileStateChanger(
        ReplaceInFileParameters(path=P, match=match), file_system=fs
    )


@pytest.mark.parametrize(
    "content, match",
    [
        ("foo\n", LiteralMatch(needle="foo", expected_count=1, replacement="bar")),
        ("foo foo\n", LiteralMatch(needle="foo", expected_count=2, replacement="bar")),
        ("aXb\n", RegexMatch(pattern="X", expected_count=1, replacement="Y")),
        (
            "name=alice\n",
            RegexMatch(pattern=r"name=(\w+)", expected_count=1, replacement=r"name=\1-x"),
        ),
    ],
)
def test_ready_when_substitution_changes_content(content: str, match: Match) -> None:
    fs = _fs(content)
    a = _ch(fs, match).assess_state()
    assert a.state is ExistingState.READY


@pytest.mark.parametrize(
    "content, match",
    [
        # Post-state already in place: replacement equals current content
        ("bar\n", LiteralMatch(needle="foo", expected_count=1, replacement="bar")),
        # No-op replacement (needle == replacement)
        ("foo\n", LiteralMatch(needle="foo", expected_count=1, replacement="foo")),
        # expected_count=0 → no replacements requested, no-op
        ("foo\n", LiteralMatch(needle="foo", expected_count=0, replacement="bar")),
        # regex matches nothing → applying is a no-op
        ("hello\n", RegexMatch(pattern="X", expected_count=0, replacement="Y")),
    ],
)
def test_already_applied_when_substitution_is_noop(content: str, match: Match) -> None:
    fs = _fs(content)
    a = _ch(fs, match).assess_state()
    assert a.state is ExistingState.ALREADY_APPLIED
