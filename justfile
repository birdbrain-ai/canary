test:
    uv run pytest

format:
    uv run ruff format src/canary

lint:
    uv run ruff check src/canary

fix:
    uv run ruff check --fix src/canary

hint:
    uv run ruff check --unsafe-fixes src/canary

check: lint
