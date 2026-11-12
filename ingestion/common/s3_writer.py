"""S3 Landing Zone writer using strictly `s3:PutObject` with automatic /tmp cleanup."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import tempfile
from typing import Any
import uuid

import boto3
import polars as pl

from ingestion.common.config import AWS_REGION, get_landing_bucket

logger = logging.getLogger(__name__)


class S3LandingWriter:
    """Writes Parquet, JSON/JSONL, and CSV files to S3 using only s3:PutObject."""

    def __init__(self, bucket: str | None = None, dry_run: bool = False) -> None:
        self.bucket = bucket or get_landing_bucket()
        self.dry_run = dry_run
        self._s3 = None if dry_run else boto3.client("s3", region_name=AWS_REGION)

    def put_parquet(self, df: pl.DataFrame, s3_key: str) -> str:
        """Write Polars DataFrame as Snappy Parquet to /tmp, upload via PutObject, and purge /tmp."""
        tmp_path = Path(tempfile.gettempdir()) / f"eqpulse_{uuid.uuid4().hex}.parquet"
        try:
            df.write_parquet(tmp_path, compression="snappy")
            if self.dry_run:
                logger.info(
                    "[DRY-RUN] Would upload Parquet (%d rows) to s3://%s/%s",
                    df.height,
                    self.bucket,
                    s3_key,
                )
            else:
                with tmp_path.open("rb") as fh:
                    self._s3.put_object(
                        Bucket=self.bucket,
                        Key=s3_key,
                        Body=fh,
                        ContentType="application/octet-stream",
                    )
                logger.info(
                    "Uploaded Parquet (%d rows) to s3://%s/%s",
                    df.height,
                    self.bucket,
                    s3_key,
                )
            return f"s3://{self.bucket}/{s3_key}"
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    def put_json(
        self, payload: Any, s3_key: str, json_lines: bool = False
    ) -> str:
        """Serialize JSON or JSONL to /tmp, upload via PutObject, and purge /tmp."""
        tmp_path = Path(tempfile.gettempdir()) / f"eqpulse_{uuid.uuid4().hex}.json"
        try:
            if json_lines and isinstance(payload, list):
                content = "\n".join(
                    json.dumps(item, ensure_ascii=False, default=str)
                    for item in payload
                )
            else:
                content = json.dumps(
                    payload, indent=2, ensure_ascii=False, default=str
                )
            tmp_path.write_text(content, encoding="utf-8")

            if self.dry_run:
                logger.info(
                    "[DRY-RUN] Would upload JSON to s3://%s/%s",
                    self.bucket,
                    s3_key,
                )
            else:
                with tmp_path.open("rb") as fh:
                    self._s3.put_object(
                        Bucket=self.bucket,
                        Key=s3_key,
                        Body=fh,
                        ContentType="application/json; charset=utf-8",
                    )
                logger.info("Uploaded JSON to s3://%s/%s", self.bucket, s3_key)
            return f"s3://{self.bucket}/{s3_key}"
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    def put_file(self, local_path: Path, s3_key: str, content_type: str = "text/csv") -> str:
        """Upload an existing local file via PutObject."""
        if self.dry_run:
            logger.info(
                "[DRY-RUN] Would upload file %s to s3://%s/%s",
                local_path,
                self.bucket,
                s3_key,
            )
            return f"s3://{self.bucket}/{s3_key}"
        with local_path.open("rb") as fh:
            self._s3.put_object(
                Bucket=self.bucket,
                Key=s3_key,
                Body=fh,
                ContentType=content_type,
            )
        logger.info("Uploaded %s to s3://%s/%s", local_path.name, self.bucket, s3_key)
        return f"s3://{self.bucket}/{s3_key}"
