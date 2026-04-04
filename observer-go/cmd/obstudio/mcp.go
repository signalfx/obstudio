package main

import (
	"os"

	"github.com/spf13/cobra"

	"github.com/signalfx/obstudio/observer-go/internal/mcp"
	"github.com/signalfx/obstudio/observer-go/internal/store"
)

func newMCPCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "mcp",
		Short: "Start the MCP server over stdio (JSON-RPC via stdin/stdout)",
		RunE: func(_ *cobra.Command, _ []string) error {
			s := store.New()
			mcp.RunStdio(s, os.Stdin, os.Stdout)
			return nil
		},
	}
}
