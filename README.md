# bp — Bandcamp Profile CLI

Fetch a Bandcamp fan profile and their collection from the command line.

## Install

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

# Pretty-print
bp profile lmnd --format readable

# Save to file
bp profile lmnd --output collection.json

# Pipe into jq and download all albums with bandcamp-dl
bp profile lmnd | jq -r '.items[].url' | xargs -n1 bandcamp-dl --base-dir=bandcamp/
```

## Flags

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--format` | `-F` | `json` | `json` or `readable` |
| `--output` | `-o` | stdout | Write output to a file |

## Project layout

```
main.go                         entry point
cmd/
  root.go                       cobra root command
  profile.go                    bp profile <username>
internal/bandcamp/
  bandcamp.go                   HTTP client, models, API calls
```

Adding a new command: create `cmd/<name>.go` and register it in `cmd/root.go`.

