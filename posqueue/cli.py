import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .printer import DryRunPrinter, TcpRawPrinter
from .service import PrintQueue
from .storage import QueueStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pos-print-queue",
        description="Queue POS print jobs with idempotency and retry protection.",
    )
    parser.add_argument(
        "--db",
        default="printqueue.db",
        help="SQLite database path (default: printqueue.db)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Initialize the queue database")

    enqueue = subparsers.add_parser("enqueue", help="Queue a print job")
    enqueue.add_argument("--key", required=True, help="Idempotency key")
    enqueue_source = enqueue.add_mutually_exclusive_group(required=True)
    enqueue_source.add_argument("--text", help="Receipt text")
    enqueue_source.add_argument("--file", help="Read receipt text from a file")
    enqueue.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="Maximum delivery attempts",
    )

    work = subparsers.add_parser("work-once", help="Process one ready job")
    work.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not connect to a printer; mark a simulated delivery instead",
    )
    work.add_argument("--host", help="Printer IP or hostname")
    work.add_argument("--port", type=int, default=9100)
    work.add_argument("--timeout", type=float, default=3.0)

    listing = subparsers.add_parser("list", help="List recent print jobs")
    listing.add_argument("--limit", type=int, default=20)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = QueueStore(args.db)

    if args.command == "init":
        store.initialize()
        print(f"initialized {args.db}")
        return 0

    store.initialize()

    if args.command == "enqueue":
        content = args.text
        if args.file:
            content = Path(args.file).read_text(encoding="utf-8")

        assert content is not None
        result = store.enqueue(
            idempotency_key=args.key,
            content=content,
            max_attempts=args.max_attempts,
        )
        print(
            json.dumps(
                {
                    "created": result.created,
                    "job": _job_to_dict(result.job),
                },
                indent=2,
            )
        )
        return 0

    if args.command == "work-once":
        if args.dry_run:
            printer = DryRunPrinter()
        else:
            if not args.host:
                raise SystemExit("--host is required unless --dry-run is used")
            printer = TcpRawPrinter(
                args.host,
                args.port,
                timeout_seconds=args.timeout,
            )

        result = PrintQueue(store, printer).process_one()
        if result is None:
            print("no ready jobs")
            return 0

        print(
            json.dumps(
                {
                    "job_id": result.job_id,
                    "status": result.status.value,
                    "message": result.message,
                },
                indent=2,
            )
        )
        return 0

    if args.command == "list":
        jobs = [_job_to_dict(job) for job in store.list(limit=args.limit)]
        print(json.dumps(jobs, indent=2))
        return 0

    raise AssertionError(f"unexpected command: {args.command}")


def _job_to_dict(job) -> dict:
    data = asdict(job)
    data["status"] = job.status.value
    return data


if __name__ == "__main__":
    raise SystemExit(main())
