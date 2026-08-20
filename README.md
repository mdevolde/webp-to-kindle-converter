# webp-to-kindle-converter

Download manga chapters from supported providers and convert them with Kindle compatible formats.

## Disclaimer

This project is a personal learning exercise about HTTP scraping, image
processing and e-reader formats. It hosts no content, mirrors nothing, and
breaks no protection: it only assembles pages that a third-party site already
serves publicly, and none of those providers are affiliated with or endorsed by
the rights holders.

Use it only for chapters you are entitled to read where you live, public
domain works, officially free chapters, or scans of volumes you own. Downloading
copyrighted manga from unauthorised sites is illegal in most countries, and this
tool is not a licence to do so. If you enjoy a series, buy the volumes or read it
on an official platform.

## Prerequisites

```text
git submodule update --init --recursive
uv sync
```

Output defaults to `EPUB-200MB`, which needs no extra tooling and is the format
Send to Kindle accepts (Amazon converts it to KFX on delivery).
This default splits the EPUB into multiple files if it exceeds 200MB, which is the maximum size Send to Kindle accepts.

## Filling the page

Pages smaller than the device resolution are upscaled by default (KCC's `-u`).
Pass `--no-upscale` to keep KCC's own default of leaving them alone, which
renders them smaller than the page. Scans whose aspect ratio differs from the
device still keep white bands on the sides, because KCC preserves the
proportions: `--stretch` trades that for a distorted, fully filled page.

`--manga-style` sets right-to-left reading order.

Provider URLs do not need an image extension. The downloader tries extensions
supported by KCC and stores pages with a recognized suffix.

Example:

```bash
convert_manga_to_kindle --provider scan-vf --chapters 1:10 --title "One Piece, 1-10" --author "Eiichiro Oda" --profile KPW5 --format EPUB-200MB one_piece
```
