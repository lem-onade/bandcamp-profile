package bandcamp

import (
"archive/zip"
"encoding/json"
"fmt"
"io"
"net/http"
"os"
"path/filepath"
"regexp"
"strings"
)

// DownloadAlbum downloads item in the given format to destDir and extracts it.
// Files land in destDir/<BandName>/<Title>/ matching the reference project layout.
// progress is called with (bytesReceived, totalBytes) during the download; pass nil to ignore.
func (s *Session) DownloadAlbum(item Item, format, destDir string, progress func(n, total int64)) error {
enc := Formats[format]
if enc == "" {
return fmt.Errorf("unknown format %q \u2014 valid choices: mp3 mp3320 flac aac ogg alac wav aiff", format)
}
if item.RedownloadURL == "" {
return fmt.Errorf("no download URL for %q (item not downloadable or API changed)", item.Title)
}

// Resolve relative URLs (/download?...) to absolute.
pageURL := item.RedownloadURL
if strings.HasPrefix(pageURL, "/") {
pageURL = "https://bandcamp.com" + pageURL
}

// 1. Fetch the download page and find the CDN URL for the requested encoding.
cdnURL, err := s.fetchCDNURL(pageURL, enc)
if err != nil {
return fmt.Errorf("fetching download page for %q: %w", item.Title, err)
}

// 2. Stream the zip to a temp file.
artist := item.BandName
if artist == "" {
artist = "Unknown Artist"
}
zipPath := filepath.Join(destDir, sanitiseName(item.Title)+".zip")
if err := downloadZip(cdnURL, zipPath, progress); err != nil {
return fmt.Errorf("downloading %q: %w", item.Title, err)
}

// 3. Extract into destDir/<artist>/<title>/.
extractDest := filepath.Join(destDir, sanitiseName(artist), sanitiseName(item.Title))
if err := extractZip(zipPath, extractDest); err != nil {
os.Remove(zipPath)
return fmt.Errorf("extracting %q: %w", item.Title, err)
}
return os.Remove(zipPath)
}

// dataBlobRe matches the data-blob attribute value on the download page element.
var dataBlobRe = regexp.MustCompile(`data-blob="([^"]+(?:&quot;[^"]*)*)"`)

// fetchCDNURL GETs a Bandcamp download page, parses the data-blob attribute,
// and returns the pre-signed CDN URL for the requested encoding.
//
// The data-blob attribute contains HTML-encoded JSON. Bandcamp no longer uses
// a "var PageData = {...}" inline script variable; data lives in a DOM attribute.
// If this breaks, run .github/skills/bandcamp-reverse/SKILL.md to re-derive.
func (s *Session) fetchCDNURL(pageURL, enc string) (string, error) {
resp, err := s.client.Get(pageURL)
if err != nil {
return "", err
}
body, err := io.ReadAll(resp.Body)
resp.Body.Close()
if err != nil {
return "", err
}

// Find the [data-blob] element and decode its attribute value.
el := findDataBlobElement(body)
if el == nil {
return "", fmt.Errorf(
"data-blob element not found on download page \u2014 run .github/skills/bandcamp-reverse/SKILL.md to re-derive",
)
}

// Unescape HTML entities in the attribute value.
raw := strings.NewReplacer("&quot;", `"`, "&amp;", "&", "&#39;", "'", "&lt;", "<", "&gt;", ">").Replace(string(el))

var blob struct {
DigitalItems []struct {
Downloads map[string]struct {
URL string `json:"url"`
} `json:"downloads"`
} `json:"digital_items"`
}
if err := json.Unmarshal([]byte(raw), &blob); err != nil {
return "", fmt.Errorf("parsing data-blob JSON: %w", err)
}
if len(blob.DigitalItems) == 0 {
return "", fmt.Errorf(
"no digital_items in data-blob \u2014 run .github/skills/bandcamp-reverse/SKILL.md to re-derive",
)
}
di := blob.DigitalItems[0]
entry, ok := di.Downloads[enc]
if !ok {
return "", fmt.Errorf("encoding %q not available for this item", enc)
}
if entry.URL == "" {
return "", fmt.Errorf("empty download URL for encoding %q", enc)
}
return entry.URL, nil
}

// findDataBlobElement locates the value of the first data-blob attribute in body.
// It handles both quoted-attribute and HTML-encoded-quote variants.
var blobAttrRe = regexp.MustCompile(`data-blob="((?:[^"\\]|\\.)*)"|data-blob='((?:[^'\\]|\\.)*)'`)

func findDataBlobElement(body []byte) []byte {
// Try unescaped single-quote variant first, then double-quote.
// The attribute value uses &quot; for internal double quotes.
idx := strings.Index(string(body), `data-blob="`)
if idx < 0 {
return nil
}
start := idx + len(`data-blob="`)
// Find the closing unescaped double quote.  Because internal JSON quotes are
// encoded as &quot; the actual `"` in the byte stream ends the attribute.
end := strings.Index(string(body[start:]), `"`)
if end < 0 {
return nil
}
return []byte(string(body)[start : start+end])
}

// downloadZip streams cdnURL into zipPath, calling progress(received, total) each chunk.
func downloadZip(cdnURL, zipPath string, progress func(n, total int64)) error {
resp, err := http.Get(cdnURL) // CDN URL is pre-signed; no auth cookies needed.
if err != nil {
return err
}
defer resp.Body.Close()

var total int64
fmt.Sscanf(resp.Header.Get("Content-Length"), "%d", &total)

tmp, err := os.CreateTemp(filepath.Dir(zipPath), ".bc-dl-*")
if err != nil {
return err
}
tmpName := tmp.Name()
defer func() {
tmp.Close()
os.Remove(tmpName)
}()

var received int64
buf := make([]byte, 32*1024)
for {
n, err := resp.Body.Read(buf)
if n > 0 {
if _, werr := tmp.Write(buf[:n]); werr != nil {
return werr
}
received += int64(n)
if progress != nil {
progress(received, total)
}
}
if err == io.EOF {
break
}
if err != nil {
return err
}
}
tmp.Close()
return os.Rename(tmpName, zipPath)
}

// extractZip extracts all entries in zipPath into destDir.
// It prevents zip-slip attacks by rejecting paths that escape destDir.
func extractZip(zipPath, destDir string) error {
r, err := zip.OpenReader(zipPath)
if err != nil {
return err
}
defer r.Close()

if err := os.MkdirAll(destDir, 0755); err != nil {
return err
}

for _, f := range r.File {
name := filepath.Clean(f.Name)
if strings.HasPrefix(name, ".."+string(filepath.Separator)) || name == ".." {
continue
}
target := filepath.Join(destDir, name)

if f.FileInfo().IsDir() {
os.MkdirAll(target, 0755)
continue
}

if err := os.MkdirAll(filepath.Dir(target), 0755); err != nil {
return err
}
if err := writeZipEntry(f, target); err != nil {
return err
}
}
return nil
}

func writeZipEntry(f *zip.File, target string) error {
rc, err := f.Open()
if err != nil {
return err
}
defer rc.Close()

out, err := os.Create(target)
if err != nil {
return err
}
defer out.Close()

_, err = io.Copy(out, rc)
return err
}

// sanitiseName removes characters that are problematic in file/directory names.
func sanitiseName(s string) string {
r := strings.NewReplacer("/", "-", "\\", "-", ":", "-", "*", "-", "?", "", `"`, "", "<", "", ">", "", "|", "")
return strings.TrimSpace(r.Replace(s))
}
