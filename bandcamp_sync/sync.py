"""One sync run: decide what's new, download it, record it."""

from __future__ import annotations

import os
import re
import shutil
import string
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import requests

from .client import BandcampError, Client, Purchase
from .state import State, state_key

FORMATS = ["flac", "mp3-320", "mp3-v0", "aac-hi", "vorbis", "alac", "wav", "aiff-lossless"]
EXTENSIONS = {
    "flac": ".flac",
    "mp3-320": ".mp3",
    "mp3-v0": ".mp3",
    "aac-hi": ".m4a",
    "vorbis": ".ogg",
    "alac": ".m4a",
    "wav": ".wav",
    "aiff-lossless": ".aiff",
}
PLACEHOLDERS = {"artist", "title", "type", "format", "id"}
DEFAULT_TEMPLATE = "{artist}/{title}"

# Seconds between two downloads, to stay gentle with Bandcamp.
PAUSE = 1.0

_UNSAFE = re.compile(r'[/\\<>:"|?*\x00-\x1f]')
_RESERVED = re.compile(r"^(con|prn|aux|nul|com\d|lpt\d)(\..*)?$", re.I)


class TemplateError(ValueError):
    pass


class _Exists(Exception):
    def __init__(self, path: Path):
        self.path = path


def sanitize(value: str) -> str:
    """Make one placeholder value safe as a single path component."""
    value = _UNSAFE.sub("_", str(value)).strip()
    value = re.sub(r"^\.+", lambda m: "_" * len(m.group()), value)
    value = value.rstrip(" .")
    if _RESERVED.match(value):
        value = "_" + value
    return value or "_"


def validate_template(template: str) -> None:
    try:
        fields = [f for _, f, _, _ in string.Formatter().parse(template) if f is not None]
    except ValueError as e:
        raise TemplateError(f"bad template {template!r}: {e}") from None
    unknown = [f for f in fields if f not in PLACEHOLDERS]
    if unknown:
        raise TemplateError(
            f"unknown placeholder {{{unknown[0]}}} in template; use {', '.join('{%s}' % p for p in sorted(PLACEHOLDERS))}"
        )
    render(template, Purchase("a", "t", "album", "p", 1, 1, None), "flac")


def render(template: str, purchase: Purchase, fmt: str) -> Path:
    """The purchase's path relative to the output folder, without a file extension."""
    values = {
        "artist": purchase.artist,
        "title": purchase.title,
        "type": purchase.type,
        "format": fmt,
        "id": purchase.item_id,
    }
    rendered = template.format(**{k: sanitize(v) for k, v in values.items()})
    parts = [p for p in re.split(r"[/\\]", rendered) if p]
    if not parts or rendered.startswith(("/", "\\")) or any(p in (".", "..") for p in parts):
        raise TemplateError(f"template {template!r} must give a path inside the output folder")
    return Path(*parts)


@dataclass
class Options:
    output: Path
    format: str = "flac"
    template: str = DEFAULT_TEMPLATE
    dry_run: bool = False
    limit: int | None = None
    force: bool = False


@dataclass
class Counts:
    downloaded: int = 0
    synced: int = 0
    skipped: int = 0
    failed: int = 0
    not_downloadable: int = 0
    planned: int = 0
    failures: list[str] = field(default_factory=list)


def _expected_path(output: Path, rel: Path, purchase: Purchase, fmt: str) -> Path:
    if purchase.type == "album":
        return output / rel
    return output / rel.with_name(rel.name + EXTENSIONS[fmt])


