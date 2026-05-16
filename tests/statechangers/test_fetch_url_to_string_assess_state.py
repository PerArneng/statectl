from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from statectl._state_changer import ExistingState
from statectl._statechangers import (
    FetchUrlToStringParameters,
    FetchUrlToStringStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_clock import ScriptedClock
from tests.fakes.scripted_http_client import ScriptedHttpClient


CACHE = Path("/work/x.txt")


def _changer(
    fs: InMemoryFileSystem,
    clock: ScriptedClock | None = None,
    url: str = "https://example.com/x",
    max_age: timedelta | None = None,
) -> FetchUrlToStringStateChanger:
    return FetchUrlToStringStateChanger(
        FetchUrlToStringParameters(
            url=url, cache_path=CACHE, max_age=max_age
        ),
        file_system=fs,
        http_client=ScriptedHttpClient(),
        clock=clock or ScriptedClock(),
    )


def test_ready_when_cache_absent_and_parent_writable() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))

    assessment = _changer(fs).assess_state()

    assert assessment.state is ExistingState.READY
    assert assessment.issues == []


def test_already_applied_when_cache_present_and_no_max_age() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(CACHE, content="cached")

    assessment = _changer(fs).assess_state()

    assert assessment.state is ExistingState.ALREADY_APPLIED


def test_already_applied_when_cache_fresh_within_max_age() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(CACHE, content="cached")
    clock = ScriptedClock()
    # mtime default is 2026-01-01 UTC; advance clock 1 hour
    clock.advance(timedelta(hours=1))

    assessment = _changer(fs, clock=clock, max_age=timedelta(hours=2)).assess_state()

    assert assessment.state is ExistingState.ALREADY_APPLIED


def test_ready_when_cache_stale_beyond_max_age() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(CACHE, content="cached")
    clock = ScriptedClock()
    clock.advance(timedelta(hours=3))

    assessment = _changer(fs, clock=clock, max_age=timedelta(hours=2)).assess_state()

    assert assessment.state is ExistingState.READY


def test_already_applied_at_exact_max_age_boundary() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(CACHE, content="cached")
    clock = ScriptedClock()
    clock.advance(timedelta(hours=2))

    assessment = _changer(fs, clock=clock, max_age=timedelta(hours=2)).assess_state()

    assert assessment.state is ExistingState.ALREADY_APPLIED


def test_invalid_when_parent_directory_missing() -> None:
    fs = InMemoryFileSystem()

    assessment = _changer(fs).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("parent directory does not exist" in i for i in assessment.issues)


def test_invalid_when_parent_is_not_a_directory() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/"))
    fs.add_file(Path("/work"), content="oops")

    assessment = _changer(fs).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("parent is not a directory" in i for i in assessment.issues)


def test_invalid_when_parent_not_writable() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"), writable=False)

    assessment = _changer(fs).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("not writable" in i for i in assessment.issues)


def test_invalid_when_cache_path_exists_as_directory() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(CACHE)

    assessment = _changer(fs).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("not a regular file" in i for i in assessment.issues)


@pytest.mark.parametrize(
    "bad_url",
    ["ftp://example.com/x", "file:///etc/hosts", "/no-scheme", ""],
)
def test_invalid_when_url_scheme_not_http(bad_url: str) -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))

    assessment = _changer(fs, url=bad_url).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("http" in i for i in assessment.issues)


def test_assess_collects_all_issues_in_one_pass() -> None:
    fs = InMemoryFileSystem()
    # parent missing AND url invalid
    changer = _changer(fs, url="ftp://example.com/x")

    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert len(assessment.issues) >= 2
