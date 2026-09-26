# POS Print Queue

A small reliability-focused print queue for POS environments where network drops, user retries, and raw TCP printers can cause duplicate receipts.

This project is based on a failure mode I have seen in real operations: an application reports a print attempt as failed, the user clicks print again, and both requests eventually reach the printer. The queue separates **job creation** from **delivery** and uses an idempotency key so the same order is not accidentally queued twice.

The project is being built in small steps. Current implementation details and usage examples are documented as features land.
