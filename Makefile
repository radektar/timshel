# Olympus Transcriber - Development Makefile

.PHONY: help install test test-pipeline test-e2e test-ui lint format clean run setup-daemon stop-daemon logs icon build-app build-app-tester build-dmg release release-tester smoke-bundle preview-window eval-synthesis signal-report magic-digest recall-eval

help:
	@echo "Timshel - Development Commands"
	@echo ""
	@echo "Setup:"
	@echo "  make install        - Install dependencies"
	@echo "  make setup-daemon   - Install as LaunchAgent"
	@echo ""
	@echo "Development:"
	@echo "  make run           - Run locally"
	@echo "  make test          - Run unit tests (L1, fast)"
	@echo "  make test-pipeline - Run L2 pipeline tests (real whisper)"
	@echo "  make test-e2e      - Run all E2E tests (L2 + L3, needs API key)"
	@echo "  make test-ui       - Run menu bar UI tests (L4)"
	@echo "  make lint          - Run linters"
	@echo "  make format        - Format code"
	@echo "  make preview-window - Render Konstelacja states to dist/preview/ (visual QA)"
	@echo "  make signal-report - Action-rate readout over the Insights signal log"
	@echo ""
	@echo "Distribution (macOS):"
	@echo "  make build-app     - Build .app bundle"
	@echo "  make build-dmg     - Create DMG installer"
	@echo "  make release       - Full release pipeline (app + dmg + checksums)"
	@echo "  make smoke-bundle  - Build tester .app and smoke-test the bundle under a fresh HOME"
	@echo ""
	@echo "Daemon Control:"
	@echo "  make stop-daemon   - Stop LaunchAgent"
	@echo "  make logs          - Watch logs"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean         - Remove build artifacts"

install:
	@echo "Installing dependencies..."
	pip install --upgrade pip
	pip install -r requirements.txt
	pip install -r requirements-dev.txt
	@echo "Done!"

test:
	@echo "Running unit tests (L1)..."
	pytest tests/ -m "not e2e" --ignore=tests/integration

test-pipeline:
	@echo "Running L2 pipeline tests (real whisper, mocked Claude)..."
	pytest tests/e2e/test_pipeline_real_whisper.py -v

test-e2e:
	@echo "Running all E2E scenario tests (L2 + L3; L3 needs ANTHROPIC_API_KEY)..."
	pytest tests/e2e/ -v

test-ui:
	@echo "Running menu bar UI tests (L4)..."
	pytest tests/ -m ui -v

test-coverage:
	@echo "Running tests with coverage..."
	pytest tests/ --cov=src --cov-report=html --cov-report=term
	@echo "Coverage report: htmlcov/index.html"

eval-synthesis:
	@echo "Comparing synthesis models on gold cases (needs a Claude key in settings)..."
	python scripts/eval_synthesis.py

import-text:
	@echo "Importing already-transcribed text (txt/md/vtt) — set SRC=<path>..."
	./venv312/bin/python scripts/import_text.py $(SRC)

magic-digest:
	@echo "Magic-insights tester digest (Opus 4.8 + verdict + metrics)..."
	./venv312/bin/python scripts/magic_digest.py

recall-eval:
	@echo "H3 recall harness over confirmed planted pairs (local, no API)..."
	./venv312/bin/python scripts/recall_eval.py

signal-report:
	@echo "Computing action-rate over the Insights signal log (ADR-004)..."
	python -m src.connections.signal_report

ask:
	@python -m src.connections.recall.cli ask "$(Q)"

backfill-embeddings:
	@echo "Embedding the vault for local recall (first run downloads the model)..."
	python -m src.connections.recall.cli backfill

lint:
	@echo "Running linters..."
	flake8 src/
	mypy src/

format:
	@echo "Formatting code..."
	black src/ tests/
	isort src/ tests/
	@echo "Code formatted!"

run:
	@echo "Starting Timshel..."
	python src/main.py

setup-daemon:
	@echo "Installing LaunchAgent..."
	chmod +x setup.sh
	./setup.sh

stop-daemon:
	@echo "Stopping LaunchAgent..."
	launchctl unload ~/Library/LaunchAgents/com.user.olympus-transcriber.plist
	@echo "Stopped!"

reload-daemon:
	@echo "Reloading LaunchAgent..."
	bash scripts/restart_daemon.sh

logs:
	@echo "Watching logs (Ctrl+C to stop)..."
	tail -f ~/Library/Application\ Support/Timshel/logs/timshel.log

daemon-logs:
	@echo "Watching LaunchAgent logs (Ctrl+C to stop)..."
	tail -f /tmp/olympus-transcriber-out.log

status:
	@echo "Daemon status:"
	@launchctl list | grep olympus-transcriber || echo "Not running"

clean:
	@echo "Cleaning build artifacts..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name ".coverage" -delete
	@echo "Cleaned!"

dev-setup:
	@echo "Setting up development environment..."
	python3.12 -m venv venv
	@echo "Virtual environment created (Python 3.12 — required by src/, e.g. X | None syntax)!"
	@echo "Now run: source venv/bin/activate && make install"

icon:
	@echo "Regenerating app icon (assets/icon.icns + iconset)..."
	python3 assets/gen_icon.py

build-app:
	@echo "Building macOS application bundle..."
	bash scripts/build_app.sh

build-app-tester:
	@echo "Building TESTER macOS application bundle (H1 instrumentation on)..."
	TESTER_BUILD=1 bash scripts/build_app.sh

build-dmg:
	@echo "Creating DMG installer..."
	bash scripts/create_dmg.sh

release:
	@echo "Running full release pipeline..."
	bash scripts/build_release.sh

release-tester:
	@echo "Running TESTER release pipeline (H1 instrumentation on)..."
	TESTER_BUILD=1 bash scripts/build_release.sh

smoke-bundle:
	@echo "Smoke-testing the built bundle under a fresh HOME..."
	bash scripts/smoke_bundle.sh

preview-window:
	@echo "Rendering Konstelacja window states to dist/preview/ (visual QA)..."
	./venv312/bin/python scripts/preview_window.py

verify-tester:
	@echo "Running the autonomous tester-build acceptance harness (A1-A8)..."
	./venv312/bin/python scripts/verify_tester.py





resummarize:
	@echo "Re-summarize transcript notes to v2 format (plan mode; add ARGS='--preview'/'--apply')..."
	./venv312/bin/python scripts/resummarize_vault.py $(ARGS)
