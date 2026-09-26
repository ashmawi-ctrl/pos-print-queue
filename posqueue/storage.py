import sqlite3
import time
import uuid
from pathlib import Path

from .models import EnqueueResult, JobStatus, PrintJob

SCHEMA = """
CREATE TABLE IF NOT EXISTS print_jobs (
    id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    content TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    next_attempt_at REAL NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_print_jobs_ready
ON print_jobs(status, next_attempt_at, created_at);
"""


class QueueStore:
    def __init__(self, database_path: str | Path = "printqueue.db") -> None:
        self.database_path = str(database_path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            timeout=5,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    def enqueue(
        self,
        *,
        idempotency_key: str,
        content: str,
        max_attempts: int = 3,
        now: float | None = None,
    ) -> EnqueueResult:
        if not idempotency_key.strip():
            raise ValueError("idempotency_key cannot be empty")
        if not content:
            raise ValueError("content cannot be empty")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")

        timestamp = time.time() if now is None else now
        job_id = str(uuid.uuid4())

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM print_jobs WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()

            if existing is not None:
                connection.commit()
                return EnqueueResult(
                    job=self._row_to_job(existing),
                    created=False,
                )

            connection.execute(
                """
                INSERT INTO print_jobs (
                    id,
                    idempotency_key,
                    content,
                    status,
                    attempts,
                    max_attempts,
                    next_attempt_at,
                    last_error,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, 0, ?, ?, NULL, ?, ?)
                """,
                (
                    job_id,
                    idempotency_key,
                    content,
                    JobStatus.QUEUED.value,
                    max_attempts,
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
            row = connection.execute(
                "SELECT * FROM print_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            connection.commit()

        assert row is not None
        return EnqueueResult(job=self._row_to_job(row), created=True)

    def claim_next(
        self,
        *,
        now: float | None = None,
    ) -> PrintJob | None:
        timestamp = time.time() if now is None else now

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT *
                FROM print_jobs
                WHERE status IN (?, ?)
                  AND next_attempt_at <= ?
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (
                    JobStatus.QUEUED.value,
                    JobStatus.RETRY.value,
                    timestamp,
                ),
            ).fetchone()

            if row is None:
                connection.commit()
                return None

            connection.execute(
                """
                UPDATE print_jobs
                SET status = ?,
                    attempts = attempts + 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    JobStatus.PROCESSING.value,
                    timestamp,
                    row["id"],
                ),
            )
            claimed = connection.execute(
                "SELECT * FROM print_jobs WHERE id = ?",
                (row["id"],),
            ).fetchone()
            connection.commit()

        assert claimed is not None
        return self._row_to_job(claimed)

    def mark_printed(self, job_id: str, *, now: float | None = None) -> None:
        self._set_status(job_id, JobStatus.PRINTED, now=now, last_error=None)

    def mark_uncertain(
        self,
        job_id: str,
        error: str,
        *,
        now: float | None = None,
    ) -> None:
        self._set_status(
            job_id,
            JobStatus.UNCERTAIN,
            now=now,
            last_error=error,
        )

    def mark_failed(
        self,
        job_id: str,
        error: str,
        *,
        now: float | None = None,
    ) -> None:
        self._set_status(
            job_id,
            JobStatus.FAILED,
            now=now,
            last_error=error,
        )

    def schedule_retry(
        self,
        job_id: str,
        error: str,
        *,
        delay_seconds: float,
        now: float | None = None,
    ) -> None:
        if delay_seconds < 0:
            raise ValueError("delay_seconds cannot be negative")

        timestamp = time.time() if now is None else now
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE print_jobs
                SET status = ?,
                    next_attempt_at = ?,
                    last_error = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    JobStatus.RETRY.value,
                    timestamp + delay_seconds,
                    error,
                    timestamp,
                    job_id,
                ),
            )

    def recover_stale_processing(
        self,
        *,
        stale_after_seconds: float,
        now: float | None = None,
    ) -> int:
        """Move stale processing jobs back to retry after explicit recovery.

        This operation is intentionally manual. A job left in PROCESSING may
        have reached the physical printer before a worker crashed, so callers
        should choose the threshold and recovery moment deliberately.
        """
        if stale_after_seconds < 0:
            raise ValueError("stale_after_seconds cannot be negative")

        timestamp = time.time() if now is None else now
        cutoff = timestamp - stale_after_seconds
        reason = (
            "recovered stale processing job after worker interruption"
        )

        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE print_jobs
                SET status = ?,
                    next_attempt_at = ?,
                    last_error = ?,
                    updated_at = ?
                WHERE status = ?
                  AND updated_at <= ?
                """,
                (
                    JobStatus.RETRY.value,
                    timestamp,
                    reason,
                    timestamp,
                    JobStatus.PROCESSING.value,
                    cutoff,
                ),
            )
            return cursor.rowcount

    def get(self, job_id: str) -> PrintJob | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM print_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        return self._row_to_job(row) if row is not None else None

    def list(self, *, limit: int = 50) -> list[PrintJob]:
        if limit < 1:
            raise ValueError("limit must be at least 1")

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM print_jobs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [self._row_to_job(row) for row in rows]

    def _set_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        now: float | None,
        last_error: str | None,
    ) -> None:
        timestamp = time.time() if now is None else now
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE print_jobs
                SET status = ?,
                    last_error = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (status.value, last_error, timestamp, job_id),
            )

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> PrintJob:
        return PrintJob(
            id=row["id"],
            idempotency_key=row["idempotency_key"],
            content=row["content"],
            status=JobStatus(row["status"]),
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            next_attempt_at=row["next_attempt_at"],
            last_error=row["last_error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
