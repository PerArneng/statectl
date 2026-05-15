from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import override

from statectl._interfaces.archive import (
    Archive,
    ArchiveCorrupt,
    ArchiveError,
    ArchiveFormat,
    ArchiveNotFound,
    ArchiveUnsafeEntry,
    ArchiveUnsupportedFormat,
)
from statectl._interfaces.fs import FileSystem, FsError
from statectl._modules import RealArchive, RealFileSystem
from statectl._state_changer import (
    ExistingState,
    Parameters,
    Result,
    StateAssessment,
    StateChanger,
)


@dataclass(frozen=True)
class ExtractArchiveParameters(Parameters):
    archive_path: Path
    dest_dir: Path
    format: ArchiveFormat
    sentinel_path: Path
    create_dest: bool = True
    strip_components: int = 0


class ExtractArchiveStateChanger(StateChanger):
    def __init__(
        self,
        params: ExtractArchiveParameters,
        file_system: FileSystem | None = None,
        archive: Archive | None = None,
    ) -> None:
        self._params = params
        self._fs: FileSystem = file_system or RealFileSystem()
        self._archive: Archive = archive or RealArchive()

    @property
    def params(self) -> ExtractArchiveParameters:
        return self._params

    @override
    def name(self) -> str:
        return f"extract-archive:{self._params.archive_path}->{self._params.dest_dir}"

    @override
    def assess_state(self) -> StateAssessment:
        params = self._params
        issues: list[str] = []

        if params.strip_components < 0:
            issues.append(
                f"strip_components must be >= 0, got {params.strip_components}"
            )

        archive_exists = self._fs.exists(params.archive_path)
        if not archive_exists:
            issues.append(f"archive does not exist: {params.archive_path}")
        elif not self._fs.is_file(params.archive_path):
            issues.append(
                f"archive is not a regular file: {params.archive_path}"
            )

        dest_exists = self._fs.exists(params.dest_dir)
        if dest_exists:
            if not self._fs.is_dir(params.dest_dir):
                issues.append(
                    f"dest_dir exists but is not a directory: {params.dest_dir}"
                )
            elif not self._fs.is_writable(params.dest_dir):
                issues.append(f"dest_dir is not writable: {params.dest_dir}")
        else:
            if not params.create_dest:
                issues.append(
                    f"dest_dir does not exist and create_dest=False: {params.dest_dir}"
                )

        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot extract {params.archive_path}",
                issues=issues,
            )

        if self._fs.exists(params.sentinel_path):
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=(
                    f"sentinel already present: {params.sentinel_path}"
                ),
            )

        return StateAssessment(
            state=ExistingState.READY,
            description=(
                f"ready to extract {params.archive_path} to {params.dest_dir}"
            ),
        )

    @override
    def transition(self) -> Result:
        params = self._params
        if params.create_dest and not self._fs.exists(params.dest_dir):
            try:
                self._fs.create_folder(params.dest_dir, parents=True, exist_ok=True)
            except FsError as e:
                return Result.failure(
                    "MKDIR_FAILED",
                    f"failed to create dest_dir {params.dest_dir}: {e}",
                )

        try:
            self._archive.extract(
                params.archive_path,
                params.dest_dir,
                params.format,
                params.strip_components,
            )
        except ArchiveNotFound as e:
            return Result.failure("ARCHIVE_VANISHED", str(e))
        except ArchiveCorrupt as e:
            return Result.failure("ARCHIVE_MALFORMED", str(e))
        except ArchiveUnsafeEntry as e:
            return Result.failure("EXTRACT_FAILED", str(e))
        except ArchiveUnsupportedFormat as e:
            return Result.failure("EXTRACT_FAILED", str(e))
        except ArchiveError as e:
            return Result.failure("EXTRACT_FAILED", str(e))

        return Result.success(
            f"extracted {params.archive_path} to {params.dest_dir}"
        )
