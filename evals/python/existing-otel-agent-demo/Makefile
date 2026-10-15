.PHONY: build test

build:
	uv sync

test:
	uv run python probe.py capture --mode generic --output /tmp/existing-otel-baseline.json
