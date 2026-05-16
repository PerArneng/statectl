from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import override

from statectl._interfaces.hashing import Hashing, HashingNotFound
from tests.fakes.in_memory_file_system import InMemoryFileSystem


@dataclass
class ScriptedHashing(Hashing):
    """In-memory Hashing fake. Computes sha256 over the utf-8 bytes of the
    text stored in the in-memory FS — sufficient because test downloads are
    registered as bytes that decode cleanly as utf-8.

    Optional `overrides` map a path to an explicit digest, useful for
    simulating mismatch scenarios without round-tripping a different body.
    """

    file_system: InMemoryFileSystem
    overrides: dict[Path, str] = field(default_factory=dict)
    calls: list[Path] = field(default_factory=list)

    @override
    def sha256_file(self, path: Path) -> str:
        self.calls.append(path)
        if path in self.overrides:
            return self.overrides[path]
        if not self.file_system.exists(path):
            raise HashingNotFound("file not found", path=path)
        content = self.file_system.read_text_file(path)
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
