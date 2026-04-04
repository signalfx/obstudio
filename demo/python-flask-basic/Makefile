.PHONY: sync dev clean

sync:
	uv sync

dev: sync
	uv run flask run --port 8000 --reload

clean:
	rm -rf .venv __pycache__ *.db .observe
