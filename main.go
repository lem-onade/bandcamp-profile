package main

import (
	"os"

	"github.com/lem-onade/bandcamp-profile/cmd"
)

func main() {
	if err := cmd.Execute(); err != nil {
		os.Exit(1)
	}
}
