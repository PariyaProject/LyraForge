.PHONY: setup lint test fixtures smoke check web-setup web-test web-build desktop

setup:
	uv sync

web-setup:
	pnpm --dir apps/desktop/web install

web-test:
	pnpm --dir apps/desktop/web test

web-build:
	pnpm --dir apps/desktop/web build

desktop: web-build
	uv run --extra desktop lyraforge desktop

lint:
	uv run ruff check .

test:
	uv run pytest --cov=lyraforge --cov-report=term-missing --cov-fail-under=80

fixtures:
	uv run python scripts/make_fixtures.py

smoke:
	@tmpdir=$$(mktemp -d); \
	trap 'rm -rf "$$tmpdir"' EXIT; \
	uv run lyraforge profiles list; \
	uv run lyraforge inspect tests/fixtures/midi/chords_type1.mid > /dev/null; \
	uv run lyraforge arrange tests/fixtures/midi/chords_type1.mid -o "$$tmpdir/perf.json" --report "$$tmpdir/report.json"; \
	uv run lyraforge validate "$$tmpdir/perf.json"; \
	uv run lyraforge preview "$$tmpdir/perf.json" -o "$$tmpdir/preview.wav" > /dev/null; \
	uv run lyraforge playback dry-run "$$tmpdir/perf.json" --log "$$tmpdir/actions.jsonl"; \
	sid=$$(uv run lyraforge import tests/fixtures/midi/c_major_scale.mid --title "Smoke Song" --data-dir "$$tmpdir/lib" | uv run python -c "import sys,json; print(json.load(sys.stdin)['song']['id'])"); \
	aid=$$(uv run lyraforge library arrange "$$sid" --style balanced --data-dir "$$tmpdir/lib" | uv run python -c "import sys,json; print(json.load(sys.stdin)['id'])"); \
	uv run lyraforge preview "$$aid" --data-dir "$$tmpdir/lib" > /dev/null; \
	uv run lyraforge playback dry-run "$$aid" --data-dir "$$tmpdir/lib" > /dev/null

check: lint test web-test web-build smoke
