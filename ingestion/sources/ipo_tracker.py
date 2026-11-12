"""Daily IPO Pipeline Tracker: Upcoming IPOs, Open IPOs, and Completed IPOs Waiting to List."""

from __future__ import annotations

import datetime as dt
import logging
import re
from typing import Any

import polars as pl

from ingestion.common.config import s3_key_ipo_pipeline
from ingestion.common.nse_session import NSESession
from ingestion.common.s3_writer import S3LandingWriter
from ingestion.common.schemas import IPO_PIPELINE_SCHEMA, enforce_schema
from ingestion.sources.universe import run_universe_and_reference_sync

logger = logging.getLogger(__name__)


def _parse_date(val: Any) -> dt.date | None:
    if not val or not str(val).strip():
        return None
    raw = str(val).strip()
    for fmt in (
        "%Y-%m-%d",
        "%d-%b-%Y",
        "%d-%B-%Y",
        "%d/%m/%Y",
        "%b %d, %Y",
        "%d %b %Y",
    ):
        try:
            return dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _parse_float(val: Any) -> float | None:
    if val is None:
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", str(val))
    if not cleaned or cleaned in ("-", "."):
        return None
    try:
        return round(float(cleaned), 2)
    except ValueError:
        return None


def _parse_int(val: Any) -> int | None:
    f_val = _parse_float(val)
    return int(f_val) if f_val is not None else None


def _parse_price_band(val: Any) -> tuple[float | None, float | None]:
    if not val:
        return None, None
    nums = re.findall(r"\d+(?:\.\d+)?", str(val).replace(",", ""))
    if not nums:
        return None, None
    if len(nums) == 1:
        p = float(nums[0])
        return p, p
    return float(nums[0]), float(nums[-1])


