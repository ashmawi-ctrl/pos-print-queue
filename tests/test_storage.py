from pathlib import Path

import pytest

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


def test_recover_stale_processing_job_moves_it_to_retry(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    job = store.enqueue(
        idempotency_key="order-crashed-worker",
        content="receipt",
        now=100.0,
    ).job

    claimed = store.claim_next(now=110.0)
    assert claimed is not None
    assert claimed.status is JobStatus.PROCESSING

    recovered = store.recover_stale_processing(
        stale_after_seconds=60,
        now=200.0,
    )

    assert recovered == 1

    updated = store.get(job.id)
    assert updated is not None
    assert updated.status is JobStatus.RETRY
    assert updated.next_attempt_at == 200.0
    assert "stale processing" in (updated.last_error or "")


def test_recovery_does_not_touch_recent_processing_job(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    job = store.enqueue(
        idempotency_key="order-active-worker",
        content="receipt",
        now=100.0,
    ).job
    store.claim_next(now=180.0)

    recovered = store.recover_stale_processing(
        stale_after_seconds=60,
        now=200.0,
    )

    assert recovered == 0
    updated = store.get(job.id)
    assert updated is not None
    assert updated.status is JobStatus.PROCESSING


def test_recovery_only_changes_processing_jobs(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    printed = store.enqueue(
        idempotency_key="already-printed",
        content="receipt",
        now=100.0,
    ).job
    store.claim_next(now=101.0)
    store.mark_printed(printed.id, now=102.0)

    recovered = store.recover_stale_processing(
        stale_after_seconds=10,
        now=200.0,
    )

    assert recovered == 0
    assert store.get(printed.id).status is JobStatus.PRINTED


def test_recovery_rejects_negative_threshold(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    with pytest.raises(ValueError):
        store.recover_stale_processing(
            stale_after_seconds=-1,
            now=200.0,
        )
