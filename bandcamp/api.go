package bandcamp

import (
	"net/http"
	"time"
)

const (
	baseURL         = "https://bandcamp.com/api"
	collectionItems = "/fancollection/1/collection_items"
)

func apiURL(path string) string {
	return baseURL + path
}

var httpClient = &http.Client{Timeout: 15 * time.Second}
