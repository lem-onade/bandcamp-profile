package cmd

import (
	"encoding/json"
	"fmt"
	"os"

	"github.com/lem-onade/bandcamp-profile/internal/bandcamp"
	"github.com/spf13/cobra"
)

var (
	outputFile string
	format     string
)

var profileCmd = &cobra.Command{
	Use:   "profile <username>",
	Short: "Fetch a Bandcamp fan profile and their collection",
	Args:  cobra.ExactArgs(1),
	RunE:  runE,
}

func runE(cmd *cobra.Command, args []string) error {
	profile, err := bandcamp.FetchProfile(args[0])
	if err != nil {
		return err
	}

	var out []byte
	if format == "readable" {
		out, err = json.MarshalIndent(profile, "", "  ")
	} else {
		out, err = json.Marshal(profile)
	}
	if err != nil {
		return err
	}

	if outputFile != "" {
		return os.WriteFile(outputFile, out, 0644)
	}
	fmt.Println(string(out))
	return nil
}

func init() {
	profileCmd.Flags().StringVarP(&outputFile, "output", "o", "", "write output to a file")
	profileCmd.Flags().StringVarP(&format, "format", "F", "json", "output format: json or readable")
}
