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
)
from statectl._interfaces.fs import FileSystem, FsError
from statectl._modules import RealArchive, RealFileSystem
from statectl._state_changer import (
    ExistingState,
    Parameters,
    Result,
    ResultStatus,
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
        issues.extend(self._param_issues())
        issues.extend(self._archive_issues())
        issues.extend(self._dest_issues())

        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot extract {params.archive_path} -> {params.dest_dir}",
                issues=issues,
            )

        if self._fs.exists(params.sentinel_path):
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=f"sentinel exists: {params.sentinel_path}",
            )

        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to extract {params.archive_path} -> {params.dest_dir}",
        )

    def _param_issues(self) -> list[str]:
        params = self._params
        if params.strip_components < 0:
            return [
                f"strip_components must be >= 0, got {params.strip_components}"
            ]
        return []

    def _archive_issues(self) -> list[str]:
        archive_path = self._params.archive_path
        if not self._fs.exists(archive_path):
            return [f"archive does not exist: {archive_path}"]
        if not self._fs.is_file(archive_path):
            return [f"archive is not a regular file: {archive_path}"]
        return []

    def _dest_issues(self) -> list[str]:
        dest_dir = self._params.dest_dir
        if self._fs.exists(dest_dir):
            if not self._fs.is_dir(dest_dir):
                return [f"dest_dir exists and is not a directory: {dest_dir}"]
            if not self._fs.is_writable(dest_dir):
                return [f"dest_dir is not writable: {dest_dir}"]
            return []
        if not self._params.create_dest:
            return [f"dest_dir does not exist and create_dest=False: {dest_dir}"]
        return self._dest_parent_issues(dest_dir.parent)

    def _dest_parent_issues(self, parent: Path) -> list[str]:
        if not self._fs.exists(parent):
            return [f"dest_dir parent does not exist: {parent}"]
        if not self._fs.is_dir(parent):
            return [f"dest_dir parent is not a directory: {parent}"]
        if not self._fs.is_writable(parent):
            return [f"dest_dir parent is not writable: {parent}"]
        return []

    @override
    def transition(self) -> Result:
        params = self._params
        if params.create_dest and not self._fs.exists(params.dest_dir):
            try:
                self._fs.create_folder(
                    params.dest_dir, parents=True, exist_ok=True
                )
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
        except ArchiveNotFound:
            return Result.failure(
                "ARCHIVE_VANISHED",
                f"archive vanished between assess and extract: {params.archive_path}",
            )
        except ArchiveCorrupt as e:
            return Result.failure(
                "ARCHIVE_MALFORMED",
                f"archive is malformed: {e}",
            )
        except ArchiveError as e:
            return Result.failure(
                "EXTRACT_FAILED",
                f"failed to extract {params.archive_path} -> {params.dest_dir}: {e}",
            )

        details: dict[str, str] = {
            "archive_path": str(params.archive_path),
            "dest_dir": str(params.dest_dir),
            "format": params.format.value,
            "strip_components": str(params.strip_components),
        }
        return Result(
            status=ResultStatus.SUCCESS,
            code="OK",
            message=f"extracted {params.archive_path} -> {params.dest_dir}",
            details=details,
        )
