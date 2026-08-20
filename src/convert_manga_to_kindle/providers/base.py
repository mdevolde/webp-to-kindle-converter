"""Base classes and utilities for manga providers."""

import typing
from abc import ABC, abstractmethod
from dataclasses import dataclass

if typing.TYPE_CHECKING:
    from pathlib import Path


class ProviderParseError(RuntimeError):
    """Raised when a provider no longer matches the website markup."""


@dataclass(frozen=True, slots=True)
class Chapter:
    """A manga chapter with its metadata."""

    index: int
    number: str
    url: str
    title: str | None = None


class MangaProvider(ABC):
    """Abstract base class for manga providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the provider registry key."""

    @abstractmethod
    def list_chapters(self, manga_id: str) -> list[Chapter]:
        """Return available chapters in ascending order."""

    @abstractmethod
    def download_chapter(self, chapter: Chapter, dest_dir: Path) -> Path:
        """Download every page into ``dest_dir``."""
