from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import timedelta
from pathlib import Path

import pytest

from statectl._state_changer import RollbackableStateChanger
from statectl._statechangers import (
    FetchUrlToStringParameters,
    FetchUrlToStringStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_clock import ScriptedClock
from tests.fakes.scripted_http_client import ScriptedHttpClient


def _changer(
    fs: InMemoryFileSystem,
    http: ScriptedHttpClient,
    clock: ScriptedClock,
    url: str = "https://example.com/x",
    cache_path: Path = Path("/work/x.txt"),
    max_age: timedelta | None = None,
) -> FetchUrlToStringStateChanger:
    return FetchUrlToStringStateChanger(
        FetchUrlToStringParameters(
            url=url, cache_path=cache_path, max_age=max_age
        ),
        file_system=fs,
        http_client=http,
        clock=clock,
    )


def test_extends_rollbackable_state_changer() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    changer = _changer(fs, ScriptedHttpClient(), ScriptedClock())

    assert isinstance(changer, RollbackableStateChanger)


def test_parameters_are_frozen() -> None:
    params = FetchUrlToStringParameters(
        url="https://example.com", cache_path=Path("/x")
    )

    with pytest.raises(FrozenInstanceError):
        params.url = "other"  # type: ignore[misc]


def test_name_contains_cache_path_for_both_directions() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    changer = _changer(fs, ScriptedHttpClient(), ScriptedClock())
    rollback = changer.rollback()

    assert "/work/x.txt" in changer.name()
    assert "/work/x.txt" in rollback.name()
    assert changer.name() != rollback.name()


def test_assess_state_does_not_call_http_or_fs_action_methods() -> None:
    inner = InMemoryFileSystem()
    inner.add_dir(Path("/work"))
    inner.add_file(Path("/work/x.txt"), content="cached")
    http = ScriptedHttpClient()
    clock = ScriptedClock()
    changer = _changer(inner, http, clock, max_age=timedelta(hours=1))

    changer.assess_state()
    changer.assess_state()

    assert http.calls == []


def test_assess_state_is_pure_when_called_repeatedly() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    changer = _changer(fs, ScriptedHttpClient(), ScriptedClock())
    snapshot = dict(fs._nodes)

    first = changer.assess_state()
    second = changer.assess_state()

    assert first.state is second.state
    assert fs._nodes == snapshot
