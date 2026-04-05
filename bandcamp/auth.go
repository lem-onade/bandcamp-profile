package bandcamp

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/cookiejar"
	"net/url"
	"os"
	"path/filepath"
	"time"
)

// Session is an authenticated Bandcamp session. All HTTP calls made through
// s.client carry the login cookies automatically via the embedded cookie jar.
type Session struct {
	client   *http.Client
	Username string
}

// storedCookie is the subset of playwright.Cookie we persist and care about.
type storedCookie struct {
	Name     string  `json:"name"`
	Value    string  `json:"value"`
	Domain   string  `json:"domain"`
	Path     string  `json:"path"`
	Expires  float64 `json:"expires"`
	HTTPOnly bool    `json:"httpOnly"`
	Secure   bool    `json:"secure"`
}

type storedSession struct {
	Username string         `json:"username"`
	SavedAt  time.Time      `json:"saved_at"`
	Cookies  []storedCookie `json:"cookies"`
}

// Login loads the saved browser session from ~/.config/bp/session.json.
//
// Run 'bp login -u <username>' first to create that file.
// The file is written by cmd/login.go using Playwright after a successful
// browser login (which handles the reCAPTCHA that plain HTTP cannot).
func Login(username string) (*Session, error) {
	path, err := sessionFilePath()
	if err != nil {
		return nil, err
	}

	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, fmt.Errorf(
				"no saved session found for %q\n"+
					"Run: bp login -u %s",
				username, username,
			)
		}
		return nil, err
	}

	var ss storedSession
	if err := json.Unmarshal(data, &ss); err != nil {
		return nil, fmt.Errorf("reading session file: %w", err)
	}

	jar, err := cookiejar.New(nil)
	if err != nil {
		return nil, err
	}

	// Inject the saved cookies into the jar.
	bcURL, _ := url.Parse("https://bandcamp.com")
	var httpCookies []*http.Cookie
	for _, c := range ss.Cookies {
		if c.Expires > 0 && c.Expires < float64(time.Now().Unix()) {
			continue // skip expired cookies
		}
		httpCookies = append(httpCookies, &http.Cookie{
			Name:     c.Name,
			Value:    c.Value,
			Domain:   c.Domain,
			Path:     c.Path,
			HttpOnly: c.HTTPOnly,
			Secure:   c.Secure,
		})
	}
	jar.SetCookies(bcURL, httpCookies)

	client := &http.Client{
		Jar:     jar,
		Timeout: 30 * time.Second,
	}

	return &Session{client: client, Username: ss.Username}, nil
}

func sessionFilePath() (string, error) {
	dir, err := os.UserConfigDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(dir, "bp", "session.json"), nil
}
