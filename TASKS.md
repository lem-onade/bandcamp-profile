# Implementation Tasks — `bp download`

Port the `hisekai/bandcamp-cli` Node/Puppeteer tool to pure Go HTTP, integrated
into this project as a `bp download` subcommand.

> **No Puppeteer. No headless browser at runtime.**
> Protocol constants are isolated in one file so a Playwright agent can update
> them without touching business logic. See `.github/skills/bandcamp-reverse/SKILL.md`.

---

## Phase 0 — Research & Protocol Capture

**TL;DR** — Run the browser skill once to record the real HTTP calls Bandcamp makes.
This produces the values that go into `protocol.go`.

- [ ] **0.1** Load `.github/skills/bandcamp-reverse/SKILL.md` in a Copilot agent session.
- [ ] **0.2** Follow Phase 1 (login handshake): record the login POST URL, all form field
  names, and the CSRF/crumb token selector.
- [ ] **0.3** Follow Phase 2 (collection): confirm whether `redownload_url` is returned
  directly by the `fancollection` API response or must be scraped from page HTML.
- [ ] **0.4** Follow Phase 3 (download page): find the inline JS variable name (e.g.
  `var PageData =`) and the JSON path to `stat_url` and available format keys.
- [ ] **0.5** Follow Phase 4 (statdownload): capture the exact URL pattern, query param
  names (`enc`, `rand`, `id`, `_`), and the JSONP response wrapper string.
- [ ] **0.6** Record everything in `bandcamp/protocol.go` (see Phase 2 task).

---

## Phase 1 — Project Scaffolding

**TL;DR** — Add a `golang.org/x/term` dependency for masked password input and
create the new source files.

- [ ] **1.1** `go get golang.org/x/term` — adds secure terminal password reading
  (disables echo on stdin). No other new dependencies needed.
- [ ] **1.2** Create the four new source files (empty packages for now):
  `bandcamp/protocol.go`, `bandcamp/auth.go`, `bandcamp/download.go`, `cmd/download.go`.
- [ ] **1.3** Run `go build ./...` to confirm the project still compiles cleanly.

---

## Phase 2 — Protocol Constants (`bandcamp/protocol.go`)

**TL;DR** — One file that owns every URL, field name, selector, and format code.
When Bandcamp breaks something, only this file changes.

- [ ] **2.1** Define login constants: `loginURL`, `loginNameField`, `loginPasswordField`,
  `crumbInputName`, `crumbSelector`.
- [ ] **2.2** Define download page constants: `pageDataMarker` (the JS variable prefix
  before the JSON blob), `digitalItemsField`, `statURLField`.
- [ ] **2.3** Define statdownload constants: `statURLQueryEnc`, `statURLQueryRand`,
  `statURLQueryID`, `statResultOK`, `statResultRetry`, `statResultURLField`.
- [ ] **2.4** Define `Formats` map: user-facing flag → Bandcamp encoding name
  (`"flac"→"flac"`, `"mp3"→"mp3-v0"`, `"mp3320"→"mp3-320"`, `"aac"→"aac-hi"`,
  `"ogg"→"vorbis"`, `"alac"→"alac"`, `"wav"→"wav"`, `"aiff"→"aiff-lossless"`).
  Source: `hisekai/bandcamp-cli` `utils/formats.js` — stable, unlikely to change.
- [ ] **2.5** Add a top-of-file comment: "Run `.github/skills/bandcamp-reverse/SKILL.md`
  to re-derive these constants when the download flow breaks."

---

## Phase 3 — Authentication (`bandcamp/auth.go`)

**TL;DR** — `Login(username, password)` does a two-step HTTP exchange (GET crumb → POST
form) and returns a `Session` wrapping a live `http.CookieJar`.

- [ ] **3.1** Define `Session` struct with an `*http.Client` (carries the cookie jar) and
  the `Username` field. All download calls go through this client so the auth cookies
  are automatically attached.
- [ ] **3.2** Implement `Login(username, password string) (*Session, error)`:
  1. `GET loginURL` → read body → extract crumb with a regexp matching `crumbSelector`.
  2. `POST loginURL` with `url.Values{loginNameField, loginPasswordField, crumbInputName}`.
  3. Verify login succeeded: check `resp.Request.URL.Path != "/login"` (redirect away
     from the login page means success).
  4. Return `*Session` with the populated cookie jar.
