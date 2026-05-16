from __future__ import annotations

from pathlib import Path

import pytest

from statectl._interfaces.fs import FsIoError
from statectl._interfaces.http import (
    HttpError,
    HttpNetworkError,
    HttpNotFound,
    HttpServerError,
)
from statectl._state_changer import ResultStatus
from statectl._statechangers import (
    FetchUrlToStringParameters,
    FetchUrlToStringStateChanger,
)
from tests.fakes.failing_file_system import FailingFileSystem
from tests.fakes.failing_http_client import FailingHttpClient
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_clock import ScriptedClock
from tests.fakes.scripted_http_client import ScriptedHttpClient


URL = "https://example.com/x"
CACHE = Path("/work/x.txt")


def _changer(
    fs: InMemoryFileSystem | FailingFileSystem,
    http: ScriptedHttpClient | FailingHttpClient,
    encoding: str = "utf-8",
) -> FetchUrlToStringStateChanger:
    return FetchUrlToStringStateChanger(
        FetchUrlToStringParameters(
            url=URL, cache_path=CACHE, encoding=encoding
        ),
        file_system=fs,
        http_client=http,
        clock=ScriptedClock(),
    )


def test_transition_fetches_bytes_and_writes_cache_file() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    http = ScriptedHttpClient()
    http.register_bytes(URL, b"hello world")

    result = _changer(fs, http).transition()

    assert result.status is ResultStatus.SUCCESS
    assert fs.is_file(CACHE)
    assert fs.read_text_file(CACHE) == "hello world"
    assert [c.method for c in http.calls] == ["get_bytes"]
    assert http.calls[0].url == URL


def test_transition_decode_failure_returns_decode_failed() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    http = ScriptedHttpClient()
    # latin-1 byte 0xFF is not valid utf-8
    http.register_bytes(URL, b"\xff\xfe")

    result = _changer(fs, http, encoding="utf-8").transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "DECODE_FAILED"
    assert not fs.exists(CACHE)


def test_transition_unknown_encoding_returns_decode_failed() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    http = ScriptedHttpClient()
    http.register_bytes(URL, b"hello")

    result = _changer(fs, http, encoding="not-a-real-encoding").transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "DECODE_FAILED"
    assert not fs.exists(CACHE)


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (HttpNotFound("404", url=URL), "HTTP_NOT_FOUND"),
        (HttpServerError("503", url=URL), "HTTP_SERVER_ERROR"),
        (HttpNetworkError("conn refused", url=URL), "HTTP_NETWORK_ERROR"),
        (HttpError("unclassified", url=URL), "HTTP_ERROR"),
    ],
    ids=["not_found", "server_error", "network_error", "generic_http"],
)
def test_transition_maps_each_http_error_to_specific_failure_code(
    error: HttpError, expected_code: str
) -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    inner_http = ScriptedHttpClient()
    inner_http.register_bytes(URL, b"unused")
    http = FailingHttpClient(inner_http)
    http.fail("get_bytes", error)

    result = _changer(fs, http).transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == expected_code
    assert not fs.exists(CACHE)


def test_transition_write_failure_returns_write_failed() -> None:
    inner = InMemoryFileSystem()
    inner.add_dir(Path("/work"))
    fs = FailingFileSystem(inner)
    fs.fail("write_binary_file", FsIoError("disk full", path=CACHE), path=CACHE)
    http = ScriptedHttpClient()
    http.register_bytes(URL, b"hello")

    result = _changer(fs, http).transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "WRITE_FAILED"
    assert "disk full" in (result.message or "")


def test_transition_does_not_catch_unexpected_exceptions() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    inner_http = ScriptedHttpClient()
    inner_http.register_bytes(URL, b"unused")
    http = FailingHttpClient(inner_http)
    http.fail("get_bytes", RuntimeError("unexpected"))

    with pytest.raises(RuntimeError, match="unexpected"):
        _changer(fs, http).transition()


def test_transition_threads_headers_to_http_client() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    http = ScriptedHttpClient()
    http.register_bytes(URL, b"hello")
    changer = FetchUrlToStringStateChanger(
        FetchUrlToStringParameters(
            url=URL,
            cache_path=CACHE,
            headers={"Authorization": "Bearer x"},
        ),
        file_system=fs,
        http_client=http,
        clock=ScriptedClock(),
    )

    changer.transition()

    assert http.calls[0].headers == {"Authorization": "Bearer x"}
