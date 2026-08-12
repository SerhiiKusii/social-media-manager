PATH := $(CURDIR)/.tools/node/bin:$(CURDIR)/.tools/ffmpeg:$(PATH)

.PHONY: dev tools test test-fast test-slow lint typecheck db-upgrade db-check render-smoke clean

dev:
	pip install -e ".[dev]"

tools:
	./scripts/install-tools.sh

test: test-fast

test-fast:
	PATH="$(PATH)" pytest

test-slow:
	PATH="$(PATH)" pytest -m slow

lint:
	ruff check src tests

typecheck:
	mypy src

db-upgrade:
	trendstealer db upgrade

db-check:
	trendstealer db check

render-smoke:
	cd video-renderer && PATH="$(PATH)" npx remotion render SmokeTest ../var/tmp/smoke.mp4

clean:
	find . -name '__pycache__' -type d -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
