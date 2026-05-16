from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from statectl._state_changer import ExistingState, ResultStatus
from statectl._statechangers import (
    FetchUrlToStringParameters,
    FetchUrlToStringStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_clock import ScriptedClock
from tests.fakes.scripted_http_client import ScriptedHttpClient


URL = "https://example.com/x"
CACHE = Path("/work/x.txt")


def _build(
    *,
    max_age: timedelta | None = None,
) -> tuple[FetchUrlToStringStateChanger, InMemoryFileSystem, ScriptedHttpClient]:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    http = ScriptedHttpClient()
    http.register_bytes(URL, b"payload")
    changer = FetchUrlToStringStateChanger(
        FetchUrlToStringParameters(url=URL, cache_path=CACHE, max_age=max_age),
        file_system=fs,
        http_client=http,
        clock=ScriptedClock(),
    )
    return changer, fs, http


def test_apply_then_rollback_leaves_filesystem_unchanged() -> None:
    changer, fs, _http = _build()

    assert changer.assess_state().state is ExistingState.READY
    assert changer.transition().status is ResultStatus.SUCCESS
    assert fs.is_file(CACHE)

    rollback = changer.rollback()
    assert rollback.assess_state().state is ExistingState.READY
    assert rollback.transition().status is ResultStatus.SUCCESS
    assert not fs.exists(CACHE)


def test_apply_is_idempotent_without_max_age() -> None:
    changer, _fs, http = _build()

    changer.transition()
    # second pass: cache present, no max_age → ALREADY_APPLIED, no second fetch
    assert changer.assess_state().state is ExistingState.ALREADY_APPLIED
    assert [c.method for c in http.calls] == ["get_bytes"]


def test_rollback_after_rollback_is_already_applied() -> None:
    changer, _fs, _http = _build()
    changer.transition()
    changer.rollback().transition()

    assert changer.rollback().assess_state().state is ExistingState.ALREADY_APPLIED
