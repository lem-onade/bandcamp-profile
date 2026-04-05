package bandcamp

// Protocol constants — ALL Bandcamp endpoint URLs, form field names, and page selectors.
//
// When bp download breaks, run .github/skills/bandcamp-reverse/SKILL.md with a
// Playwright agent to re-derive any of these values and update them here only.
// No other file needs to change for protocol-level fixes.
//
// Last verified: April 2026.

const (
	// loginURL is the page used to GET the login form (for the CSRF meta tag).
	loginURL = "https://bandcamp.com/login"

	// loginPostURL is the endpoint that receives credentials POSTed by JS.
	// FRAGILE: verify from network tab if login stops working.
	loginPostURL = "https://bandcamp.com/login_cb"

	// loginNameField is the POST body key for the username sent to loginPostURL.
	// FRAGILE: inspect the login JS bundle (trackpipe/login_*.js) to confirm.
	loginNameField = "user.name"

	// loginPasswordField is the POST body key for the password sent to loginPostURL.
	// FRAGILE: inspect the login JS bundle to confirm.
	loginPasswordField = "login.password"

	// csrfMetaSelector is the CSS selector for the CSRF token meta tag.
	// The token is sent as an X-CSRF-TOKEN request header (not a form field).
	// FRAGILE: re-verify if login starts returning 403.
	csrfMetaSelector = `meta[name="csrf-token"]`

	// dataBlobSelector is the CSS selector for the element holding the download page
	// JSON payload in its data-blob attribute.
	// FRAGILE: re-verify if download page parsing breaks.
	dataBlobSelector = "[data-blob]"

	// digitalItemsField is the key in the data-blob JSON containing the download items.
	digitalItemsField = "digital_items"

	// downloadsField is the key inside a digital item that maps encoding names to
	// download URLs. Each entry has a "url" field with a pre-signed CDN URL.
	downloadsField = "downloads"

	// redownloadURLField is the key in the fancollection API response item that holds
	// the pre-signed download page path (starts with /download?...).
	// FRAGILE: re-verify with the browser skill if collection items show no download URL.
	redownloadURLField = "redownload_url"
)

// Formats maps CLI flag names to Bandcamp internal audio encoding identifiers.
// Confirmed against live download page April 2026 — stable, Bandcamp does not change these.
var Formats = map[string]string{
	"mp3":    "mp3-v0",
	"mp3320": "mp3-320",
	"flac":   "flac",
	"aac":    "aac-hi",
	"ogg":    "vorbis",
	"alac":   "alac",
	"wav":    "wav",
	"aiff":   "aiff-lossless",
}
