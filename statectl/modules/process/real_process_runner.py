from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from typing import Mapping, Sequence, override

from statectl.interfaces.process.error.process_decode_error import ProcessDecodeError
from statectl.interfaces.process.error.process_launch_error import ProcessLaunchError
from statectl.interfaces.process.error.process_not_found import ProcessNotFound
from statectl.interfaces.process.error.process_timeout import ProcessTimeout
from statectl.interfaces.process.process_result import ProcessResult
from statectl.interfaces.process.process_runner import ProcessRunner


class RealProcessRunner(ProcessRunner):
    @override
    def which(self, name: str) -> Path | None:
        found = shutil.which(name)
        return Path(found) if found is not None else None

    @override
    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | None = None,
        timeout: float | None = None,
    ) -> ProcessResult:
        argv_tuple = tuple(argv)
        start = time.monotonic()
        try:
            completed = subprocess.run(
                list(argv_tuple),
                cwd=cwd,
                env=dict(env) if env is not None else None,
                input=stdin,
                timeout=timeout,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as e:
            raise ProcessNotFound(f"executable not found: {e}", argv=argv_tuple) from e
        except subprocess.TimeoutExpired as e:
            raise ProcessTimeout(
                f"process exceeded timeout of {timeout}s", argv=argv_tuple
            ) from e
        except UnicodeDecodeError as e:
            raise ProcessDecodeError(
                f"could not decode process output: {e}", argv=argv_tuple
            ) from e
        except PermissionError as e:
            raise ProcessLaunchError(
                f"permission denied launching process: {e}", argv=argv_tuple
            ) from e
        except OSError as e:
            raise ProcessLaunchError(
                f"os error launching process: {e}", argv=argv_tuple
            ) from e
        duration_ms = int((time.monotonic() - start) * 1000)
        return ProcessResult(
            exit_code=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            duration_ms=duration_ms,
        )
