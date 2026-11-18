.PHONY: sync dev clean

sync:
	uv sync

dev: sync
	uv run flask run --port $(or $(PORT),8000) --reload

clean:
	rm -rf .venv __pycache__ *.db .observe
