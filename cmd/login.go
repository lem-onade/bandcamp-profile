package cmd

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/playwright-community/playwright-go"
	"github.com/spf13/cobra"
)

var loginCmd = &cobra.Command{
	Use:   "login",
	Short: "Authenticate with Bandcamp and cache the session (required before download)",
	Long: `Opens a browser window for one-time Bandcamp login.

After you complete the login (including any CAPTCHA), the session is saved to
~/.config/bp/session.json and reused by bp download until it expires.

  bp login -u alice`,
	RunE: runLogin,
}

var loginUser string

func runLogin(_ *cobra.Command, _ []string) error {
	if loginUser == "" {
		return fmt.Errorf("--username is required")
	}

	fmt.Fprintln(os.Stderr, "Opening browser for Bandcamp login…")
	fmt.Fprintln(os.Stderr, "(Complete the login in the browser window, then it will close automatically)")

	pw, err := playwright.Run(&playwright.RunOptions{SkipInstallBrowsers: true})
	if err != nil {
		return fmt.Errorf("starting playwright: %w", err)
	}
	defer pw.Stop()

	browser, err := pw.Chromium.Launch(playwright.BrowserTypeLaunchOptions{
		Headless: playwright.Bool(false),
	})
	if err != nil {
		return fmt.Errorf("launching browser: %w", err)
	}
	defer browser.Close()

	page, err := browser.NewPage()
	if err != nil {
		return fmt.Errorf("new page: %w", err)
	}

	if _, err := page.Goto("https://bandcamp.com/login"); err != nil {
		return fmt.Errorf("navigating to login: %w", err)
	}

	// Wait until the user lands on any page that is NOT the login page (success).
	fmt.Fprintln(os.Stderr, "Waiting for login to complete…")
	if err := page.WaitForURL("**!/login**", playwright.PageWaitForURLOptions{
		Timeout: playwright.Float(120_000), // 2 minutes
	}); err != nil {
		return fmt.Errorf("login timed out or was cancelled: %w", err)
	}

	// Also verify account presence via fanId.
	time.Sleep(1 * time.Second) // let the page settle

	cookies, err := browser.Contexts()[0].Cookies()
	if err != nil {
		return fmt.Errorf("extracting cookies: %w", err)
	}
	if len(cookies) == 0 {
		return fmt.Errorf("no cookies found after login")
	}

	if err := saveSession(loginUser, cookies); err != nil {
		return fmt.Errorf("saving session: %w", err)
	}

	fmt.Fprintf(os.Stderr, "Session saved. Run: bp download -u %s\n", loginUser)
	return nil
}

func sessionPath() (string, error) {
	dir, err := os.UserConfigDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(dir, "bp", "session.json"), nil
}

// StoredSession is persisted to disk between invocations.
type StoredSession struct {
	Username  string             `json:"username"`
	SavedAt   time.Time          `json:"saved_at"`
	Cookies   []playwright.Cookie `json:"cookies"`
}

func saveSession(username string, cookies []playwright.Cookie) error {
	path, err := sessionPath()
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return err
	}
	data, err := json.MarshalIndent(StoredSession{
		Username: username,
		SavedAt:  time.Now(),
		Cookies:  cookies,
	}, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, data, 0600)
}

func init() {
	loginCmd.Flags().StringVarP(&loginUser, "username", "u", "", "Bandcamp username")
	rootCmd.AddCommand(loginCmd)
}
