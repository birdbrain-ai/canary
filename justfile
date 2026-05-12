test:
    uv run pytest

format:
    uv run ruff format src/canary

lint:
    uv run ruff check src/canary

check: lint
