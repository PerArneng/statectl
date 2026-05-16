from __future__ import annotations

from pathlib import Path

from statectl._state_changer import ResultStatus
from statectl._statechangers import (
    DownloadFileParameters,
    DownloadFileStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_hashing import ScriptedHashing, sha256_of
from tests.fakes.scripted_http_client import ScriptedHttpClient


def test_downloads_and_writes_dest() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    http = ScriptedHttpClient(file_system=fs)
    http.register_download("http://x/a", b"hello")
    hashing = ScriptedHashing(file_system=fs)
    changer = DownloadFileStateChanger(
        DownloadFileParameters(url="http://x/a", dest=Path("/work/a")),
        file_system=fs,
        http_client=http,
        hashing=hashing,
    )

    result = changer.transition()

    assert result.status is ResultStatus.SUCCESS
    assert fs.read_text_file(Path("/work/a")) == "hello"
    assert http.calls[0].method == "download"


def test_checksum_match_succeeds_and_applies_mode() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    http = ScriptedHttpClient(file_system=fs)
    http.register_download("http://x/a", b"payload")
    expected = sha256_of("payload")
    changer = DownloadFileStateChanger(
        DownloadFileParameters(
            url="http://x/a",
            dest=Path("/work/a"),
            sha256=expected,
            mode=0o600,
        ),
        file_system=fs,
        http_client=http,
        hashing=ScriptedHashing(file_system=fs),
    )

    result = changer.transition()

    assert result.status is ResultStatus.SUCCESS
    assert fs.stat_mode(Path("/work/a")) == 0o600


def test_checksum_mismatch_removes_file_and_fails() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    http = ScriptedHttpClient(file_system=fs)
    http.register_download("http://x/a", b"actual")
    changer = DownloadFileStateChanger(
        DownloadFileParameters(
            url="http://x/a",
            dest=Path("/work/a"),
            sha256=sha256_of("expected"),
            overwrite_mismatch=True,
        ),
        file_system=fs,
        http_client=http,
        hashing=ScriptedHashing(file_system=fs),
    )

    result = changer.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "CHECKSUM_MISMATCH"
    assert not fs.exists(Path("/work/a"))
