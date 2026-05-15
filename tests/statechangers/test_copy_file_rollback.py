from __future__ import annotations

from pathlib import Path

from statectl._state_changer import ExistingState, ResultStatus
from statectl._statechangers import (
    CopyFileParameters,
    CopyFileRollbackStateChanger,
    CopyFileStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem


SRC = Path("/work/a")
DEST = Path("/work/b")


def _forward(fs: InMemoryFileSystem, **overrides: object) -> CopyFileStateChanger:
    kwargs: dict[str, object] = {"src": SRC, "dest": DEST}
    kwargs.update(overrides)
    return CopyFileStateChanger(
        CopyFileParameters(**kwargs),  # pyrefly: ignore
        file_system=fs,
    )


def _fs() -> InMemoryFileSystem:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(SRC, content="hello\n")
    return fs


def test_rollback_deletes_dest_when_it_did_not_exist_before() -> None:
    fs = _fs()
    forward = _forward(fs)
    forward.transition()
    assert fs.exists(DEST)

    rb = forward.rollback()
    assert isinstance(rb, CopyFileRollbackStateChanger)
    assert rb.dest_existed is False
    assert rb.assess_state().state is ExistingState.READY

    result = rb.transition()
    assert result.status is ResultStatus.SUCCESS
    assert not fs.exists(DEST)


def test_rollback_restores_pre_image_when_dest_existed() -> None:
    fs = _fs()
    fs.add_file(DEST, content="original\n")
    forward = _forward(fs, overwrite=True)
    forward.transition()
    assert fs.read_text_file(DEST) == "hello\n"

    rb = forward.rollback()
    assert rb.dest_existed is True
    assert rb.pre_image == b"original\n"

    result = rb.transition()
    assert result.status is ResultStatus.SUCCESS
    assert fs.read_text_file(DEST) == "original\n"


def test_rollback_already_applied_when_dest_already_gone_after_create() -> None:
    fs = _fs()
    forward = _forward(fs)
    forward.transition()
    rb = forward.rollback()
    fs.delete_file(DEST)

    assert rb.assess_state().state is ExistingState.ALREADY_APPLIED


def test_rollback_already_applied_when_pre_image_already_restored() -> None:
    fs = _fs()
    fs.add_file(DEST, content="original\n")
    forward = _forward(fs, overwrite=True)
    forward.transition()
    rb = forward.rollback()
    # someone else already restored pre-image
    fs.write_text_file(DEST, "original\n")

    assert rb.assess_state().state is ExistingState.ALREADY_APPLIED


def test_rollback_invalid_on_drift() -> None:
    fs = _fs()
    fs.add_file(DEST, content="original\n")
    forward = _forward(fs, overwrite=True)
    forward.transition()
    rb = forward.rollback()
    # someone else drifted dest to neither pre nor src image
    fs.write_text_file(DEST, "drifted\n")

    a = rb.assess_state()
    assert a.state is ExistingState.INVALID
    assert any("drifted" in i or "neither" in i for i in a.issues)


def test_rollback_invalid_when_dest_existed_but_pre_image_missing() -> None:
    fs = _fs()
    fs.add_file(DEST, content="original\n")
    # construct rollback directly without a pre_image
    rb = CopyFileRollbackStateChanger(
        CopyFileParameters(src=SRC, dest=DEST),
        dest_existed=True,
        pre_image=None,
        file_system=fs,
    )

    a = rb.assess_state()
    assert a.state is ExistingState.INVALID


def test_rollback_transition_skipped_when_created_dest_already_gone() -> None:
    fs = _fs()
    forward = _forward(fs)
    forward.transition()
    rb = forward.rollback()
    fs.delete_file(DEST)

    result = rb.transition()
    assert result.status is ResultStatus.SKIPPED
