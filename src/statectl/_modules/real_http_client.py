from __future__ import annotations

import shutil
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Mapping, override

from statectl._interfaces.http import (
    HttpClient,
    HttpNetworkError,
    HttpNotFound,
    HttpResponse,
    HttpServerError,
)


@contextmanager
def _translate(url: str) -> Iterator[None]:
    try:
        yield
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise HttpNotFound(f"http 404: {e.reason}", url=url) from e
        if 500 <= e.code < 600:
            raise HttpServerError(f"http {e.code}: {e.reason}", url=url) from e
        raise HttpNetworkError(f"http {e.code}: {e.reason}", url=url) from e
    except urllib.error.URLError as e:
        raise HttpNetworkError(f"url error: {e.reason}", url=url) from e
    except TimeoutError as e:
        raise HttpNetworkError(f"timeout: {e}", url=url) from e
    except OSError as e:
        raise HttpNetworkError(f"io error: {e}", url=url) from e


class RealHttpClient(HttpClient):
    @override
    def get(
        self,
        url: str,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> HttpResponse:
        request = urllib.request.Request(url, headers=dict(headers) if headers else {})
        with _translate(url):
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                raw = resp.read()
                charset = resp.headers.get_content_charset() or "utf-8"
                body = raw.decode(charset, errors="replace")
                resp_headers = {k: v for k, v in resp.headers.items()}
                return HttpResponse(
                    status_code=resp.status,
                    body=body,
                    headers=resp_headers,
                )

    @override
    def download_to_file(
        self,
        url: str,
        dest: Path,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> None:
        request = urllib.request.Request(url, headers=dict(headers) if headers else {})
        with _translate(url):
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                with open(dest, "wb") as out:
                    shutil.copyfileobj(resp, out)
