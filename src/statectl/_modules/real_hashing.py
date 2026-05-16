from __future__ import annotations

import hashlib
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, override

from statectl._interfaces.hashing import (
    Hashing,
    HashingIoError,
    HashingNotFound,
)


_CHUNK: int = 65536


@contextmanager
def _translate(path: Path) -> Iterator[None]:
    try:
        yield
    except FileNotFoundError as e:
        raise HashingNotFound("file not found", path=path) from e
    except IsADirectoryError as e:
        raise HashingIoError("path is a directory", path=path) from e
    except PermissionError as e:
        raise HashingIoError(f"permission denied: {e}", path=path) from e
    except OSError as e:
        raise HashingIoError(f"io error: {e}", path=path) from e


class RealHashing(Hashing):
    @override
    def sha256_file(self, path: Path) -> str:
        h = hashlib.sha256()
        with _translate(path):
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(_CHUNK)
                    if not chunk:
                        break
                    h.update(chunk)
        return h.hexdigest()
