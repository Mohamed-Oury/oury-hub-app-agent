"""Versions des analyses : un fichier JSON par besoin."""

from pathlib import Path

from pydantic import TypeAdapter

from agentic.schemas.analysis import AnalysisVersion

_versions = TypeAdapter(list[AnalysisVersion])


def _path(name: str, directory: Path) -> Path:
    return directory / f"{name}.json"


def load_versions(name: str, directory: Path) -> list[AnalysisVersion]:
    path = _path(name, directory)
    if not path.exists():
        return []
    return _versions.validate_json(path.read_text(encoding="utf-8"))


def save_versions(name: str, versions: list[AnalysisVersion], directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    payload = _versions.dump_json(versions, by_alias=True, indent=2)
    _path(name, directory).write_bytes(payload)
