from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from statectl._state_changer import ExistingState
from statectl._statechangers import AptUpdateParameters, AptUpdateStateChanger
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_clock import ScriptedClock
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


_LISTS = Path("/var/lib/apt/lists")
_NOW = datetime(2026, 5, 16, 12, 0, 0, tzinfo=timezone.utc)


def _clock_at(now: datetime) -> ScriptedClock:
    clock = ScriptedClock()
    clock.set_now(now)
    return clock


def _build(
    *,
    release_mtime: datetime | None = None,
    max_age: timedelta = timedelta(hours=24),
    release_name: str = "deb.debian.org_dists_stable_Release",
    extra_files: list[tuple[str, datetime | None]] | None = None,
) -> AptUpdateStateChanger:
    pr = ScriptedProcessRunner()
    pr.register_executable("apt-get")
    fs = InMemoryFileSystem()
    fs.add_dir(_LISTS)
    if release_mtime is not None:
        path = _LISTS / release_name
        fs.add_file(path, content="")
        fs.set_mtime(path, release_mtime)
    for name, mtime in extra_files or []:
        path = _LISTS / name
        fs.add_file(path, content="")
        if mtime is not None:
            fs.set_mtime(path, mtime)
    return AptUpdateStateChanger(
        AptUpdateParameters(max_age=max_age),
        process_runner=pr,
        file_system=fs,
        env=ScriptedEnv.linux(),
        clock=_clock_at(_NOW),
    )


def test_ready_when_lists_dir_empty() -> None:
    changer = _build()
    a = changer.assess_state()
    assert a.state is ExistingState.READY


def test_ready_when_release_file_is_stale() -> None:
    stale = _NOW - timedelta(hours=48)
    changer = _build(release_mtime=stale)
    a = changer.assess_state()
    assert a.state is ExistingState.READY


def test_already_applied_when_release_file_is_fresh() -> None:
    fresh = _NOW - timedelta(hours=1)
    changer = _build(release_mtime=fresh)
    a = changer.assess_state()
    assert a.state is ExistingState.ALREADY_APPLIED


def test_already_applied_at_exact_max_age_boundary() -> None:
    boundary = _NOW - timedelta(hours=24)
    changer = _build(release_mtime=boundary, max_age=timedelta(hours=24))
    a = changer.assess_state()
    assert a.state is ExistingState.ALREADY_APPLIED


def test_ready_when_just_past_max_age_boundary() -> None:
    just_past = _NOW - timedelta(hours=24, seconds=1)
    changer = _build(release_mtime=just_past, max_age=timedelta(hours=24))
    a = changer.assess_state()
    assert a.state is ExistingState.READY


@pytest.mark.parametrize(
    "max_age,age,expected",
    [
        (timedelta(hours=1), timedelta(minutes=30), ExistingState.ALREADY_APPLIED),
        (timedelta(hours=1), timedelta(hours=2), ExistingState.READY),
        (timedelta(minutes=5), timedelta(minutes=4), ExistingState.ALREADY_APPLIED),
        (timedelta(minutes=5), timedelta(minutes=6), ExistingState.READY),
    ],
)
def test_max_age_truth_table(
    max_age: timedelta, age: timedelta, expected: ExistingState
) -> None:
    changer = _build(release_mtime=_NOW - age, max_age=max_age)
    a = changer.assess_state()
    assert a.state is expected


def test_uses_newest_release_when_multiple_present() -> None:
    # One stale, one fresh — fresh wins.
    stale = _NOW - timedelta(days=10)
    fresh = _NOW - timedelta(hours=1)
    changer = _build(
        release_mtime=stale,
        release_name="src_a_Release",
        extra_files=[("src_b_InRelease", fresh)],
    )
    a = changer.assess_state()
    assert a.state is ExistingState.ALREADY_APPLIED


def test_ignores_non_release_files() -> None:
    fresh = _NOW - timedelta(hours=1)
    # None of these match the `_Release` / `_InRelease` underscore-prefixed
    # suffix, so they must be ignored — including the deliberate "MyRelease"
    # which would have matched a loose `endswith("Release")` check.
    changer = _build(
        extra_files=[
            ("partial.gz", fresh),
            ("lock", fresh),
            ("MyRelease", fresh),
        ],
    )
    a = changer.assess_state()
    assert a.state is ExistingState.READY
