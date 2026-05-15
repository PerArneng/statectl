from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import override

from statectl._interfaces.env import Env, Platform


@dataclass
class ScriptedEnv(Env):
    """In-memory Env. Configure variables, home directory, and platform up
    front; methods return scripted values.
    """

    variables: dict[str, str] = field(default_factory=dict)
    home: Path = Path("/home/test")
    _platform: Platform = "linux"

    @classmethod
    def darwin(cls, home: Path | None = None, variables: dict[str, str] | None = None) -> ScriptedEnv:
        return cls(
            variables=variables or {},
            home=home or Path("/Users/test"),
            _platform="darwin",
        )

    @classmethod
    def linux(cls, home: Path | None = None, variables: dict[str, str] | None = None) -> ScriptedEnv:
        return cls(
            variables=variables or {},
            home=home or Path("/home/test"),
            _platform="linux",
        )

    @override
    def get(self, name: str) -> str | None:
        return self.variables.get(name)

    @override
    def user_home(self) -> Path:
        return self.home

    @override
    def platform(self) -> Platform:
        return self._platform
