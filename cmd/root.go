package cmd

import "github.com/spf13/cobra"

var rootCmd = &cobra.Command{
	Use:          "bp",
	Short:        "Bandcamp profile CLI",
	SilenceUsage: true,
}

func Execute() error {
	return rootCmd.Execute()
}

func init() {
	rootCmd.AddCommand(profileCmd)
}
