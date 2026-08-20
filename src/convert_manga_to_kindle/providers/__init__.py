"""Providers for manga sources."""

import typing

from convert_manga_to_kindle.providers.scan_vf import ScanVfProvider

if typing.TYPE_CHECKING:
    from convert_manga_to_kindle.providers.base import MangaProvider

PROVIDERS: dict[str, type[MangaProvider]] = {"scan-vf": ScanVfProvider}


def get_provider(name: str) -> MangaProvider:
    """Return a provider instance by name."""
    try:
        return PROVIDERS[name]()
    except KeyError as error:
        available = ", ".join(sorted(PROVIDERS))
        e = f"Unknown provider {name!r}; available: {available}"
        raise ValueError(e) from error
