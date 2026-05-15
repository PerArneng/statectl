from __future__ import annotations

from pathlib import Path

import pytest

from statectl._state_changer import ExistingState
from statectl._statechangers import (
    AfterRegex,
    AtEnd,
    AtStart,
    BeforeRegex,
    EnsureLineInFileParameters,
    EnsureLineInFileStateChanger,
    Placement,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem


P = Path("/w/c.txt")


def _fs(content: str) -> InMemoryFileSystem:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/w"))
    fs.add_file(P, content=content)
    return fs


def _assess(
    content: str, line: str, placement: Placement, strict: bool = True
) -> ExistingState:
    fs = _fs(content)
    ch = EnsureLineInFileStateChanger(
        EnsureLineInFileParameters(
            path=P, line=line, placement=placement, strict_anchor=strict
        ),
        file_system=fs,
    )
    return ch.assess_state().state


@pytest.mark.parametrize(
    "content,line,placement,expected",
    [
        # AtStart
        ("first\nsecond\n", "first", AtStart(), ExistingState.ALREADY_APPLIED),
        ("second\nfirst\n", "first", AtStart(), ExistingState.INVALID),
        ("a\nb\n", "first", AtStart(), ExistingState.READY),
        ("", "first", AtStart(), ExistingState.READY),
        # AtEnd
        ("a\nlast\n", "last", AtEnd(), ExistingState.ALREADY_APPLIED),
        ("last\na\n", "last", AtEnd(), ExistingState.INVALID),
        ("a\nb\n", "last", AtEnd(), ExistingState.READY),
        # AfterRegex
        ("hdr\nbody\n", "body", AfterRegex(pattern="^hdr$"), ExistingState.ALREADY_APPLIED),
        ("hdr\nother\n", "body", AfterRegex(pattern="^hdr$"), ExistingState.READY),
        # BeforeRegex
        ("body\nftr\n", "body", BeforeRegex(pattern="^ftr$"), ExistingState.ALREADY_APPLIED),
        ("other\nftr\n", "body", BeforeRegex(pattern="^ftr$"), ExistingState.READY),
    ],
)
def test_strict_anchor_truth_table(
    content: str, line: str, placement: Placement, expected: ExistingState
) -> None:
    assert _assess(content, line, placement, strict=True) is expected


def test_non_strict_anchor_accepts_line_anywhere() -> None:
    # line exists at top, anchor wants it after "hdr"
    assert (
        _assess(
            "body\nhdr\nother\n",
            "body",
            AfterRegex(pattern="^hdr$"),
            strict=False,
        )
        is ExistingState.ALREADY_APPLIED
    )


def test_at_end_empty_file_is_ready() -> None:
    assert _assess("", "x", AtEnd()) is ExistingState.READY
