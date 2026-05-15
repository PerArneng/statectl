from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    body: str
    headers: Mapping[str, str]


class HttpClient(ABC):
    """HTTP client abstraction. Action methods (`get`, `download_to_file`)
    raise HttpError subclasses on failure. The real implementation wraps
    stdlib `urllib` to avoid a third-party dependency.

    Implementations must translate underlying errors into:
      - HttpNotFound       404 responses
      - HttpServerError    5xx responses
      - HttpNetworkError   connection failures, DNS, TLS, timeouts, other I/O
    """

    @abstractmethod
    def get(
        self,
        url: str,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> HttpResponse: ...

    @abstractmethod
    def download_to_file(
        self,
        url: str,
        dest: Path,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> None: ...
