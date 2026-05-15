from __future__ import annotations

from pathlib import Path

import pytest

from statectl._state_changer import ExistingState, ResultStatus
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


def _setup(content: str) -> InMemoryFileSystem:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/w"))
    fs.add_file(P, content=content)
    return fs


def _run(
    fs: InMemoryFileSystem, line: str, placement: Placement
) -> tuple[ResultStatus, str]:
    ch = EnsureLineInFileStateChanger(
        EnsureLineInFileParameters(path=P, line=line, placement=placement),
        file_system=fs,
    )
    r = ch.transition()
    return r.status, fs.read_text_file(P)


@pytest.mark.parametrize(
    "content,line,placement,expected",
    [
        ("a\nb\n", "z", AtStart(), "z\na\nb\n"),
        ("a\nb\n", "z", AtEnd(), "a\nb\nz\n"),
        ("hdr\nbody\n", "ins", AfterRegex(pattern="^hdr$"), "hdr\nins\nbody\n"),
        ("hdr\nbody\n", "ins", BeforeRegex(pattern="^body$"), "hdr\nins\nbody\n"),
        ("", "z", AtStart(), "z\n"),
        ("", "z", AtEnd(), "z\n"),
    ],
)
def test_transition_inserts_line_at_correct_position(
    content: str, line: str, placement: Placement, expected: str
) -> None:
    fs = _setup(content)
    status, after = _run(fs, line, placement)
    assert status is ResultStatus.SUCCESS
    assert after == expected


def test_re_assess_after_transition_is_already_applied() -> None:
    fs = _setup("hdr\nbody\n")
    ch = EnsureLineInFileStateChanger(
        EnsureLineInFileParameters(
            path=P, line="ins", placement=AfterRegex(pattern="^hdr$")
        ),
        file_system=fs,
    )
    assert ch.transition().status is ResultStatus.SUCCESS
    assert ch.assess_state().state is ExistingState.ALREADY_APPLIED
