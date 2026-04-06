package main

import (
	"encoding/json"
	"fmt"
	"io/fs"
	"log"
	"os"
	"path/filepath"
	"strings"

	"github.com/spf13/cobra"
)

type agentTarget struct {
	skillsDir func(string) string
	mcpConfig func() string
}

var targets = map[string]agentTarget{
	"cursor": {
		skillsDir: func(home string) string { return filepath.Join(home, ".cursor", "skills", "obstudio") },
		mcpConfig: func() string { return filepath.Join(userHome(), ".cursor", "mcp.json") },
	},
	"claude-code": {
		skillsDir: func(home string) string { return filepath.Join(home, ".claude", "skills", "obstudio") },
		mcpConfig: func() string { return filepath.Join(userHome(), ".claude", "settings.json") },
	},
	"codex": {
		skillsDir: func(home string) string { return filepath.Join(home, ".codex", "skills", "obstudio") },
		mcpConfig: func() string { return filepath.Join(userHome(), ".codex", "mcp.json") },
	},
}

func supportedTargets() string {
	names := make([]string, 0, len(targets))
	for k := range targets {
		names = append(names, k)
	}
	return strings.Join(names, ", ")
}

func newInstallCmd() *cobra.Command {
	var target string

	cmd := &cobra.Command{
		Use:   "install",
		Short: "Install skills and configure the MCP server for an AI coding agent",
		RunE: func(_ *cobra.Command, _ []string) error {
			return runInstall(target)
		},
	}

	cmd.Flags().StringVar(&target, "target", "", "Agent target ("+supportedTargets()+")")
	cmd.MarkFlagRequired("target")

	return cmd
}

func runInstall(target string) error {
	t, ok := targets[target]
	if !ok {
		return fmt.Errorf("unknown target: %s (supported: %s)", target, supportedTargets())
	}

	home := userHome()
	destDir := t.skillsDir(home)

	fmt.Printf("Installing obstudio to %s\n", destDir)

	if err := os.RemoveAll(destDir); err != nil {
		return fmt.Errorf("failed to clean destination: %w", err)
	}

	skillsFS, err := fs.Sub(embeddedSkills, "_skills")
	if err != nil {
		return fmt.Errorf("failed to read embedded skills: %w", err)
	}

	if err := extractFS(skillsFS, destDir); err != nil {
		return fmt.Errorf("failed to extract skills: %w", err)
	}
	fmt.Println("  Skills installed (includes references).")

	exePath, err := os.Executable()
	if err != nil {
		return fmt.Errorf("failed to resolve executable path: %w", err)
	}
	exePath, _ = filepath.EvalSymlinks(exePath)

	installedBinary := filepath.Join(destDir, "obstudio")
	if err := copyFile(exePath, installedBinary); err != nil {
		return fmt.Errorf("failed to copy binary: %w", err)
	}
	if err := os.Chmod(installedBinary, 0o755); err != nil {
		return fmt.Errorf("failed to set binary permissions: %w", err)
	}
	fmt.Println("  Binary installed.")

	mcpFile := t.mcpConfig()
	if err := configureMCP(mcpFile, installedBinary); err != nil {
		return fmt.Errorf("failed to configure MCP: %w", err)
	}
	fmt.Printf("  MCP configured in %s\n", mcpFile)

	fmt.Println("\nDone. Restart your editor to activate the MCP server.")
	return nil
}

func configureMCP(path, binaryPath string) error {
	config := map[string]any{}

	data, err := os.ReadFile(path)
	if err == nil {
		if err := json.Unmarshal(data, &config); err != nil {
			return fmt.Errorf("failed to parse %s: %w", path, err)
		}
	}

	servers, ok := config["mcpServers"].(map[string]any)
	if !ok {
		servers = map[string]any{}
	}

	servers["obstudio"] = map[string]any{
		"command": binaryPath,
		"args":    []string{},
	}
	config["mcpServers"] = servers

	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}

	out, err := json.MarshalIndent(config, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, append(out, '\n'), 0o644)
}

func extractFS(src fs.FS, destDir string) error {
	return fs.WalkDir(src, ".", func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}

		target := filepath.Join(destDir, path)

		if d.IsDir() {
			return os.MkdirAll(target, 0o755)
		}

		data, err := fs.ReadFile(src, path)
		if err != nil {
			return err
		}

		if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
			return err
		}
		return os.WriteFile(target, data, 0o644)
	})
}

func copyFile(src, dst string) error {
	data, err := os.ReadFile(src)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
		return err
	}
	return os.WriteFile(dst, data, 0o644)
}

func userHome() string {
	home, err := os.UserHomeDir()
	if err != nil {
		log.Fatalf("Failed to find home directory: %v", err)
	}
	return home
}
