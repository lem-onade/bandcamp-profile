"""bandcamp-sync: download everything you bought on Bandcamp, once."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import requests

from . import __version__
from .client import AuthError, BandcampError, Client
from .sync import DEFAULT_TEMPLATE, FORMATS, Options, TemplateError, sync, validate_template

DEFAULT_COOKIE_FILE = "~/.config/bandcamp-sync/cookie"
COOKIE_HELP = (
    "copy the 'identity' cookie from your browser (devtools → Storage/Application → Cookies → "
    "bandcamp.com) into that file; see the README's 'Sync purchases' section"
)


class CookieError(Exception):
    pass


def cookie_path(arg: str | None) -> tuple[Path, str]:
    if arg:
        return Path(arg).expanduser(), "--cookie-file"
    env = os.environ.get("BANDCAMP_SYNC_COOKIE_FILE")
    if env:
        return Path(env).expanduser(), "$BANDCAMP_SYNC_COOKIE_FILE"
    return Path(DEFAULT_COOKIE_FILE).expanduser(), "default location"


def load_cookie(path: Path, source: str) -> str:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        raise CookieError(f"no cookie file at {path} ({source}); {COOKIE_HELP}") from None
    except OSError as e:
        raise CookieError(f"can't read cookie file {path} ({source}): {e.strerror}") from None
    if text.startswith("identity="):
        text = text[len("identity="):].strip()
    if not text:
        raise CookieError(f"cookie file {path} ({source}) is empty; {COOKIE_HELP}")
    return text


def positive_int(value: str) -> int:
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return n


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bandcamp-sync",
        description="Download your Bandcamp purchases into a folder. Re-run any time: "
        "only purchases not yet downloaded in the chosen format are fetched.",
    )
    parser.add_argument("-o", "--output", default="./bandcamp", help="folder to download into (default: ./bandcamp)")
    parser.add_argument("-f", "--format", default="flac", choices=FORMATS, help="audio format (default: flac)")
    parser.add_argument(
        "-t",
        "--template",
        default=DEFAULT_TEMPLATE,
        help="path for each purchase inside the output folder, from {artist} {title} {type} {format} {id}; "
        "albums become a folder, tracks get the file's extension (default: %(default)s)",
    )
    parser.add_argument("-n", "--dry-run", action="store_true", help="list what would be downloaded and where, then stop")
    parser.add_argument("--limit", type=positive_int, metavar="N", help="download at most N new purchases this run")
    parser.add_argument(
        "--force", action="store_true", help="ignore the sync record and download again (never overwrites files)"
    )
    parser.add_argument(
        "--cookie-file",
        metavar="PATH",
        help="file holding your bandcamp.com 'identity' cookie "
        f"(default: $BANDCAMP_SYNC_COOKIE_FILE, then {DEFAULT_COOKIE_FILE})",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="print the HTTP steps")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _say(message: str) -> None:
    print(message, flush=True)


def _err(message: str) -> None:
    print(f"bandcamp-sync: {message}", file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate_template(args.template)
    except TemplateError as e:
        _err(str(e))
        return 2

    path, source = cookie_path(args.cookie_file)
    try:
        identity = load_cookie(path, source)
    except CookieError as e:
        _err(str(e))
        return 2

    log = (lambda msg: print(f"  http: {msg}", file=sys.stderr, flush=True)) if args.verbose else None
    client = Client(identity, log=log)
    options = Options(
        output=Path(args.output).expanduser(),
        format=args.format,
        template=args.template,
        dry_run=args.dry_run,
        limit=args.limit,
        force=args.force,
    )

    try:
        try:
            fan_id = client.fan_id()
        except AuthError as e:
            _err(f"{e}; the cookie in {path} ({source}) may be expired; {COOKIE_HELP}")
            return 2
        purchases = client.purchases(fan_id)
        counts = sync(client, purchases, options, out=_say)
    except KeyboardInterrupt:
        _err("interrupted; finished purchases are recorded, the next run picks up the rest")
        return 130
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        _err(f"Bandcamp answered HTTP {status} for {e.request.url.split('?')[0] if e.request else 'a request'}")
        return 1
    except requests.RequestException as e:
        _err(f"couldn't reach Bandcamp ({type(e).__name__})")
        return 1
    except (BandcampError, ValueError, OSError) as e:
        _err(str(e))
        return 1
    return 1 if counts.failed else 0


if __name__ == "__main__":
    sys.exit(main())
