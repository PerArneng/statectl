from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from statectl._interfaces.fs import FsIoError
from statectl._interfaces.hashing import HashingIoError
from statectl._interfaces.http import (
    HttpError,
    HttpNetworkError,
    HttpNotFound,
    HttpServerError,
)
from statectl._state_changer import ResultStatus
from statectl._statechangers import (
    DownloadFileParameters,
    DownloadFileStateChanger,
)
from tests.fakes.failing_file_system import FailingFileSystem
from tests.fakes.failing_hashing import FailingHashing
from tests.fakes.failing_http_client import FailingHttpClient
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_hashing import ScriptedHashing
from tests.fakes.scripted_http_client import ScriptedHttpClient


@pytest.mark.parametrize(
    "error,code",
    [
        (HttpNotFound("nope", url="http://x/a"), "HTTP_NOT_FOUND"),
        (HttpServerError("5xx", url="http://x/a"), "HTTP_SERVER_ERROR"),
        (HttpNetworkError("net", url="http://x/a"), "HTTP_NETWORK_ERROR"),
    ],
    ids=["not_found", "server_error", "network_error"],
)
def test_http_error_matrix(error: HttpError, code: str) -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    inner_http = ScriptedHttpClient(file_system=fs)
    inner_http.register_download("http://x/a", b"hi")
    http = FailingHttpClient(inner_http)
    http.fail("download_to_file", error)
    changer = DownloadFileStateChanger(
        DownloadFileParameters(url="http://x/a", dest=Path("/work/a")),
        file_system=fs,
        http_client=http,
        hashing=ScriptedHashing(file_system=fs),
    )

    result = changer.transition()
    assert result.status is ResultStatus.FAILURE
    assert result.code == code


def test_unexpected_http_exception_propagates() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    inner = ScriptedHttpClient(file_system=fs)
    inner.register_download("http://x/a", b"hi")
    http = FailingHttpClient(inner)
    http.fail("download_to_file", RuntimeError("boom"))
    changer = DownloadFileStateChanger(
        DownloadFileParameters(url="http://x/a", dest=Path("/work/a")),
        file_system=fs,
        http_client=http,
        hashing=ScriptedHashing(file_system=fs),
    )
    with pytest.raises(RuntimeError, match="boom"):
        changer.transition()


def test_hashing_failure_returns_hash_failed() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    http = ScriptedHttpClient(file_system=fs)
    http.register_download("http://x/a", b"hi")
    hashing = FailingHashing(ScriptedHashing(file_system=fs))
    hashing.fail(HashingIoError("read failed", path=Path("/work/a")))
    changer = DownloadFileStateChanger(
        DownloadFileParameters(url="http://x/a", dest=Path("/work/a")),
        file_system=fs,
        http_client=http,
        hashing=hashing,
    )

    result = changer.transition()
    assert result.status is ResultStatus.FAILURE
    assert result.code == "HASH_FAILED"


def test_chmod_failure_returns_chmod_failed() -> None:
    inner_fs = InMemoryFileSystem()
    inner_fs.add_dir(Path("/work"))
    fs = FailingFileSystem(inner_fs)
    http = ScriptedHttpClient(file_system=inner_fs)
    http.register_download("http://x/a", b"hi")
    fs.fail(
        "chmod",
        FsIoError("denied", path=Path("/work/a")),
        path=Path("/work/a"),
    )
    changer = DownloadFileStateChanger(
        DownloadFileParameters(
            url="http://x/a", dest=Path("/work/a"), mode=0o600
        ),
        file_system=fs,
        http_client=http,
        hashing=ScriptedHashing(file_system=inner_fs),
    )

    result = changer.transition()
    assert result.status is ResultStatus.FAILURE
    assert result.code == "CHMOD_FAILED"


def _noop_factory() -> Callable[[], None]:
    return lambda: None
