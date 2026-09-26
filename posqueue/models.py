from dataclasses import dataclass
from enum import StrEnum


class JobStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    RETRY = "retry"
    PRINTED = "printed"
    UNCERTAIN = "uncertain"
    FAILED = "failed"


@dataclass(frozen=True)
class PrintJob:
    id: str
    idempotency_key: str
    content: str
    status: JobStatus
    attempts: int
    max_attempts: int
    next_attempt_at: float
    last_error: str | None
    created_at: float
    updated_at: float


@dataclass(frozen=True)
class EnqueueResult:
    job: PrintJob
    created: bool
