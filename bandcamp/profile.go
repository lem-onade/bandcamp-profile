package bandcamp

import (
	"fmt"
	"io"
	"log"
	"net/http"
	"strconv"
)

type Profile struct {
	ID        int64  `json:"id"`
	URL       string `json:"url"`
	ItemCount int    `json:"item_count"`
	Items     []Item `json:"items"`
}

// FetchProfile resolves a Bandcamp username to a fan_id, then fetches their collection.
func FetchProfile(username string, log *log.Logger) (*Profile, error) {
	fanID, err := fetchFanID(username, log)
	if err != nil {
		return nil, err
	}

	items, err := fetchCollection(fanID, httpClient, log)
	if err != nil {
		return nil, fmt.Errorf("fetching collection: %w", err)
	}

	return &Profile{
		ID:        fanID,
		URL:       fmt.Sprintf("%s/%s", baseURL, username),
		ItemCount: len(items),
		Items:     items,
	}, nil
}

func fetchFanID(username string, log *log.Logger) (int64, error) {
	url := fmt.Sprintf("%s/%s", baseURL, username)
	log.Printf("GET %s", url)

	resp, err := httpClient.Get(url)
	if err != nil {
		return 0, fmt.Errorf("fetching profile page: %w", err)
	}
	defer resp.Body.Close()

	log.Printf("status: %s", resp.Status)

	if resp.StatusCode == http.StatusNotFound {
		return 0, fmt.Errorf("user %q not found", username)
	}
	if resp.StatusCode != http.StatusOK {
		return 0, fmt.Errorf("profile page returned HTTP %d", resp.StatusCode)
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return 0, err
	}

	log.Printf("body size: %d bytes", len(body))

	m := fanIDRe.FindSubmatch(body)
	if m == nil {
		snippet := body
		if len(snippet) > 512 {
			snippet = snippet[:512]
		}
		log.Printf("fan_id not found; first 512 bytes of body:\n%s", snippet)
		return 0, fmt.Errorf("could not find fan_id on profile page for %q", username)
	}

	log.Printf("fan_id: %s", m[1])
	return strconv.ParseInt(string(m[1]), 10, 64)
}
