
# bp — Bandcamp Profile CLI

## Description

Retrieve Bandcamp user data from your CLI.

## Usage

```
bp <command> [flags]
```

## Commands

### `bp profile <username>`

Bandcamp user profile data.

```
bp profile lem-onade
bp profile lem-onade --format readable
bp profile lem-onade --output collection.json
```

**Flags**
| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--format` | `-F` | `json` | Output format: `json` or `readable` |
| `--output` | `-o` | stdout | Write output to a file |
