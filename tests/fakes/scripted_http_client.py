from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, override

from statectl._interfaces.http import (
    HttpClient,
    HttpNotFound,
    HttpResponse,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem


@dataclass(frozen=True)
class RecordedHttpCall:
    method: str
    url: str
    headers: Mapping[str, str] | None
    timeout: float | None
    dest: Path | None


@dataclass
class ScriptedHttpClient(HttpClient):
    """In-memory HttpClient. Register URL -> response (or URL -> raw bytes for
    downloads). Unregistered URLs raise HttpNotFound. Every call is recorded on
    `.calls` for assertions.

    If `file_system` is set, `download_to_file` writes the body into that
    in-memory FS (utf-8 decoded) rather than touching real disk.
    """

    _responses: dict[str, HttpResponse] = field(default_factory=dict)
    _bytes: dict[str, bytes] = field(default_factory=dict)
    _downloads: dict[str, bytes] = field(default_factory=dict)
    calls: list[RecordedHttpCall] = field(default_factory=list)
    file_system: InMemoryFileSystem | None = None

    def register_response(self, url: str, response: HttpResponse) -> None:
        self._responses[url] = response

    def register_bytes(self, url: str, body: bytes) -> None:
        self._bytes[url] = body

    def register_download(self, url: str, body: bytes) -> None:
        self._downloads[url] = body

    @override
    def get(
        self,
        url: str,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> HttpResponse:
        self.calls.append(
            RecordedHttpCall(method="get", url=url, headers=headers, timeout=timeout, dest=None)
        )
        if url not in self._responses:
            raise HttpNotFound(f"no scripted response for {url}", url=url)
        return self._responses[url]

    @override
    def get_bytes(
        self,
        url: str,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> bytes:
        self.calls.append(
            RecordedHttpCall(method="get_bytes", url=url, headers=headers, timeout=timeout, dest=None)
        )
        if url not in self._bytes:
            raise HttpNotFound(f"no scripted bytes for {url}", url=url)
        return self._bytes[url]

    @override
    def download_to_file(
        self,
        url: str,
        dest: Path,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> None:
        self.calls.append(
            RecordedHttpCall(method="download", url=url, headers=headers, timeout=timeout, dest=dest)
        )
        if url not in self._downloads:
            raise HttpNotFound(f"no scripted download for {url}", url=url)
        body = self._downloads[url]
        if self.file_system is not None:
            try:
                text = body.decode("utf-8")
            except UnicodeDecodeError as e:
                raise ValueError(
                    f"ScriptedHttpClient: registered body for {url} is not valid "
                    f"utf-8 ({e}); add_binary_file support is not yet wired through "
                    f"InMemoryFileSystem"
                ) from e
            self.file_system.add_file(dest, content=text)
        else:
            dest.write_bytes(body)
