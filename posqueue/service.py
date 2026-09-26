import time
from dataclasses import dataclass

from .models import JobStatus, PrintJob
from .printer import PrinterClient, PrinterDeliveryError
from .storage import QueueStore


@dataclass(frozen=True)
class ProcessResult:
    job_id: str
    status: JobStatus
    message: str


class PrintQueue:
    def __init__(
        self,
        store: QueueStore,
        printer: PrinterClient,
        *,
        base_retry_delay: float = 2.0,
    ) -> None:
        if base_retry_delay < 0:
            raise ValueError("base_retry_delay cannot be negative")

        self.store = store
        self.printer = printer
        self.base_retry_delay = base_retry_delay

    def process_one(self, *, now: float | None = None) -> ProcessResult | None:
        timestamp = time.time() if now is None else now
        job = self.store.claim_next(now=timestamp)

        if job is None:
            return None

        try:
            receipt = self.printer.send(job.content)
        except PrinterDeliveryError as exc:
            return self._handle_delivery_error(job, exc, timestamp)
        except OSError as exc:
            error = PrinterDeliveryError(str(exc), may_have_printed=False)
            return self._handle_delivery_error(job, error, timestamp)

        self.store.mark_printed(job.id, now=timestamp)
        return ProcessResult(
            job_id=job.id,
            status=JobStatus.PRINTED,
            message=f"printed {receipt.bytes_sent} bytes",
        )

    def _handle_delivery_error(
        self,
        job: PrintJob,
        error: PrinterDeliveryError,
        now: float,
    ) -> ProcessResult:
        message = str(error) or error.__class__.__name__

        if error.may_have_printed:
            self.store.mark_uncertain(job.id, message, now=now)
            return ProcessResult(
                job_id=job.id,
                status=JobStatus.UNCERTAIN,
                message=(
                    "delivery became ambiguous; automatic retry stopped "
                    "to avoid a duplicate print"
                ),
            )

        if job.attempts >= job.max_attempts:
            self.store.mark_failed(job.id, message, now=now)
            return ProcessResult(
                job_id=job.id,
                status=JobStatus.FAILED,
                message="maximum attempts reached",
            )

        delay = self.base_retry_delay * (2 ** (job.attempts - 1))
        self.store.schedule_retry(
            job.id,
            message,
            delay_seconds=delay,
            now=now,
        )
        return ProcessResult(
            job_id=job.id,
            status=JobStatus.RETRY,
            message=f"scheduled retry in {delay:g}s",
        )
