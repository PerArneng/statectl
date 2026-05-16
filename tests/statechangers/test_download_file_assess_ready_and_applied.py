from __future__ import annotations

from pathlib import Path

from statectl._state_changer import ExistingState
from statectl._statechangers import (
    DownloadFileParameters,
    DownloadFileStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_hashing import ScriptedHashing, sha256_of
from tests.fakes.scripted_http_client import ScriptedHttpClient


def _build(
    params: DownloadFileParameters,
    fs: InMemoryFileSystem,
) -> DownloadFileStateChanger:
    return DownloadFileStateChanger(
        params,
        file_system=fs,
        http_client=ScriptedHttpClient(file_system=fs),
        hashing=ScriptedHashing(file_system=fs),
    )


def test_ready_when_dest_absent_no_sha() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    a = _build(
        DownloadFileParameters(url="http://x/a", dest=Path("/work/a")),
        fs,
    ).assess_state()
    assert a.state is ExistingState.READY


def test_already_applied_when_dest_present_no_sha_no_mode() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/a"), content="anything")
    a = _build(
        DownloadFileParameters(url="http://x/a", dest=Path("/work/a")),
        fs,
    ).assess_state()
    assert a.state is ExistingState.ALREADY_APPLIED


def test_already_applied_when_sha_matches() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/a"), content="hello")
    a = _build(
        DownloadFileParameters(
            url="http://x/a", dest=Path("/work/a"), sha256=sha256_of("hello")
        ),
        fs,
    ).assess_state()
    assert a.state is ExistingState.ALREADY_APPLIED


def test_ready_when_sha_mismatches_and_overwrite_allowed() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/a"), content="old")
    a = _build(
        DownloadFileParameters(
            url="http://x/a",
            dest=Path("/work/a"),
            sha256=sha256_of("new"),
            overwrite_mismatch=True,
        ),
        fs,
    ).assess_state()
    assert a.state is ExistingState.READY


def test_already_applied_when_sha_and_mode_match() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/a"), content="hello", mode=0o755)
    a = _build(
        DownloadFileParameters(
            url="http://x/a",
            dest=Path("/work/a"),
            sha256=sha256_of("hello"),
            mode=0o755,
        ),
        fs,
    ).assess_state()
    assert a.state is ExistingState.ALREADY_APPLIED


def test_ready_when_mode_differs() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/a"), content="hello", mode=0o644)
    a = _build(
        DownloadFileParameters(
            url="http://x/a",
            dest=Path("/work/a"),
            sha256=sha256_of("hello"),
            mode=0o755,
        ),
        fs,
    ).assess_state()
    assert a.state is ExistingState.READY
