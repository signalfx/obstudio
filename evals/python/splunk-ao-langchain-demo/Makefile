.PHONY: sync run test clean

sync:
	uv sync --no-config --default-index https://pypi.org/simple --group dev

run: sync
	uv run --no-config python app.py

test: sync
	uv run --no-config pytest

clean:
	rm -rf .venv __pycache__ .pytest_cache tests/__pycache__
