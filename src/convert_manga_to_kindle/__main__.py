"""Command-line orchestration for manga download and KCC conversion."""

import argparse
import shutil
import sys
import typing
from decimal import Decimal, InvalidOperation
from pathlib import Path

from convert_manga_to_kindle.downloader import DownloadError
from convert_manga_to_kindle.kcc_bridge import (
    DEFAULT_KCC_C2E_PATH,
    SUPPORTED_FORMATS,
    SUPPORTED_PROFILES,
    KccConversionError,
    run_kcc,
    safe_name,
    validate_conversion_options,
)
from convert_manga_to_kindle.providers import get_provider
from convert_manga_to_kindle.providers.base import ProviderParseError

if typing.TYPE_CHECKING:
    from convert_manga_to_kindle.providers.base import Chapter


class CliArgs(argparse.Namespace):
    """Typed view of the parsed command line."""

    provider: str
    manga_id: str
    chapter: str | None
    chapters: tuple[str, str] | None
    all_chapters: bool
    output_dir: Path
    work_dir: Path | None
    keep_webp: bool
    profile: str
    format: str
    title: str | None
    author: str | None
    upscale: bool
    stretch: bool
    manga_style: bool
    kcc_path: Path


def _chapter_range(value: str) -> tuple[str, str]:
    start, separator, end = value.partition(":")
    if not separator or not start or not end:
        e = "chapter range must be START:END"
        raise argparse.ArgumentTypeError(e)
    return start, end


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Download manga and convert it with KCC."
    )
    parser.add_argument("--provider", required=True, choices=("scan-vf",))
    parser.add_argument("manga_id")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--chapter")
    selection.add_argument("--chapters", type=_chapter_range)
    selection.add_argument("--all", action="store_true", dest="all_chapters")
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument(
        "--keep-webp", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument(
        "--profile",
        default="KV",
        choices=SUPPORTED_PROFILES,
        metavar="PROFILE",
        help="KCC device profile (default: KV). One of: "
        + ", ".join(SUPPORTED_PROFILES),
    )
    parser.add_argument(
        "--format",
        default="EPUB-200MB",
        choices=SUPPORTED_FORMATS,
        metavar="FORMAT",
        help="KCC output format (default: EPUB, which Send to Kindle accepts). "
        "One of: " + ", ".join(SUPPORTED_FORMATS),
    )
    parser.add_argument("--title")
    parser.add_argument("--author")
    parser.add_argument(
        "--upscale",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Resize pages smaller than the profile resolution (default: on). "
        "KCC leaves them untouched with --no-upscale, so they render smaller "
        "than the page.",
    )
    parser.add_argument(
        "--stretch",
        action="store_true",
        help="Resize pages to the exact profile resolution, filling the screen "
        "at the cost of distortion when the aspect ratios differ.",
    )
    parser.add_argument(
        "--manga-style",
        action="store_true",
        help="Right-to-left reading order.",
    )
    parser.add_argument("--kcc-path", type=Path, default=DEFAULT_KCC_C2E_PATH)
    return parser


def _select_chapters(chapters: list[Chapter], args: CliArgs) -> list[Chapter]:
    if args.chapter is not None:
        return [chapter for chapter in chapters if chapter.number == args.chapter]
    if args.chapters is not None:
        start, end = args.chapters
        try:
            start_number = Decimal(start)
            end_number = Decimal(end)
            return [
                chapter
                for chapter in chapters
                if start_number <= Decimal(chapter.number) <= end_number
            ]
        except InvalidOperation:
            return [chapter for chapter in chapters if start <= chapter.number <= end]
    return chapters


_MAX_TITLE_BYTES = 80


def _chapter_dir_name(chapter: Chapter) -> str:
    number = safe_name(chapter.number, _MAX_TITLE_BYTES) or str(chapter.index)
    name = f"chapter {number}"
    title = safe_name(chapter.title, _MAX_TITLE_BYTES) if chapter.title else ""
    return f"{name} - {title}" if title else name


def main(argv: list[str] | None = None) -> int:
    """Entry point for the command-line interface."""
    args = build_parser().parse_args(argv, namespace=CliArgs())
    try:
        validate_conversion_options(args.profile, args.format)
        provider = get_provider(args.provider)
        chapters = _select_chapters(provider.list_chapters(args.manga_id), args)
        if not chapters:
            e = "No matching chapters found"
            raise ProviderParseError(e)

        output_dir = args.output_dir.resolve()
        work_dir = (args.work_dir or output_dir / "webp").resolve()
        manga_dir = work_dir / args.manga_id
        chapter_dirs: list[Path] = []
        for chapter in chapters:
            chapter_dir = manga_dir / _chapter_dir_name(chapter)
            provider.download_chapter(chapter, chapter_dir)
            chapter_dirs.append(chapter_dir)

        source = chapter_dirs[0] if len(chapter_dirs) == 1 else manga_dir
        book_files = run_kcc(
            source,
            output_dir,
            profile=args.profile,
            title=args.title,
            author=args.author,
            fmt=args.format,
            upscale=args.upscale,
            stretch=args.stretch,
            manga_style=args.manga_style,
            kcc_script=args.kcc_path,
        )
        for book_file in book_files:
            print(book_file)
        if not args.keep_webp:
            shutil.rmtree(manga_dir)
        return 0  # noqa: TRY300
    except (DownloadError, ProviderParseError, KccConversionError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
