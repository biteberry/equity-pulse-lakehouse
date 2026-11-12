"""Audit logger and GitHub Actions summary payload formatter."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import datetime as dt
import json
import logging
import time
from typing import Any

from ingestion.common.config import s3_key_audit_log
from ingestion.common.s3_writer import S3LandingWriter

logger = logging.getLogger(__name__)

SUMMARY_START_MARKER = "===SUMMARY_JSON_START==="
SUMMARY_END_MARKER = "===SUMMARY_JSON_END==="


@dataclass
class JobAuditRecord:
    job_name: str
    batch_id: str
    run_date: str
    status: str
    entities_processed: int
    rows_written: int
    s3_keys: list[str] = field(default_factory=list)
    execution_duration_sec: float = 0.0
    error_message: str | None = None
    _ingested_at_utc: str = ""


class AuditTracker:
    """Tracks multiple job executions in a CLI invocation and writes S3 audit logs."""

    def __init__(
        self, writer: S3LandingWriter, batch_id: str, run_date: dt.date
    ) -> None:
        self.writer = writer
        self.batch_id = batch_id
        self.run_date = run_date
        self.records: list[JobAuditRecord] = []

    def run_job(
        self,
        job_name: str,
        fn: Any,
        *args: Any,
        **kwargs: Any,
    ) -> JobAuditRecord:
        t0 = time.monotonic()
        ingested_at = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            result: dict[str, Any] = fn(*args, **kwargs)
            duration = round(time.monotonic() - t0, 2)
            record = JobAuditRecord(
                job_name=job_name,
                batch_id=self.batch_id,
                run_date=self.run_date.isoformat(),
                status="SUCCESS",
                entities_processed=int(result.get("entities_processed", 0)),
                rows_written=int(result.get("rows_written", 0)),
                s3_keys=list(result.get("s3_keys", [])),
                execution_duration_sec=duration,
                error_message=None,
                _ingested_at_utc=ingested_at,
            )
        except Exception as exc:
            duration = round(time.monotonic() - t0, 2)
            logger.exception("Job %s failed: %s", job_name, exc)
            record = JobAuditRecord(
                job_name=job_name,
                batch_id=self.batch_id,
                run_date=self.run_date.isoformat(),
                status="FAILED",
                entities_processed=0,
                rows_written=0,
                s3_keys=[],
                execution_duration_sec=duration,
                error_message=str(exc),
                _ingested_at_utc=ingested_at,
            )

        self.records.append(record)
        audit_key = s3_key_audit_log(self.run_date, job_name, self.batch_id)
        try:
            self.writer.put_json(asdict(record), audit_key)
        except Exception as audit_exc:
            logger.warning("Failed to upload audit log %s: %s", audit_key, audit_exc)

        return record

    def emit_stdout_summary(self) -> dict[str, Any]:
        """Print structured JSON summary markers for GitHub Actions to parse."""
        overall_status = (
            "SUCCESS"
            if all(r.status == "SUCCESS" for r in self.records)
            else "FAILED"
        )
        summary = {
            "batch_id": self.batch_id,
            "run_date": self.run_date.isoformat(),
            "bucket": self.writer.bucket,
            "overall_status": overall_status,
            "total_rows_written": sum(r.rows_written for r in self.records),
            "jobs": [asdict(r) for r in self.records],
        }
        print(SUMMARY_START_MARKER)
        print(json.dumps(summary, ensure_ascii=False))
        print(SUMMARY_END_MARKER)
        return summary
