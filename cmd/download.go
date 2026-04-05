package cmd

import (
	"fmt"
	"io"
	"log"
	"os"
	"path/filepath"
	"strings"

	"github.com/lem-onade/bandcamp-profile/bandcamp"
	"github.com/spf13/cobra"
)

var (
	dlUsername string
	dlFormat   string
	dlDest     string
	dlFilter   string
	dlLast     int
	dlVerbose  bool
)

var downloadCmd = &cobra.Command{
	Use:   "download",
	Short: "Download albums from your Bandcamp collection",
	Long: `Download purchased albums from your Bandcamp collection.

Run 'bp login -u <username>' once first to cache your session.

Examples:
  bp download -u alice                        download full collection (flac)
  bp download -u alice -f mp3                 use mp3 format
  bp download -u alice -n 5                   last 5 albums only
  bp download -u alice -F "some band"         titles containing "some band"
  bp download -u alice -d /tmp/music          custom destination`,
	RunE: runDownload,
}

func runDownload(cmd *cobra.Command, _ []string) error {
	var debugLog *log.Logger
	if dlVerbose {
		debugLog = log.New(os.Stderr, "[debug] ", 0)
	} else {
		debugLog = log.New(io.Discard, "", 0)
	}

	if dlUsername == "" {
		return fmt.Errorf("--username is required")
	}

	// Load cached session (created by: bp login -u <username>).
	fmt.Fprintln(os.Stderr, "Loading session…")
	session, err := bandcamp.Login(dlUsername)
	if err != nil {
		return err
	}
	debugLog.Printf("loaded session for %s", session.Username)

	// Fetch collection (authenticated so redownload_url is populated).
	fmt.Fprintln(os.Stderr, "Fetching collection…")
	items, err := session.FetchCollection(dlUsername, debugLog)
	if err != nil {
		return fmt.Errorf("fetching collection: %w", err)
	}

	// Filter to downloadable items only.
	var downloadable []bandcamp.Item
	for _, it := range items {
		if it.Downloadable {
			downloadable = append(downloadable, it)
		}
	}

	// Apply title substring filter.
	if dlFilter != "" {
		needle := strings.ToLower(dlFilter)
		var filtered []bandcamp.Item
		for _, it := range downloadable {
			if strings.Contains(strings.ToLower(it.Title), needle) {
				filtered = append(filtered, it)
			}
		}
		downloadable = filtered
	}

	// Apply --last N.
	if dlLast > 0 && dlLast < len(downloadable) {
		downloadable = downloadable[:dlLast]
	}

	if len(downloadable) == 0 {
		fmt.Fprintln(os.Stderr, "No downloadable albums match the given filters.")
		return nil
	}

	// Resolve destination directory.
	dest := dlDest
	if dest == "" {
		home, err := os.UserHomeDir()
		if err != nil {
			return err
		}
		dest = filepath.Join(home, "Music")
	}

	// Confirmation prompt.
	fmt.Fprintf(os.Stderr, "\nDownload %d album(s) to %s? [y/N] ", len(downloadable), dest)
	var ans string
	fmt.Fscan(os.Stdin, &ans)
	if strings.ToLower(strings.TrimSpace(ans)) != "y" {
		fmt.Fprintln(os.Stderr, "Aborted.")
		return nil
	}
	fmt.Fprintln(os.Stderr)

	// Download each album.
	ok, failed := 0, 0
	for _, item := range downloadable {
		artist := item.BandName
		if artist == "" {
			artist = "?"
		}
		fmt.Fprintf(os.Stderr, "↓  %s — %s\n", artist, item.Title)

		err := session.DownloadAlbum(
			item,
			dlFormat,
			dest,
			func(n, total int64) {
				if total > 0 {
					fmt.Fprintf(os.Stderr, "\r   %d%% (%d / %d MB)   ",
						100*n/total, n>>20, total>>20)
				}
			},
		)
		fmt.Fprintln(os.Stderr) // end progress line
		if err != nil {
			fmt.Fprintf(os.Stderr, "   error: %v\n", err)
			failed++
		} else {
			fmt.Fprintln(os.Stderr, "   ✓")
			ok++
		}
	}

	fmt.Fprintf(os.Stderr, "\nDone: %d downloaded, %d failed.\n", ok, failed)
	if failed > 0 {
		return fmt.Errorf("%d download(s) failed", failed)
	}
	return nil
}

func init() {
	downloadCmd.Flags().StringVarP(&dlUsername, "username", "u", "", "Bandcamp username (required)")
	downloadCmd.Flags().StringVarP(&dlFormat, "format", "f", "flac",
		"Audio format: flac mp3 mp3320 aac ogg alac wav aiff")
	downloadCmd.Flags().StringVarP(&dlDest, "dest", "d", "",
		"Destination directory (default: ~/Music)")
	downloadCmd.Flags().StringVarP(&dlFilter, "filter", "F", "",
		"Only download albums whose title contains this string (case-insensitive)")
	downloadCmd.Flags().IntVarP(&dlLast, "last", "n", 0,
		"Download only the last N albums from the filtered list")
	downloadCmd.Flags().BoolVarP(&dlVerbose, "verbose", "v", false,
		"Print debug info to stderr")
}
