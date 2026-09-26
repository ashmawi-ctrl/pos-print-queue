.PHONY: install lint test quality demo

install:
	python -m pip install -e ".[dev]"

lint:
	ruff check .

test:
	pytest

quality: lint test

demo:
	pos-print-queue --db /tmp/printqueue-demo.db init
	pos-print-queue --db /tmp/printqueue-demo.db enqueue --key demo-order --text "Demo receipt"
	pos-print-queue --db /tmp/printqueue-demo.db work-once --dry-run
	pos-print-queue --db /tmp/printqueue-demo.db list --limit 5
