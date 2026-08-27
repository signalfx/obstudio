//go:build !windows

package audit

import (
	"os"
	"syscall"
)

// openNoFollow opens a path without following a final symlink, so a path that
// is swapped for a symlink after validation fails to open rather than silently
// resolving elsewhere.
func openNoFollow(path string) (*os.File, error) {
	return os.OpenFile(path, os.O_RDONLY|syscall.O_NOFOLLOW, 0)
}
