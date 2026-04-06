.PHONY: all test dev build build-all embed-static clean

all: test build

# Run all tests.
test:
	bun test

# Start development server with hot reload.
dev:
	bun --hot src/index.ts

# Embed static assets into src/web/embedded-assets.ts for compiled binary.
embed-static:
	bun scripts/embed-static.ts

# Compile to standalone binary for current platform.
build: embed-static
	bun build --compile src/index.ts --outfile dist/obstudio

# Compile for all platforms.
build-all: embed-static
	mkdir -p dist
	bun build --compile --target=bun-linux-x64 src/index.ts --outfile dist/obstudio-linux-x64
	bun build --compile --target=bun-linux-arm64 src/index.ts --outfile dist/obstudio-linux-arm64
	bun build --compile --target=bun-darwin-x64 src/index.ts --outfile dist/obstudio-darwin-x64
	bun build --compile --target=bun-darwin-arm64 src/index.ts --outfile dist/obstudio-darwin-arm64

clean:
	rm -rf dist
