# bandcamp-profile

## Description 

Get Bandcamp profile information (owned tracks, wishlist, ...)

## Usage

List arguments, example usage
```bash
python3 main.py -h
```

Get profile information
```bash
username=lmnd
python3 main.py https://bandcamp.com/$username
```

Download all albums (using jq and [bandcamp-dl](https://github.com/iheanyi/bandcamp-dl))
```bash
username=lmnd
output_dir=bandcamp/
python3 main.py https://bandcamp.com/$username | jq -r ".items.[].url" | xargs -n1 bandcamp-dl --base-dir=$output_dir
```

## Sync purchases

`bandcamp-sync` downloads everything you bought on Bandcamp into a folder, in the format and
layout you choose. Run it again whenever you like: it only fetches purchases it hasn't
downloaded yet in that format.

### Install

```bash
uv run bandcamp-sync --help     # run from this repo
pipx install .                  # or install it as a command
```

### Log in with your browser's cookie

Bandcamp has no login API, so the tool uses your browser session's `identity` cookie.

1. Log in at <https://bandcamp.com> in your browser.
2. Open the developer tools: Storage (Firefox) or Application (Chrome) → Cookies →
   `https://bandcamp.com` → `identity`.
3. Copy its value into `~/.config/bandcamp-sync/cookie` (either the bare value or
   `identity=<value>`), and keep the file private:

```bash
mkdir -p ~/.config/bandcamp-sync
nano ~/.config/bandcamp-sync/cookie
chmod 600 ~/.config/bandcamp-sync/cookie
```

The cookie is read from `--cookie-file PATH`, then `$BANDCAMP_SYNC_COOKIE_FILE`, then
`~/.config/bandcamp-sync/cookie`. If it's missing or expired, the command exits with code 2
and says where it looked; copy a fresh cookie in and run it again.

### Examples

```bash
bandcamp-sync                                   # FLAC into ./bandcamp/{artist}/{title}
bandcamp-sync -n                                # show what would be downloaded, change nothing
bandcamp-sync -o ~/Music/Bandcamp -f mp3-320    # MP3 320 into your music folder
bandcamp-sync -t '{artist}/{title} [{format}]'  # your own layout
bandcamp-sync --limit 5                         # at most 5 new purchases this run
```

Albums are unzipped into a folder (cover art included, as Bandcamp ships it); single tracks
become `<template>.<ext>`, for example `Artist/Title.flac`.

### Flags

| Flag | What it does |
| --- | --- |
| `-o, --output DIR` | Where downloads go (default `./bandcamp`). |
| `-f, --format` | `flac` (default), `mp3-320`, `mp3-v0`, `aac-hi`, `vorbis`, `alac`, `wav` or `aiff-lossless`. |
| `-t, --template` | Path of each purchase inside the output folder, from `{artist}`, `{title}`, `{type}` (album/track), `{format}` and `{id}`. Default `{artist}/{title}`. Characters that aren't safe in file names are replaced. |
| `-n, --dry-run` | List what would be downloaded and where, then stop. |
| `--limit N` | Download at most N new purchases this run. |
| `--force` | Ignore the sync record and download again. Existing files are still never overwritten. |
| `--cookie-file PATH` | File holding the `identity` cookie. |
| `-v, --verbose` | Print the HTTP steps (to stderr; the cookie is never printed). |

### How the sync record works

The tool keeps `<output>/.bandcamp-sync.json`, keyed per purchase and format. It's saved after
each finished purchase, so stopping halfway (Ctrl-C) loses nothing. Purchases that fail aren't
recorded, so the next run retries them; the command exits 1 if anything failed. A destination
that already exists is never overwritten: it's marked "skipped: exists" and recorded. Switching
`--format` downloads everything again in the new format, so point it at another folder or add
`{format}` to the template.

Output is one plain line per purchase plus a summary, so it reads well in cron logs.

### Tests

```bash
uv run pytest
```

The tests run against a local fake Bandcamp (`tests/fake_bandcamp.py`), never the real site.
`BANDCAMP_SYNC_BASE_URL` points the tool at another base URL.
