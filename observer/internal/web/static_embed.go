//go:build !dev

package web

import (
	"embed"
	"io/fs"
)

//go:embed all:static
var embeddedFS embed.FS

func staticFS() fs.FS { return embeddedFS }
