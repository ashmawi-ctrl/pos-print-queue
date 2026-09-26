# POS Print Queue

[![quality](https://github.com/ashmawi-ctrl/pos-print-queue/actions/workflows/quality.yml/badge.svg)](https://github.com/ashmawi-ctrl/pos-print-queue/actions/workflows/quality.yml)

A small reliability-focused print queue for POS environments where network drops, user retries, and raw TCP printers can cause duplicate receipts.

I built this around a failure mode I have seen in production support: the application reports a print attempt as failed, the user clicks **Print** again, and both requests eventually reach the printer. The important problem is not just retrying — it is knowing **when retrying is safe**.

## What the queue does

- stores print jobs in SQLite
- requires an idempotency key such as an order or receipt ID
- returns the existing job when the same key is queued again
- claims one ready job at a time
- retries failures that happened before delivery started
- uses exponential backoff between retries
- stops automatic retries when delivery becomes ambiguous
- exposes a CLI for local use and testing
- supports raw TCP printers, commonly on port 9100
- includes a dry-run printer for safe development
- runs tests and linting in GitHub Actions
- supports explicit recovery of jobs abandoned in `processing` after worker crashes

## Why there is an `uncertain` state

A raw TCP printer normally does not provide application-level exactly-once delivery.

There is an important difference between:

1. **Connection failed before sending**  
   Retrying is usually safe.

2. **The connection dropped after sending started**  
   The printer may already have received enough data to print. Retrying automatically may create a duplicate.

For the second case the job moves to `uncertain` instead of being retried automatically.

That does not magically provide exactly-once printing, but it avoids pretending the application knows more than it actually does.

## Job lifecycle

```text
queued
   |
   v
processing ---------> printed
   |
   +---- safe failure ----> retry ----> processing
   |
   +---- max attempts ----> failed
   |
   +---- ambiguous send --> uncertain
```

## Install

Python 3.11+ is required.

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -e ".[dev]"
```

## Initialize a queue

```bash
pos-print-queue --db printqueue.db init
```

## Enqueue a receipt

```bash
pos-print-queue --db printqueue.db enqueue \
  --key order-10042 \
  --text "Order #10042\n2 x Coffee\nTotal: 320 EGP"
```

Running the same command again with the same key does **not** create another job.

You can also queue a text file:

```bash
pos-print-queue --db printqueue.db enqueue \
  --key order-10043 \
  --file examples/sample_receipt.txt
```

## Process a job safely in development

```bash
pos-print-queue --db printqueue.db work-once --dry-run
```

This uses the in-memory dry-run printer and makes no network connection.

## Send to a raw TCP printer

```bash
pos-print-queue --db printqueue.db work-once \
  --host 192.168.1.50 \
  --port 9100 \
  --timeout 3
```

The TCP client sends UTF-8 bytes as-is. Real POS deployments may need ESC/POS formatting or vendor-specific commands before this layer.

## Inspect jobs

```bash
pos-print-queue --db printqueue.db list --limit 20
```

Example output:

```json
[
  {
    "id": "4bb2...",
    "idempotency_key": "order-10042",
    "content": "Order #10042\n...",
    "status": "printed",
    "attempts": 1,
    "max_attempts": 3,
    "next_attempt_at": 0,
    "last_error": null,
    "created_at": 1780000000.0,
    "updated_at": 1780000001.2
  }
]
```

## Recover jobs after a worker crash

A worker marks a job as `processing` before it talks to the printer. If that
worker process crashes before writing the final state, the job can otherwise
remain stuck indefinitely.

Recovery is deliberately **not automatic** because a crashed worker may have
sent data to the physical printer before it disappeared. An operator can
explicitly recover jobs that have been stuck longer than a chosen threshold:

```bash
pos-print-queue --db printqueue.db recover-stale --older-than 300
```

That moves only stale `processing` jobs back to `retry`, records a recovery
reason, and makes them immediately eligible for a future worker run. Recently
claimed jobs and jobs in terminal states are left unchanged.

## Retry behavior

For a safe pre-send failure, retries use exponential backoff:

```text
attempt 1 -> 2 seconds
attempt 2 -> 4 seconds
attempt 3 -> 8 seconds
...
```

The delay is configurable in `PrintQueue`.

## Project structure

```text
posqueue/
  cli.py       command-line interface
  models.py    job states and data models
  printer.py   printer client and delivery errors
  service.py   worker and retry decisions
  storage.py   SQLite persistence and idempotency

tests/
  test_printer.py
  test_service.py
  test_storage.py
```

## Quality checks

```bash
ruff check .
pytest
```

Both checks also run automatically in GitHub Actions.

## Design limitation

The idempotency key prevents the **application** from creating duplicate jobs for the same logical receipt. It cannot guarantee that a physical printer will never print twice after an ambiguous network failure.

True end-to-end exactly-once behavior would require printer-side acknowledgements or another protocol that supports a durable receipt ID.

More detail is in [docs/delivery-semantics.md](docs/delivery-semantics.md).

## Next improvements

- operator command to resolve `uncertain` jobs
- ESC/POS renderer
- printer health checks
- structured operational metrics
- long-running worker mode

## License

MIT