- [ ] **3.3** Return a clear sentinel error if the crumb is not found (site structure
  changed) vs. wrong credentials (still on `/login` after POST). These map to different
  "fix action" messages for the user.

---

## Phase 4 — Collection with Auth (`bandcamp/collection.go`)

**TL;DR** — Extend the existing unauthenticated collection fetch to accept an
`*http.Client` so the `Session` can inject its auth cookies. Add the fields needed
for downloading.

- [ ] **4.1** Add new fields to the `collectionResponse` item struct:
  `SaleItemType string`, `SaleItemID int64`, `PaymentID int64`,
  `RedownloadURL string`, `BandName string`.
  Use JSON tags that match the API field names (verify with Phase 0).
- [ ] **4.2** Add matching exported fields to `Item`: `SaleItemType`, `SaleItemID`,
  `PaymentID`, `RedownloadURL`, `BandName`.
- [ ] **4.3** Change `fetchCollection` signature to accept `client *http.Client`
  (internal). Update the call in `FetchProfile` to pass the package-level `httpClient`.
- [ ] **4.4** Add `Session.FetchCollection(username string, log *log.Logger) ([]Item, error)`
  which calls `fetchFanID` (reuse existing, unauthenticated) then `fetchCollection`
  with `s.client`. This is the entry point for the download command.

---

## Phase 5 — Download Flow (`bandcamp/download.go`)

**TL;DR** — Four clean functions that map directly to the four steps: get download
page → poll statdownload → fetch zip → extract. Each step is independently testable
and the protocol calls are clearly labelled.

### 5.1 `fetchDownloadPage(s *Session, redownloadURL string) (*pageData, error)`
- `GET redownloadURL` with `s.client`.
- Scan the response HTML for `pageDataMarker`; extract the JSON blob that follows.
- Unmarshal into `pageData` struct:
  ```
  pageData.DigitalItems[0].StatURL   string
  pageData.DigitalItems[0].SaleItemID int64
  pageData.DigitalItems[0].Downloads  map[string]struct{ URL string }
  ```
- Return a clear error if the marker is not found (protocol changed → run skill).

### 5.2 `pollStatDownload(ctx context.Context, s *Session, statURL, enc string, id int64) (cdnURL string, err error)`
- Build the query: `enc=<enc>`, `rand=<random float>`, `id=<id>`, `_=<unix_ms>`.
- Loop with 2-second backoff, honouring `ctx.Done()`.
- `GET statURL+query` → strip JSONP wrapper → JSON unmarshal.
- Return `cdnURL` when `result == statResultOK`; retry on `statResultRetry`.
- Fail fast on unknown result values.

### 5.3 `downloadZip(ctx context.Context, s *Session, cdnURL, destPath string, progress func(n, total int64)) error`
- `GET cdnURL` (no special auth needed — CDN URL is pre-signed).
- Stream body into a temp file (same directory as `destPath`); atomic rename on success.
- Call `progress(bytesRead, contentLength)` on each chunk for live progress display.

### 5.4 `extractZip(zipPath, destDir string) error`
- Open with `archive/zip` (stdlib).
- For each entry: sanitise path (strip leading `../` to prevent zip-slip), create dirs,
  write file.
- Is a pure helper with no Bandcamp-specific knowledge.

### 5.5 `Session.DownloadAlbum(ctx, item Item, format, destDir string, progress func(n, total int64)) error`
- Orchestrates 5.1 → 5.2 → 5.3 → 5.4 → delete zip.
- Handles the case where `item.RedownloadURL` is empty (skip with warning).
- Creates `destDir/<BandName>/<Title>/` as the extraction target (matches reference
  project directory hierarchy).
- Uses the format from the `Formats` map; returns an error if the format key is unknown.

---

## Phase 6 — CLI Command (`cmd/download.go`)

**TL;DR** — `bp download -u <username>` prompts for password, shows a filtered list
from the collection, asks for confirmation, then downloads with per-album progress.

