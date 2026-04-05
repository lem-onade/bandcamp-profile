package bandcamp

import (
	"bytes"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"regexp"
)

func fetchCollection(fanID int64, log *log.Logger) ([]Item, error) {
	log.Printf("POST %s (fan_id: %d)", apiURL(collectionItems), fanID)

	body, err := json.Marshal(collectionRequest{
		FanID:          fanID,
		OlderThanToken: "1654875877:2285568234:p::",
		Count:          10000,
	})
	if err != nil {
		return nil, err
	}

	resp, err := httpClient.Post(apiURL(collectionItems), "application/json", bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("calling collection API: %w", err)
	}
	defer resp.Body.Close()

	log.Printf("collection API status: %s", resp.Status)
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("collection API returned HTTP %d", resp.StatusCode)
	}

	var cr collectionResponse
	if err := json.NewDecoder(resp.Body).Decode(&cr); err != nil {
		return nil, fmt.Errorf("decoding collection response: %w", err)
	}

	items := make([]Item, len(cr.Items))
	for i, r := range cr.Items {
		items[i] = Item{
			ID:           r.ItemID,
			BandID:       r.BandID,
			Slug:         r.URLHints.Slug,
			Title:        r.ItemTitle,
			URL:          r.ItemURL,
			ArtURL:       r.ItemArtURL,
			Downloadable: r.DownloadAvail,
		}
	}
	return items, nil
}

type Item struct {
	ID           int64  `json:"id"`
	BandID       int64  `json:"band_id"`
	Slug         string `json:"slug"`
	Title        string `json:"title"`
	URL          string `json:"url"`
	ArtURL       string `json:"art_url"`
	Downloadable bool   `json:"downloadable"`
}

var fanIDRe = regexp.MustCompile(`(?:"fan_id"|&quot;fan_id&quot;)\s*:\s*(\d+)`)

type collectionRequest struct {
	FanID          int64  `json:"fan_id"`
	OlderThanToken string `json:"older_than_token"`
	Count          int    `json:"count"`
}

type collectionResponse struct {
	Items []struct {
		ItemID        int64  `json:"item_id"`
		BandID        int64  `json:"band_id"`
		ItemTitle     string `json:"item_title"`
		ItemURL       string `json:"item_url"`
		ItemArtURL    string `json:"item_art_url"`
		DownloadAvail bool   `json:"download_available"`
		URLHints      struct {
			Slug string `json:"slug"`
		} `json:"url_hints"`
	} `json:"items"`
}
