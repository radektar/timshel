# Olympus Transcriber - Development Makefile

.PHONY: help install test test-pipeline test-e2e test-ui lint format clean run setup-daemon stop-daemon logs icon build-app build-dmg release eval-synthesis signal-report

help:
	@echo "Malinche - Development Commands"
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
	@echo "  make signal-report - Action-rate readout over the Insights signal log"
	@echo ""
	@echo "Distribution (macOS):"
	@echo "  make build-app     - Build .app bundle"
	@echo "  make build-dmg     - Create DMG installer"
	@echo "  make release       - Full release pipeline (app + dmg + checksums)"
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
	@echo "Starting Olympus Transcriber..."
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
	tail -f ~/Library/Logs/olympus_transcriber.log

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

build-dmg:
	@echo "Creating DMG installer..."
	bash scripts/create_dmg.sh

release:
	@echo "Running full release pipeline..."
	bash scripts/build_release.sh