- [ ] **6.1** Define `downloadCmd` with `cobra.Command`:
  - `Use: "download"`
  - `Short: "Download albums from your Bandcamp collection"`
  - Flags: `-u/--username`, `-f/--format` (default `flac`), `-d/--dest` (default `~/Music`),
    `-F/--filter` (title substring), `-n/--last` (download last N), `-v/--verbose`.
- [ ] **6.2** Password prompt: use `golang.org/x/term.ReadPassword(int(os.Stdin.Fd()))`.
  Print `"Password: "` to stderr, read, clear with `"\n"` after. Never accept password
  as a CLI flag (avoids shell history leakage).
- [ ] **6.3** Call `bandcamp.Login(username, password)` → handle both error cases
  ("site changed" → tell user to run the reverse skill; "wrong credentials" → prompt again
  or exit).
- [ ] **6.4** Call `session.FetchCollection(username, log)` to get the full item list.
  Filter to `item.Downloadable == true`. Apply `--filter` and `--last` flags.
- [ ] **6.5** Print a compact table: index, artist, title, format availability.
- [ ] **6.6** Confirmation prompt: `"Download N album(s) to <dest>? [y/N] "` — read one
  character from stdin without requiring Enter (or use a simple `fmt.Scanln`).
- [ ] **6.7** For each album: print `"↓ Artist — Title"`, call `session.DownloadAlbum`
  with a progress closure that renders `\r  42% (12/28 MB)` until done, print `" ✓"`.
- [ ] **6.8** Register `downloadCmd` in `cmd/root.go`'s `init()`.

---

## Phase 7 — End-to-End Verification

**TL;DR** — Smoke-test the whole pipeline with a real account, fix any mismatch
between the code and the live site.

- [ ] **7.1** `go build -o bp .` and run `./bp download -u <username> -n 1 -v`.
- [ ] **7.2** If login fails: re-run Phase 0 (SKILL.md) to capture current login fields.
  Update `protocol.go`.
- [ ] **7.3** If download page parse fails ("no digital items"): re-run Phase 0, Phase 3
  section to find the correct `pageDataMarker` and JSON field paths.
- [ ] **7.4** If statdownload fails: re-run Phase 0, Phase 4 to get the current query
  parameter names and JSONP wrapper.
- [ ] **7.5** Verify that the extracted files are in `~/Music/<BandName>/<Title>/` and
  contain valid audio files.
- [ ] **7.6** Run `./bp profile <username>` to confirm the existing unauthed command
  is not broken.

---

## Phase 8 — Protocol Update Cycle (Maintenance)

**TL;DR** — When `bp download` breaks in the future, the fix is always the same: run
the SKILL.md agent workflow, update `protocol.go`, rebuild.

- [ ] **8.1** Document in `README.md` under a "Maintenance" section:
  > If downloads break, open this project in VS Code and ask Copilot:
  > "Run the bandcamp-reverse skill and update protocol.go"
- [ ] **8.2** Optionally add a `make verify-protocol` target that runs the SKILL.md
  workflow headlessly (if unattended environment) or prints instructions for the manual flow.

---

## File Map

```
.github/skills/bandcamp-reverse/SKILL.md   ← agent browser workflow (already created)
bandcamp/
  protocol.go     ← ALL swappable constants; update this when Bandcamp changes
  auth.go         ← Login(), Session{}
  api.go          ← base URL, http client (existing, unchanged)
  collection.go   ← fetchCollection() extended with auth client + new fields
  profile.go      ← FetchProfile() (existing, unchanged)
  download.go     ← fetchDownloadPage, pollStatDownload, downloadZip, extractZip
cmd/
  root.go         ← register downloadCmd (add one line)
  profile.go      ← existing, unchanged
  download.go     ← bp download subcommand
```

---

## What stays simple / what can rot

| Area | Why it stays stable |
|---|---|
| `archive/zip` extraction | stdlib, no deps |
| `fancollection` API call | This API has been stable for years |
| Format encoding names | Confirmed via reference project; Bandcamp doesn't change these |
| Cookie jar auth injection | Standard Go `net/http` — no special handling needed |
| **Login form fields** | **FRAGILE — run SKILL.md to re-derive** |
| **`pageDataMarker` variable name** | **FRAGILE — run SKILL.md to re-derive** |
| **statdownload URL/params** | **FRAGILE — run SKILL.md to re-derive** |
