from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from statectl._state_changer import RollbackableStateChanger, StateChanger
from statectl._statechangers import (
    DownloadFileParameters,
    DownloadFileRollbackStateChanger,
    DownloadFileStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_hashing import ScriptedHashing
from tests.fakes.scripted_http_client import ScriptedHttpClient


def _stack(
    url: str = "http://x/a",
    dest: Path = Path("/work/a"),
    sha256: str | None = None,
    mode: int | None = None,
    overwrite_mismatch: bool = False,
) -> tuple[
    DownloadFileStateChanger,
    InMemoryFileSystem,
    ScriptedHttpClient,
    ScriptedHashing,
]:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    http = ScriptedHttpClient(file_system=fs)
    hashing = ScriptedHashing(file_system=fs)
    changer = DownloadFileStateChanger(
        DownloadFileParameters(
            url=url,
            dest=dest,
            sha256=sha256,
            mode=mode,
            overwrite_mismatch=overwrite_mismatch,
        ),
        file_system=fs,
        http_client=http,
        hashing=hashing,
    )
    return changer, fs, http, hashing


def test_is_rollbackable() -> None:
    changer, *_ = _stack()
    assert isinstance(changer, RollbackableStateChanger)


def test_rollback_is_plain_state_changer() -> None:
    changer, *_ = _stack()
    rollback = changer.rollback()
    assert isinstance(rollback, StateChanger)
    assert not isinstance(rollback, RollbackableStateChanger)
    assert isinstance(rollback, DownloadFileRollbackStateChanger)


def test_parameters_are_frozen() -> None:
    params = DownloadFileParameters(url="http://x/a", dest=Path("/work/a"))
    with pytest.raises(FrozenInstanceError):
        params.url = "http://other"  # type: ignore[misc]


def test_name_contains_dest_for_both_directions() -> None:
    changer, *_ = _stack(dest=Path("/work/abc"))
    rb = changer.rollback()
    assert "/work/abc" in changer.name()
    assert "/work/abc" in rb.name()
    assert changer.name() != rb.name()


def test_assess_state_does_not_call_http_or_mutate() -> None:
    changer, fs, http, hashing = _stack()
    snapshot = dict(fs._nodes)
    changer.assess_state()
    assert fs._nodes == snapshot
    assert http.calls == []
