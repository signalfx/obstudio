package buildutil

import (
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
)

// StageEmbeddedSkills copies the repo-level skills directory into the
// observer-go embed location expected by cmd/obstudio.
func StageEmbeddedSkills(repoRoot, observerGoRoot string) error {
	skillsSrc := filepath.Join(repoRoot, "skills")
	skillsDest := filepath.Join(observerGoRoot, "cmd", "obstudio", "_skills")
	examplesSrc := filepath.Join(repoRoot, "docs", "examples.md")

	if _, err := os.Stat(skillsSrc); err != nil {
		return fmt.Errorf("stat skills source: %w", err)
	}
	if err := os.RemoveAll(skillsDest); err != nil {
		return fmt.Errorf("remove staged skills: %w", err)
	}
	if err := copyDir(skillsSrc, skillsDest); err != nil {
		return fmt.Errorf("copy skills: %w", err)
	}

	if _, err := os.Stat(examplesSrc); err == nil {
		if err := copyFile(examplesSrc, filepath.Join(skillsDest, "examples.md")); err != nil {
			return fmt.Errorf("copy examples.md: %w", err)
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return fmt.Errorf("stat examples.md: %w", err)
	}

	return nil
}

func copyDir(src, dst string) error {
	return filepath.WalkDir(src, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}

		rel, err := filepath.Rel(src, path)
		if err != nil {
			return err
		}

		target := dst
		if rel != "." {
			target = filepath.Join(dst, rel)
		}

		if d.IsDir() {
			info, err := d.Info()
			if err != nil {
				return err
			}
			return os.MkdirAll(target, info.Mode().Perm())
		}

		return copyFile(path, target)
	})
}

func copyFile(src, dst string) error {
	info, err := os.Stat(src)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
		return err
	}

	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()

	out, err := os.OpenFile(dst, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, info.Mode().Perm())
	if err != nil {
		return err
	}
	defer out.Close()

	if _, err := io.Copy(out, in); err != nil {
		return err
	}
	return out.Close()
}
