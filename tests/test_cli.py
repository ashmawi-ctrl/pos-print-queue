import json
from pathlib import Path

from posqueue.cli import main
from posqueue.models import JobStatus
from posqueue.storage import QueueStore


def test_recover_stale_command_reports_recovered_jobs(
    tmp_path: Path,
    capsys,
) -> None:
    database = tmp_path / "queue.db"
    store = QueueStore(database)
    store.initialize()

    job = store.enqueue(
        idempotency_key="order-cli-recovery",
        content="receipt",
        now=100.0,
    ).job
    store.claim_next(now=110.0)

    # Make the claimed job stale without waiting in real time.
    with store._connect() as connection:
        connection.execute(
            "UPDATE print_jobs SET updated_at = ? WHERE id = ?",
            (1.0, job.id),
        )

    exit_code = main(
        [
            "--db",
            str(database),
            "recover-stale",
            "--older-than",
            "60",
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["recovered_jobs"] == 1

    updated = store.get(job.id)
    assert updated is not None
    assert updated.status is JobStatus.RETRY
