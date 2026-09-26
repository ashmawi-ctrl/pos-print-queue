from pathlib import Path

from posqueue.models import JobStatus
from posqueue.storage import QueueStore


def make_store(tmp_path: Path) -> QueueStore:
    store = QueueStore(tmp_path / "queue.db")
    store.initialize()
    return store


def test_enqueue_is_idempotent(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    first = store.enqueue(
        idempotency_key="order-1001",
        content="receipt",
        now=100.0,
    )
    second = store.enqueue(
        idempotency_key="order-1001",
        content="different receipt",
        now=101.0,
    )

    assert first.created is True
    assert second.created is False
    assert second.job.id == first.job.id
    assert second.job.content == "receipt"


def test_claim_next_marks_job_processing_and_increments_attempt(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    enqueued = store.enqueue(
        idempotency_key="order-1002",
        content="receipt",
        now=100.0,
    )

    claimed = store.claim_next(now=100.0)

    assert claimed is not None
    assert claimed.id == enqueued.job.id
    assert claimed.status is JobStatus.PROCESSING
    assert claimed.attempts == 1


def test_retry_job_is_not_ready_until_due(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    job = store.enqueue(
        idempotency_key="order-1003",
        content="receipt",
        now=100.0,
    ).job

    claimed = store.claim_next(now=100.0)
    assert claimed is not None

    store.schedule_retry(
        job.id,
        "printer offline",
        delay_seconds=10,
        now=100.0,
    )

    assert store.claim_next(now=109.0) is None
    assert store.claim_next(now=110.0) is not None


def test_list_returns_latest_jobs_first(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.enqueue(
        idempotency_key="older",
        content="first",
        now=100.0,
    )
    store.enqueue(
        idempotency_key="newer",
        content="second",
        now=200.0,
    )

    jobs = store.list(limit=2)

    assert [job.idempotency_key for job in jobs] == ["newer", "older"]
