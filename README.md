# bp — Bandcamp Profile CLI

Fetch a Bandcamp fan profile and their collection from the command line.

## Install

Download from releases tab.

Go install:

```bash
go install github.com/lem-onade/bandcamp-profile@latest
```

Or build from source:

```bash
git clone https://github.com/lem-onade/bandcamp-profile
cd bandcamp-profile
go build -o bp .
```

## Usage

```bash
bp profile <username>
```

**Examples**

```bash
# Print collection as JSON
bp profile lmnd

# Save to file
bp profile lmnd -F json --output output.json

# Pipe into jq and download all albums with bandcamp-dl
bp profile lmnd | jq -r '.items[].url' | xargs -n1 bandcamp-dl --base-dir=out/
```

## Flags

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--format` | `-F` | `json` | `json` or `readable` |
| `--output` | `-o` | stdout | Write output to a file |
