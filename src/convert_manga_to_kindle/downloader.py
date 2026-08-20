"""Shared HTTP and image download helpers."""

from pathlib import Path
from typing import Final
from urllib.parse import urlparse

import requests

IMAGE_EXTENSIONS: Final[tuple[str, ...]] = (
    ".webp",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".jp2",
    ".avif",
)
HTTP_NOT_FOUND: Final[int] = 404

REQUEST_ERROR: Final[type[requests.RequestException]] = requests.RequestException


class DownloadError(RuntimeError):
    """Raised when a remote resource cannot be downloaded."""


def fetch(
    url: str,
    *,
    session: requests.Session,
    retries: int = 3,
    timeout: float = 15.0,
) -> requests.Response:
    """Fetch a URL with retries and timeout."""
    last_error: Exception | None = None
    for _ in range(retries):
        try:
            response = session.get(url, timeout=timeout)
            if response.ok or response.status_code == HTTP_NOT_FOUND:
                return response
            last_error = DownloadError(f"HTTP {response.status_code}: {url}")
        except REQUEST_ERROR as error:
            last_error = error
    e = f"Could not fetch {url}"
    raise DownloadError(e) from last_error


def fetch_binary(
    url: str,
    dest: Path,
    *,
    session: requests.Session,
    retries: int = 3,
    timeout: float = 15.0,
) -> Path:
    """Try supported suffixes and write the response using the matched suffix."""
    url_suffix = Path(urlparse(url).path).suffix.lower()
    candidates = (
        (url,)
        if url_suffix in IMAGE_EXTENSIONS
        else tuple(f"{url}{extension}" for extension in IMAGE_EXTENSIONS)
    )
    for candidate in candidates:
        response = fetch(candidate, session=session, retries=retries, timeout=timeout)
        if response.status_code == HTTP_NOT_FOUND:
            continue
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0]
        if not content_type.startswith("image/"):
            continue
        extension = Path(urlparse(candidate).path).suffix.lower()
        output = dest.with_suffix(extension)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(response.content)
        return output
    extensions = ", ".join(IMAGE_EXTENSIONS)
    message = f"No supported image found at {url}. Tried: {extensions}"
    raise DownloadError(message)