def _fetch_nse_current_and_upcoming_ipos(
    as_of_date: dt.date, session: NSESession, ingested_at: str, batch_id: str
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    # 1. Current / Open IPO issues on NSE
    try:
        curr_payload = session.get_json("/api/ipo-current-issue")
        curr_items = (
            curr_payload
            if isinstance(curr_payload, list)
            else curr_payload.get("data", [])
        )
        for item in curr_items:
            if not isinstance(item, dict):
                continue
            company = str(
                item.get("companyName") or item.get("symbol") or ""
            ).strip()
            if not company:
                continue
            open_dt = _parse_date(item.get("issueStartDate"))
            close_dt = _parse_date(item.get("issueEndDate"))
            pb_low, pb_high = _parse_price_band(item.get("issuePrice"))
            sec_type = str(item.get("series") or "EQ").upper()
            issue_type = "SME" if "SM" in sec_type else "MAINBOARD"

            status = "OPEN_FOR_SUBSCRIPTION"
            if open_dt and open_dt > as_of_date:
                status = "UPCOMING"
            elif close_dt and close_dt < as_of_date:
                status = "COMPLETED_WAITING_TO_LIST"

            rows.append(
                {
                    "as_of_date": as_of_date,
                    "company_name": company,
                    "symbol": str(item.get("symbol") or "").strip().upper() or None,
                    "sector": str(item.get("industry") or "Diversified").strip(),
                    "ipo_status": status,
                    "issue_type": issue_type,
                    "issue_open_date": open_dt,
                    "issue_close_date": close_dt,
                    "expected_allotment_date": (
                        close_dt + dt.timedelta(days=1) if close_dt else None
                    ),
                    "expected_listing_date": (
                        close_dt + dt.timedelta(days=3) if close_dt else None
                    ),
                    "price_band_low": pb_low,
                    "price_band_high": pb_high,
                    "issue_size_cr": _parse_float(item.get("issueSize")),
                    "lot_size": _parse_int(item.get("lotSize") or item.get("bidLot")),
                    "sub_qib_times": _parse_float(item.get("qib")),
                    "sub_nii_times": _parse_float(item.get("nii")),
                    "sub_retail_times": _parse_float(item.get("retail")),
                    "sub_total_times": _parse_float(item.get("noOfTime")),
                    "_ingested_at_utc": ingested_at,
                    "_source_system": "nse_ipo_current",
                    "_batch_id": batch_id,
                }
            )
    except Exception as exc:
        logger.warning("NSE /api/ipo-current-issue warning: %s", exc)

    # 2. Upcoming IPO issues on NSE
    try:
        up_payload = session.get_json("/api/all-upcoming-issues?category=ipo")
        up_items = (
            up_payload
            if isinstance(up_payload, list)
            else up_payload.get("data", [])
        )
        for item in up_items:
            if not isinstance(item, dict):
                continue
            company = str(
                item.get("companyName") or item.get("symbol") or ""
            ).strip()
            if not company:
                continue
            open_dt = _parse_date(item.get("issueStartDate"))
            close_dt = _parse_date(item.get("issueEndDate"))
            pb_low, pb_high = _parse_price_band(item.get("issuePrice"))
            sec_type = str(item.get("series") or item.get("securityType") or "EQ").upper()
            issue_type = "SME" if "SM" in sec_type else "MAINBOARD"

            status = "UPCOMING"
            if close_dt and close_dt < as_of_date:
                status = "COMPLETED_WAITING_TO_LIST"
            elif open_dt and close_dt and open_dt <= as_of_date <= close_dt:
                status = "OPEN_FOR_SUBSCRIPTION"

            rows.append(
                {
                    "as_of_date": as_of_date,
                    "company_name": company,
                    "symbol": str(item.get("symbol") or "").strip().upper() or None,
                    "sector": str(item.get("industry") or "Diversified").strip(),
                    "ipo_status": status,
                    "issue_type": issue_type,
                    "issue_open_date": open_dt,
                    "issue_close_date": close_dt,
                    "expected_allotment_date": (
                        close_dt + dt.timedelta(days=1) if close_dt else None
                    ),
                    "expected_listing_date": (
                        close_dt + dt.timedelta(days=3) if close_dt else None
                    ),
                    "price_band_low": pb_low,
                    "price_band_high": pb_high,
                    "issue_size_cr": _parse_float(item.get("issueSize")),
                    "lot_size": _parse_int(item.get("lotSize")),
                    "sub_qib_times": None,
                    "sub_nii_times": None,
                    "sub_retail_times": None,
                    "sub_total_times": None,
                    "_ingested_at_utc": ingested_at,
                    "_source_system": "nse_ipo_upcoming",
                    "_batch_id": batch_id,
                }
            )
    except Exception as exc:
        logger.warning("NSE /api/all-upcoming-issues warning: %s", exc)

    # 3. Recently Closed IPOs waiting to list from /api/public-past-issues
    try:
        past_payload = session.get_json("/api/public-past-issues")
        past_items = (
            past_payload
            if isinstance(past_payload, list)
            else past_payload.get("data", [])
        )
        recent_window = as_of_date - dt.timedelta(days=15)
        for item in past_items:
            if not isinstance(item, dict):
                continue
            close_dt = _parse_date(item.get("issueEndDate"))
            list_dt = _parse_date(item.get("listingDate"))
            # Closed within the last 15 days and not yet listed (or listing date in the future)
            if close_dt and close_dt >= recent_window and (list_dt is None or list_dt > as_of_date):
                company = str(
                    item.get("companyName") or item.get("symbol") or ""
                ).strip()
                if not company:
                    continue
                open_dt = _parse_date(item.get("issueStartDate"))
                pb_low, pb_high = _parse_price_band(item.get("issuePrice") or item.get("priceRange"))
                sec_type = str(item.get("securityType") or item.get("series") or "EQ").upper()
                issue_type = "SME" if "SM" in sec_type else "MAINBOARD"
                rows.append(
                    {
                        "as_of_date": as_of_date,
                        "company_name": company,
                        "symbol": str(item.get("symbol") or "").strip().upper() or None,
                        "sector": str(item.get("industry") or "Diversified").strip(),
                        "ipo_status": "COMPLETED_WAITING_TO_LIST",
                        "issue_type": issue_type,
                        "issue_open_date": open_dt,
                        "issue_close_date": close_dt,
                        "expected_allotment_date": close_dt + dt.timedelta(days=1),
                        "expected_listing_date": list_dt or (close_dt + dt.timedelta(days=3)),
                        "price_band_low": pb_low,
                        "price_band_high": pb_high,
                        "issue_size_cr": _parse_float(item.get("issueSize")),
                        "lot_size": _parse_int(item.get("lotSize")),
                        "sub_qib_times": _parse_float(item.get("qib")),
                        "sub_nii_times": _parse_float(item.get("nii")),
                        "sub_retail_times": _parse_float(item.get("retail")),
                        "sub_total_times": _parse_float(item.get("noOfTime")),
                        "_ingested_at_utc": ingested_at,
                        "_source_system": "nse_ipo_closed_unlisted",
                        "_batch_id": batch_id,
                    }
                )
    except Exception as exc:
        logger.warning("NSE /api/public-past-issues check warning: %s", exc)

    # Deduplicate by company_name
    deduped: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = r["company_name"].upper()
        deduped[key] = r
    return list(deduped.values())


def run_ipo_tracker(
    writer: S3LandingWriter,
    as_of_date: dt.date,
    batch_id: str,
) -> dict[str, Any]:
    """
    1. Ingests Upcoming IPOs, Open IPOs, and Completed IPOs waiting to list.
    2. Refreshes the Past 1-Year Listed IPOs & Equity Universe Master in S3.
    """
    ingested_at = dt.datetime.now(dt.timezone.utc).isoformat()
    session = NSESession(timeout=15)

    pipeline_rows = _fetch_nse_current_and_upcoming_ipos(
        as_of_date=as_of_date,
        session=session,
        ingested_at=ingested_at,
        batch_id=batch_id,
    )
    pipeline_df = enforce_schema(pipeline_rows, IPO_PIPELINE_SCHEMA)
    if not pipeline_df.is_empty():
        pipeline_df = pipeline_df.sort(["ipo_status", "company_name"])

    pipeline_key = s3_key_ipo_pipeline(as_of_date)
    writer.put_parquet(pipeline_df, pipeline_key)

    # Also refresh the Past 1-Year Listed IPO master and Equity Master table
    uni_res = run_universe_and_reference_sync(
        writer=writer,
        as_of_date=as_of_date,
        batch_id=batch_id,
        enrich_live_ipos=True,
    )

    all_keys = [pipeline_key] + list(uni_res.get("s3_keys", []))
    return {
        "entities_processed": pipeline_df.height + int(uni_res.get("entities_processed", 0)),
        "rows_written": pipeline_df.height + int(uni_res.get("rows_written", 0)),
        "s3_keys": all_keys,
    }
