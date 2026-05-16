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


def test_unsupported_scheme_is_invalid() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    a = _build(
        DownloadFileParameters(url="ftp://x/a", dest=Path("/work/a")),
        fs,
    ).assess_state()
    assert a.state is ExistingState.INVALID
    assert any("unsupported scheme" in i for i in a.issues)


def test_malformed_sha256_is_invalid() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    a = _build(
        DownloadFileParameters(
            url="http://x/a", dest=Path("/work/a"), sha256="not-a-hash"
        ),
        fs,
    ).assess_state()
    assert a.state is ExistingState.INVALID
    assert any("malformed sha256" in i for i in a.issues)


def test_missing_parent_directory_is_invalid() -> None:
    fs = InMemoryFileSystem()
    a = _build(
        DownloadFileParameters(url="http://x/a", dest=Path("/work/a")),
        fs,
    ).assess_state()
    assert a.state is ExistingState.INVALID
    assert any("parent directory does not exist" in i for i in a.issues)


def test_parent_not_writable_is_invalid() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"), writable=False)
    a = _build(
        DownloadFileParameters(url="http://x/a", dest=Path("/work/a")),
        fs,
    ).assess_state()
    assert a.state is ExistingState.INVALID
    assert any("not writable" in i for i in a.issues)


def test_dest_exists_as_directory_is_invalid() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(Path("/work/a"))
    a = _build(
        DownloadFileParameters(url="http://x/a", dest=Path("/work/a")),
        fs,
    ).assess_state()
    assert a.state is ExistingState.INVALID
    assert any("not a regular file" in i for i in a.issues)


def test_dest_exists_with_wrong_sha_and_overwrite_disabled_is_invalid() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/a"), content="existing")
    expected = sha256_of("intended")
    a = _build(
        DownloadFileParameters(
            url="http://x/a",
            dest=Path("/work/a"),
            sha256=expected,
            overwrite_mismatch=False,
        ),
        fs,
    ).assess_state()
    assert a.state is ExistingState.INVALID
    assert any("dest exists with sha256" in i for i in a.issues)


def test_collects_all_issues_in_one_pass() -> None:
    fs = InMemoryFileSystem()
    a = _build(
        DownloadFileParameters(
            url="ftp://x/a",
            dest=Path("/work/a"),
            sha256="zz",
        ),
        fs,
    ).assess_state()
    assert a.state is ExistingState.INVALID
    assert len(a.issues) >= 3
