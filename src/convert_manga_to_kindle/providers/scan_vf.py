"""Provider and utilities for scan-vf.net."""

import typing
from dataclasses import replace
from itertools import groupby
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

from convert_manga_to_kindle.downloader import fetch, fetch_binary
from convert_manga_to_kindle.providers.base import (
    Chapter,
    MangaProvider,
    ProviderParseError,
)

if typing.TYPE_CHECKING:
    from pathlib import Path


def _attribute(tag: Tag, name: str) -> str:
    value = tag.get(name)
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return " ".join(value)


def _chapter_title(link: Tag) -> str | None:
    emphasis = link.find_next_sibling("em")
    if emphasis is None:
        return None
    return emphasis.get_text(" ", strip=True) or None


def _chapter_sort_key(number: str) -> tuple[tuple[int | str, ...], str]:
    parts = tuple(
        int(run) if digits else run
        for digits, characters in groupby(number, str.isdigit)
        if (run := "".join(characters))
    )
    return parts, number


def _page_numbers(soup: BeautifulSoup) -> list[str]:
    return [
        value
        for option in soup.select("select#page-list option[value]")
        if (value := _attribute(option, "value").strip())
    ]


def _image_source(image: Tag) -> str | None:
    for attribute in ("data-src", "src"):
        source = _attribute(image, attribute).strip()
        if source and not source.startswith("data:"):
            return source
    return None


def _scan_page_image(soup: BeautifulSoup, base_url: str) -> str:
    image = soup.select_one("img.scan-page")
    source = _image_source(image) if image is not None else None
    if not source:
        e = (
            f"scan-vf: no image source found "
            f"on {base_url},site structure may have changed"
        )
        raise ProviderParseError(e)
    return urljoin(base_url, source)


class ScanVfProvider(MangaProvider):
    """Provider for scan-vf.net."""

    BASE_URL = "https://www.scan-vf.net"

    @property
    def name(self) -> str:
        """Return the provider registry key."""
        return "scan-vf"

    def __init__(self, session: requests.Session | None = None) -> None:
        """Initialize the provider with an optional requests session."""
        self.session = session or requests.Session()

    def list_chapters(self, manga_id: str) -> list[Chapter]:
        """Return available chapters in ascending order."""
        response = fetch(f"{self.BASE_URL}/{manga_id}", session=self.session)
        return self.parse_chapters(response.text, manga_id)

    @classmethod
    def parse_chapters(cls, html: str, manga_id: str) -> list[Chapter]:
        """Parse the chapter list from HTML and return them in ascending order."""
        soup = BeautifulSoup(html, "html.parser")
        by_number: dict[str, Chapter] = {}
        for link in soup.select("a[href]"):
            href = _attribute(link, "href")
            if "chapitre-" not in href:
                continue
            number = href.split("chapitre-", 1)[1].split("/", 1)[0]
            if not number or number in by_number:
                continue
            by_number[number] = Chapter(
                index=0,
                number=number,
                url=urljoin(f"{cls.BASE_URL}/{manga_id}", href),
                title=_chapter_title(link),
            )
        chapters = list(by_number.values())
        if not chapters:
            e = (
                f"scan-vf: no chapters found for {manga_id}, "
                f"site structure may have changed"
            )
            raise ProviderParseError(e)
        chapters.sort(key=lambda chapter: _chapter_sort_key(chapter.number))
        return [
            replace(chapter, index=index)
            for index, chapter in enumerate(chapters, start=1)
        ]

    def download_chapter(self, chapter: Chapter, dest_dir: Path) -> Path:
        """Download every page into ``dest_dir``."""
        response = fetch(chapter.url, session=self.session)
        soup = BeautifulSoup(response.text, "html.parser")
        for page, image_url in enumerate(self._page_images(soup, chapter), start=1):
            fetch_binary(image_url, dest_dir / f"{page:03d}", session=self.session)
        return dest_dir

    def _page_images(self, soup: BeautifulSoup, chapter: Chapter) -> list[str]:
        image_urls = [_scan_page_image(soup, chapter.url)]
        base_url = chapter.url.rstrip("/")
        for page in _page_numbers(soup)[1:]:
            page_url = f"{base_url}/{page}"
            page_soup = BeautifulSoup(
                fetch(page_url, session=self.session).text, "html.parser"
            )
            image_urls.append(_scan_page_image(page_soup, page_url))
        return image_urls
