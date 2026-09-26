from pathlib import Path

from posqueue.models import JobStatus
from posqueue.printer import PrinterDeliveryError, PrintReceipt
from posqueue.service import PrintQueue
from posqueue.storage import QueueStore


class SuccessfulPrinter:
    def send(self, content: str) -> PrintReceipt:
        return PrintReceipt(bytes_sent=len(content.encode("utf-8")))


class OfflinePrinter:
    def send(self, content: str) -> PrintReceipt:
        raise PrinterDeliveryError(
            "connection refused",
            may_have_printed=False,
        )


class AmbiguousPrinter:
    def send(self, content: str) -> PrintReceipt:
        raise PrinterDeliveryError(
            "connection dropped after send started",
            may_have_printed=True,
        )


def make_store(tmp_path: Path) -> QueueStore:
    store = QueueStore(tmp_path / "queue.db")
    store.initialize()
    return store


def test_successful_job_is_marked_printed(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    job = store.enqueue(
        idempotency_key="order-2001",
        content="receipt",
        now=100.0,
    ).job

    result = PrintQueue(store, SuccessfulPrinter()).process_one(now=100.0)

    assert result is not None
    assert result.status is JobStatus.PRINTED
    assert store.get(job.id).status is JobStatus.PRINTED


def test_pre_send_failure_is_scheduled_for_retry(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    job = store.enqueue(
        idempotency_key="order-2002",
        content="receipt",
        max_attempts=3,
        now=100.0,
    ).job

    result = PrintQueue(
        store,
        OfflinePrinter(),
        base_retry_delay=5.0,
    ).process_one(now=100.0)

    assert result is not None
    assert result.status is JobStatus.RETRY

    updated = store.get(job.id)
    assert updated is not None
    assert updated.status is JobStatus.RETRY
    assert updated.next_attempt_at == 105.0


def test_ambiguous_delivery_stops_automatic_retry(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    job = store.enqueue(
        idempotency_key="order-2003",
        content="receipt",
        now=100.0,
    ).job

    result = PrintQueue(store, AmbiguousPrinter()).process_one(now=100.0)

    assert result is not None
    assert result.status is JobStatus.UNCERTAIN

    updated = store.get(job.id)
    assert updated is not None
    assert updated.status is JobStatus.UNCERTAIN


def test_job_fails_after_max_attempts(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    job = store.enqueue(
        idempotency_key="order-2004",
        content="receipt",
        max_attempts=1,
        now=100.0,
    ).job

    result = PrintQueue(store, OfflinePrinter()).process_one(now=100.0)

    assert result is not None
    assert result.status is JobStatus.FAILED
    assert store.get(job.id).status is JobStatus.FAILED
