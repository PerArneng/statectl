from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import override

from statectl._interfaces.env import Env, Platform


class RealEnv(Env):
    @override
    def get(self, name: str) -> str | None:
        return os.environ.get(name)

    @override
    def user_home(self) -> Path:
        return Path.home()

    @override
    def platform(self) -> Platform:
        if sys.platform == "darwin":
            return "darwin"
        return "linux"