def _download(client: Client, purchase: Purchase, fmt: str, output: Path, rel: Path) -> Path:
    available = client.formats(purchase.redownload_url)
    if fmt not in available:
        offered = ", ".join(sorted(available)) or "none"
        raise BandcampError(f"format {fmt} not offered (available: {offered})")
    url = client.resolve(available[fmt])

    base = output / rel
    base.parent.mkdir(parents=True, exist_ok=True)
    part = base.with_name(base.name + ".part")
    tmp: Path | None = None
    try:
        name = client.fetch(url, part)
        with open(part, "rb") as f:
            looks_zipped = f.read(4) == b"PK\x03\x04"
        if purchase.type == "album" or looks_zipped:
            # Albums always come as a zip; a broken one raises BadZipFile here.
            dest = base
            if dest.exists():
                raise _Exists(dest)
            tmp = Path(tempfile.mkdtemp(prefix=f".{base.name}.", suffix=".tmp", dir=base.parent))
            with zipfile.ZipFile(part) as z:
                z.extractall(tmp)
            os.rename(tmp, dest)
            tmp = None
        else:
            ext = os.path.splitext(name or "")[1].lower()
            if not re.fullmatch(r"\.[a-z0-9]{1,5}", ext) or ext == ".part":
                ext = EXTENSIONS[fmt]
            dest = base.with_name(base.name + ext)
            if dest.exists():
                raise _Exists(dest)
            os.rename(part, dest)
        return dest
    finally:
        part.unlink(missing_ok=True)
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)


def _reason(error: Exception) -> str:
    if isinstance(error, requests.HTTPError) and error.response is not None:
        return f"HTTP {error.response.status_code}"
    if isinstance(error, requests.RequestException):
        return f"network error ({type(error).__name__})"
    if isinstance(error, zipfile.BadZipFile):
        return f"bad zip ({error})"
    return str(error) or type(error).__name__


def sync(client: Client, purchases: list[Purchase], options: Options, out: Callable[[str], None] = print) -> Counts:
    output = options.output
    fmt = options.format
    state = State.load(output)
    counts = Counts()
    started = 0
    total = len(purchases)

    for index, purchase in enumerate(purchases, 1):
        label = f"[{index}/{total}] {purchase.artist} — {purchase.title}"
        key = state_key(purchase.sale_key, fmt)

        if not purchase.redownload_url:
            counts.not_downloadable += 1
            out(f"{label} … not downloadable (no download link)")
            continue
        if key in state and not options.force:
            counts.synced += 1
            out(f"{label} … already synced")
            continue

        rel = render(options.template, purchase, fmt)
        expected = _expected_path(output, rel, purchase, fmt)
        if expected.exists():
            counts.skipped += 1
            out(f"{label} … skipped: exists ({expected.relative_to(output)})")
            if not options.dry_run:
                state.record(key, purchase.artist, purchase.title, str(expected.relative_to(output)))
            continue

        if options.limit is not None and started >= options.limit:
            out(f"limit of {options.limit} reached, the rest waits for the next run")
            break
        started += 1

        if options.dry_run:
            counts.planned += 1
            out(f"{label} … would download to {expected.relative_to(output)}")
            continue

        if started > 1 and PAUSE:
            time.sleep(PAUSE)
        try:
            dest = _download(client, purchase, fmt, output, rel)
        except _Exists as e:
            counts.skipped += 1
            out(f"{label} … skipped: exists ({e.path.relative_to(output)})")
            state.record(key, purchase.artist, purchase.title, str(e.path.relative_to(output)))
            continue
        except (requests.RequestException, BandcampError, zipfile.BadZipFile, OSError) as e:
            counts.failed += 1
            counts.failures.append(purchase.sale_key)
            out(f"{label} … failed: {_reason(e)}")
            continue
        counts.downloaded += 1
        state.record(key, purchase.artist, purchase.title, str(dest.relative_to(output)))
        out(f"{label} … downloaded to {dest.relative_to(output)}")

    if options.dry_run:
        out(
            f"dry run: {counts.planned} to download, {counts.synced} already synced, "
            f"{counts.skipped} skipped, {counts.not_downloadable} not downloadable"
        )
    else:
        out(
            f"{counts.downloaded} downloaded, {counts.synced} already synced, {counts.skipped} skipped, "
            f"{counts.failed} failed, {counts.not_downloadable} not downloadable"
        )
    return counts
