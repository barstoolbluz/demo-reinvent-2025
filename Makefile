.PHONY: help setup seed test status clean reset logs shell lint build package

# Development workflow shortcuts

help:
	@echo "Ticket Processing Pipeline - Development Commands"
	@echo ""
	@echo "Setup & Data:"
	@echo "  make setup     - Initialize LocalStack resources"
	@echo "  make seed      - Upload sample tickets"
	@echo "  make reset     - Clean and reinitialize everything"
	@echo ""
	@echo "Development:"
	@echo "  make test      - Run integration tests"
	@echo "  make status    - Check LocalStack status"
	@echo "  make logs      - Show LocalStack logs"
	@echo "  make shell     - Open Python shell with imports"
	@echo "  make lint      - Run code linters"
	@echo ""
	@echo "Packaging:"
	@echo "  make build     - Build Nix package"
	@echo "  make package   - Alias for build"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean     - Remove test data"
	@echo ""
	@echo "Note: Requires LocalStack running (flox activate -s)"

setup:
	@./scripts/dev.sh setup

seed:
	@./scripts/dev.sh seed

test:
	@./scripts/dev.sh test

status:
	@./scripts/dev.sh status

clean:
	@./scripts/dev.sh clean

reset:
	@./scripts/dev.sh reset

logs:
	@./scripts/dev.sh logs

shell:
	@./scripts/dev.sh shell

lint:
	@./scripts/dev.sh lint

build:
	@./scripts/build-package.sh

package: build
