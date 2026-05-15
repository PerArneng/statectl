from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, override

from statectl._interfaces.http import (
    HttpClient,
    HttpNotFound,
    HttpResponse,
)


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
    """

    _responses: dict[str, HttpResponse] = field(default_factory=dict)
    _downloads: dict[str, bytes] = field(default_factory=dict)
    _byte_responses: dict[str, bytes] = field(default_factory=dict)
    calls: list[RecordedHttpCall] = field(default_factory=list)

    def register_response(self, url: str, response: HttpResponse) -> None:
        self._responses[url] = response

    def register_download(self, url: str, body: bytes) -> None:
        self._downloads[url] = body

    def register_bytes(self, url: str, body: bytes) -> None:
        self._byte_responses[url] = body

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
        if url not in self._byte_responses:
            raise HttpNotFound(f"no scripted bytes response for {url}", url=url)
        return self._byte_responses[url]

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
        dest.write_bytes(self._downloads[url])
