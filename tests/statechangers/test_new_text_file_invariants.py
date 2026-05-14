from __future__ import annotations

from pathlib import Path

import pytest

from statectl._interfaces.fs import FsIoError
from statectl._state_changer import (
    ExistingState,
    ResultStatus,
    RollbackableStateChanger,
)
from statectl._statechangers import (
    NewTextFileParameters,
    NewTextFileStateChanger,
)
from tests.fakes.failing_file_system import FailingFileSystem
from tests.fakes.in_memory_file_system import InMemoryFileSystem


def _changer(
    fs: InMemoryFileSystem | FailingFileSystem,
    path: Path,
    text: str,
) -> RollbackableStateChanger:
    return NewTextFileStateChanger(
        NewTextFileParameters(path=path, text=text),
        file_system=fs,
    )


@pytest.mark.parametrize(
    "text",
    ["", "hi", "line1\nline2\n", "héllo wörld 🌍", "x" * 10_000],
    ids=["empty", "ascii", "multiline", "unicode", "large"],
)
def test_transition_writes_content_verbatim(text: str) -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    target = Path("/work/hello.txt")
    changer = _changer(fs, target, text)

    assert changer.transition().status is ResultStatus.SUCCESS
    assert fs.read_text_file(target) == text


def test_ready_assessment_has_no_issues() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    assessment = _changer(fs, Path("/work/hello.txt"), "hi").assess_state()

    assert assessment.state is ExistingState.READY
    assert assessment.issues == []


def test_already_applied_assessment_has_no_issues() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/hello.txt"), content="hi")
    assessment = _changer(fs, Path("/work/hello.txt"), "hi").assess_state()

    assert assessment.state is ExistingState.ALREADY_APPLIED
    assert assessment.issues == []


def test_assess_state_is_pure_when_called_repeatedly() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    changer = _changer(fs, Path("/work/hello.txt"), "hi")
    snapshot = dict(fs._nodes)

    first = changer.assess_state()
    second = changer.assess_state()

    assert first.state is second.state
    assert fs._nodes == snapshot


def test_transition_only_mutates_the_target_path() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/other.txt"), content="keep me")
    fs.add_dir(Path("/work/sub"))
    target = Path("/work/hello.txt")
    other_paths_before = {p: dict(n.__dict__) for p, n in fs._nodes.items() if p != target}

    _changer(fs, target, "hi").transition()

    other_paths_after = {p: dict(n.__dict__) for p, n in fs._nodes.items() if p != target}
    assert other_paths_before == other_paths_after


def test_rollback_transition_only_removes_target_path() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/other.txt"), content="keep me")
    target = Path("/work/hello.txt")
    fs.add_file(target, content="hi")

    _changer(fs, target, "hi").rollback().transition()

    assert not fs.exists(target)
    assert fs.is_file(Path("/work/other.txt"))
    assert fs.read_text_file(Path("/work/other.txt")) == "keep me"


def test_rollback_removes_file_even_when_content_differs_from_params() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    target = Path("/work/hello.txt")
    fs.add_file(target, content="something else")

    rollback = _changer(fs, target, "hi").rollback()

    assert rollback.assess_state().state is ExistingState.READY
    assert rollback.transition().status is ResultStatus.SUCCESS
    assert not fs.exists(target)


def test_failed_transition_does_not_create_target() -> None:
    inner = InMemoryFileSystem()
    inner.add_dir(Path("/work"))
    fs = FailingFileSystem(inner)
    target = Path("/work/hello.txt")
    fs.fail("write_text_file", FsIoError("disk full", path=target), path=target)
    changer = _changer(fs, target, "hi")

    result = changer.transition()

    assert result.status is ResultStatus.FAILURE
    assert not inner.exists(target)


def test_rollback_after_failed_transition_is_already_applied() -> None:
    inner = InMemoryFileSystem()
    inner.add_dir(Path("/work"))
    fs = FailingFileSystem(inner)
    target = Path("/work/hello.txt")
    fs.fail("write_text_file", FsIoError("disk full", path=target), path=target)
    changer = _changer(fs, target, "hi")

    changer.transition()

    assert changer.rollback().assess_state().state is ExistingState.ALREADY_APPLIED


def test_name_contains_target_path_for_both_directions() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    target = Path("/work/hello.txt")
    changer = _changer(fs, target, "hi")
    rollback = changer.rollback()

    assert str(target) in changer.name()
    assert str(target) in rollback.name()
    assert changer.name() != rollback.name()


def test_custom_encoding_round_trips() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    target = Path("/work/hello.txt")
    changer = NewTextFileStateChanger(
        NewTextFileParameters(path=target, text="héllo", encoding="latin-1"),
        file_system=fs,
    )

    assert changer.transition().status is ResultStatus.SUCCESS
    assert changer.assess_state().state is ExistingState.ALREADY_APPLIED


def test_rollback_after_successful_apply_uses_same_filesystem() -> None:
    inner = InMemoryFileSystem()
    inner.add_dir(Path("/work"))
    fs = FailingFileSystem(inner)
    target = Path("/work/hello.txt")
    changer = _changer(fs, target, "hi")

    changer.transition()
    assert inner.is_file(target)
    fs.fail("delete_file", FsIoError("device busy", path=target), path=target)

    result = changer.rollback().transition()

    assert result.status is ResultStatus.FAILURE
    assert inner.is_file(target)
