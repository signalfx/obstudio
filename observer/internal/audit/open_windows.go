//go:build windows

package audit

import "os"

// openNoFollow opens a path for reading. Windows has no O_NOFOLLOW equivalent
// in the standard library, and creating symlinks there requires elevation by
// default, so the descriptor-based size and mode checks in readContained carry
// the guarantee on this platform.
func openNoFollow(path string) (*os.File, error) {
	return os.Open(path)
}
