from __future__ import annotations

from typing import override


class HttpError(Exception):
    def __init__(self, message: str, url: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.url = url

    @override
    def __str__(self) -> str:
        if self.url is not None:
            return f"{self.message}: {self.url}"
        return self.message


class HttpNetworkError(HttpError):
    pass


class HttpNotFound(HttpError):
    pass


class HttpServerError(HttpError):
    pass
