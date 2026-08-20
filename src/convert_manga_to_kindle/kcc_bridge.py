"""Subprocess bridge for Kindle Comic Converter."""

import re
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_KCC_C2E_PATH = (
    Path(__file__).resolve().parents[2] / "libs" / "kcc" / "kcc-c2e.py"
)

# Device profiles KCC treats as Kindle devices.
KINDLE_PROFILES: tuple[str, ...] = (
    "K1",
    "K2",
    "KDX",
    "K34",
    "K57",
    "KPW",
    "KV",
    "KPW34",
    "K810",
    "KO",
    "K11",
    "KPW5",
    "KPW6",
    "KS1860",
    "KS1920",
    "KS1240",
    "KS1324",
    "KS",
    "KCS",
    "KS3",
    "KSCS",
)

# Kobo, reMarkable and generic profiles KCC accepts but cannot send to Kindle.
NON_KINDLE_PROFILES: tuple[str, ...] = (
    "KoMT",
    "KoG",
    "KoGHD",
    "KoA",
    "KoAHD",
    "KoAH2O",
    "KoAO",
    "KoN",
    "KoC",
    "KoCC",
    "KoL",
    "KoLC",
    "KoF",
    "KoS",
    "KoE",
    "Rmk1",
    "Rmk2",
    "RmkPP",
    "RmkPPMove",
    "OTHER",
)

SUPPORTED_PROFILES: tuple[str, ...] = KINDLE_PROFILES + NON_KINDLE_PROFILES

# Profiles KCC treats as reMarkable devices, needed to resolve ``Auto``.
REMARKABLE_PROFILES: frozenset[str] = frozenset({"Rmk1", "Rmk2", "RmkPP", "RmkPPMove"})

# The 200MB variants are absent from KCC's own ``--help`` but are accepted:
# they split the book to stay under the Send to Kindle upload limit.
SUPPORTED_FORMATS: tuple[str, ...] = (
    "Auto",
    "EPUB",
    "EPUB-200MB",
    "MOBI",
    "MOBI+EPUB",
    "MOBI+EPUB-200MB",
    "CBZ",
    "KFX",
    "PDF",
    "PDF-200MB",
)

# Formats KCC only builds for a Kindle profile.
KINDLE_ONLY_FORMATS = frozenset(
    {"MOBI", "MOBI+EPUB", "MOBI+EPUB-200MB", "KFX", "EPUB-200MB"}
)

# Formats built by KindleGen, which ships only inside Kindle Previewer.
KINDLEGEN_FORMATS = frozenset({"MOBI", "MOBI+EPUB", "MOBI+EPUB-200MB"})


def validate_conversion_options(profile: str, fmt: str) -> None:
    """Reject profile/format combinations KCC would refuse after downloading."""
    if profile not in SUPPORTED_PROFILES:
        message = (
            f"Unknown KCC profile {profile!r}. "
            f"Available profiles: {', '.join(SUPPORTED_PROFILES)}"
        )
        raise ValueError(message)
    if fmt not in SUPPORTED_FORMATS:
        message = (
            f"Unknown KCC format {fmt!r}. "
            f"Available formats: {', '.join(SUPPORTED_FORMATS)}"
        )
        raise ValueError(message)
    if fmt in KINDLE_ONLY_FORMATS and profile not in KINDLE_PROFILES:
        message = (
            f"Format {fmt} requires a Kindle profile, but {profile!r} is not one. "
            f"Kindle profiles: {', '.join(KINDLE_PROFILES)}"
        )
        raise ValueError(message)
    if fmt in KINDLEGEN_FORMATS and shutil.which("kindlegen") is None:
        message = (
            f"Format {fmt} needs kindlegen on PATH, and it was not found. "
            "Install Kindle Previewer and add its kindlegen to PATH, or use "
            "EPUB, which Send to Kindle accepts and needs no extra tool."
        )
        raise ValueError(message)


def _resolve_auto_format(profile: str) -> str:
    """Mirror KCC's own resolution of the ``Auto`` format."""
    if profile == "KDX":
        return "CBZ"
    if profile in KINDLE_PROFILES:
        return "MOBI"
    if profile in REMARKABLE_PROFILES:
        return "PDF"
    return "EPUB"


def output_extensions(profile: str, fmt: str) -> tuple[str, ...]:
    """Return the suffixes KCC writes for a ``profile``/``fmt`` pair."""
    if fmt == "Auto":
        fmt = _resolve_auto_format(profile)
    # KCC drops the size-limited suffix once it has set its split options.
    fmt = fmt.removesuffix("-200MB")
    if fmt == "CBZ":
        return (".cbz",)
    if fmt == "PDF":
        return (".pdf",)
    if fmt == "MOBI":
        return (".mobi",)
    if fmt == "MOBI+EPUB":
        return (".mobi", ".epub")
    # KFX is an EPUB tagged for the Calibre KFX Output plugin. Kobo profiles
    # turn EPUB output into KEPUB unless KCC is passed --nokepub.
    if "Ko" in profile:
        return (".kepub.epub",)
    return (".epub",)


# Characters Windows rejects in a file name, the POSIX set is a subset of it.
_FORBIDDEN_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Device names Windows reserves, whatever extension follows them.
_RESERVED_NAMES: frozenset[str] = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{digit}" for digit in "123456789"}
    | {f"LPT{digit}" for digit in "123456789"}
)

# Leave room for the extension and KCC's volume suffix under the 255-byte
_MAX_STEM_BYTES = 150


def safe_name(value: str, max_bytes: int = _MAX_STEM_BYTES) -> str:
    """Return ``value`` reduced to characters every filesystem accepts."""
    collapsed = " ".join(_FORBIDDEN_CHARACTERS.sub(" ", value).split())
    name = collapsed.encode("utf-8")[:max_bytes].decode("utf-8", "ignore")
    name = name.strip(". ")
    if name.split(".")[0].upper() in _RESERVED_NAMES:
        name = f"{name}_"
    return name


def safe_filename(title: str) -> str:
    """Return ``title`` as a file stem, rejecting one that sanitises to nothing."""
    stem = safe_name(title)
    if not stem:
        message = (
            f"Title {title!r} leaves no character usable in a file name. "
            "Keep at least one letter, digit or dash."
        )
        raise ValueError(message)
    return stem


def _unique_path(directory: Path, stem: str, extension: str) -> Path:
    """Pick a free name rather than overwrite a book from an earlier run."""
    candidate = directory / f"{stem}{extension}"
    counter = 2
    while candidate.exists():
        candidate = directory / f"{stem} ({counter}){extension}"
        counter += 1
    return candidate


def _retitle(
    path: Path, stem: str, source_name: str, extensions: tuple[str, ...]
) -> Path:
    """Rename one book KCC named after ``source_name`` to ``stem``."""
    # Longest first: ".kepub.epub" must win over the ".epub" it ends with.
    extension = next(
        (
            candidate
            for candidate in sorted(extensions, key=len, reverse=True)
            if path.name.endswith(candidate)
        ),
        None,
    )
    if extension is None:
        return path
    kcc_stem = path.name[: -len(extension)]
    # KCC splits oversized books into "<source> 1", "<source> 2": that suffix
    # is the only thing telling the volumes apart, so carry it over.
    volume = kcc_stem[len(source_name) :] if kcc_stem.startswith(source_name) else ""
    return path.rename(_unique_path(path.parent, f"{stem}{volume}", extension))


class KccConversionError(RuntimeError):
    """Raised when KCC fails to create a book."""

    def __init__(self, stdout: str, stderr: str, returncode: int) -> None:
        """Initialize the exception with KCC's output and exit code."""
        details = stderr.strip() or stdout.strip() or "KCC exited without details"
        super().__init__(f"KCC conversion failed ({returncode}): {details}")
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def run_kcc(  # noqa: PLR0913
    source: Path,
    output_dir: Path,
    *,
    profile: str = "KV",
    title: str | None = None,
    author: str | None = None,
    fmt: str = "EPUB",
    upscale: bool = True,
    stretch: bool = False,
    manga_style: bool = False,
    kcc_script: Path = DEFAULT_KCC_C2E_PATH,
) -> list[Path]:
    """Run KCC and return every book it generated in ``output_dir``."""
    validate_conversion_options(profile, fmt)
    # Reject an unusable title before spending the conversion on it.
    stem = safe_filename(title) if title else None
    output_dir.mkdir(parents=True, exist_ok=True)
    extensions = output_extensions(profile, fmt)
    existing = {path for suffix in extensions for path in output_dir.glob(f"*{suffix}")}
    argv = [
        sys.executable,
        str(kcc_script.resolve()),
        "-p",
        profile,
        "-f",
        fmt,
        "-o",
        str(output_dir.resolve()),
    ]
    # Without -u, KCC leaves pages smaller than the device untouched, so scans
    # below the profile resolution render at their own size on a larger page.
    if upscale:
        argv.append("-u")
    # -s wins over -u inside KCC: it resizes to the exact device resolution.
    if stretch:
        argv.append("-s")
    if manga_style:
        argv.append("-m")
    if title:
        argv.extend(("-t", title))
    if author:
        argv.extend(("-a", author))
    argv.append(str(source.resolve()))
    result = subprocess.run(argv, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        raise KccConversionError(result.stdout, result.stderr, result.returncode)
    # Diff against the snapshot: books left by earlier runs are not ours to
    # return, let alone to rename.
    produced = sorted(
        {path for suffix in extensions for path in output_dir.glob(f"*{suffix}")}
        - existing
    )
    if stem is None:
        return produced
    # KCC names the book after the source directory, the title the reader asked
    # for is the better name.
    return [_retitle(path, stem, source.name, extensions) for path in produced]
