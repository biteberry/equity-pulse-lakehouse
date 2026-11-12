"""Builds the unified Stock Universe: NIFTY 50 + Past 1-Year Listed IPOs with Sector metadata."""

from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any

import polars as pl
import yfinance as yf

from ingestion.common.config import (
    NIFTY50_SEED_PATH,
    RECENT_IPOS_SEED_PATH,
    SUPPLY_CHAIN_CSV_PATH,
    s3_key_equity_master,
    s3_key_listed_ipos_past_1y,
    s3_key_supply_chain,
)
from ingestion.common.nse_session import NSESession
from ingestion.common.schemas import EQUITY_MASTER_SCHEMA, enforce_schema
from ingestion.common.s3_writer import S3LandingWriter

logger = logging.getLogger(__name__)


def _parse_nse_date(val: str | None) -> dt.date | None:
    if not val or not str(val).strip():
        return None
    raw = str(val).strip()
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%B-%Y", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _resolve_sector_via_yfinance(ticker: str) -> tuple[str, str]:
    """Fallback sector/industry lookup via yfinance .info."""
    try:
        info = yf.Ticker(ticker).info or {}
        sector = info.get("sector") or "Diversified"
        industry = info.get("industry") or sector
        return str(sector), str(industry)
    except Exception:
        return "Diversified", "Diversified"


def load_nifty50_seed() -> list[dict[str, Any]]:
    data = json.loads(NIFTY50_SEED_PATH.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for item in data:
        rows.append(
            {
                "nse_symbol": item["nse_symbol"],
                "ticker": item["ticker"],
                "company_name": item["company_name"],
                "sector": item["sector"],
                "industry": item.get("industry", item["sector"]),
                "universe_category": "NIFTY_50",
                "listing_date": _parse_nse_date(item.get("listing_date")),
            }
        )
    return rows


def load_recent_ipos_seed() -> list[dict[str, Any]]:
    data = json.loads(RECENT_IPOS_SEED_PATH.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for item in data:
        rows.append(
            {
                "nse_symbol": item["nse_symbol"],
                "ticker": item["ticker"],
                "company_name": item["company_name"],
                "sector": item["sector"],
                "industry": item.get("industry", item["sector"]),
                "universe_category": "RECENT_IPO_1Y",
                "listing_date": _parse_nse_date(item.get("listing_date")),
            }
        )
    return rows


def fetch_dynamic_past_1y_ipos(
    as_of_date: dt.date, nse: NSESession | None = None
) -> list[dict[str, Any]]:
    """Fetch mainboard IPOs listed on NSE in the trailing 365 days."""
    session = nse or NSESession()
    cutoff = as_of_date - dt.timedelta(days=365)
    discovered: list[dict[str, Any]] = []
    try:
        payload = session.get_json("/api/public-past-issues")
        items = payload if isinstance(payload, list) else payload.get("data", [])
        for row in items:
            if not isinstance(row, dict):
                continue
            sym = (row.get("symbol") or "").strip().upper()
            if not sym:
                continue
            # Filter out SME issues if flagged as SME
            sec_type = str(row.get("securityType") or row.get("series") or "EQ").upper()
            if "SME" in sec_type or sec_type == "SM":
                continue
            list_dt = _parse_nse_date(
                row.get("listingDate") or row.get("issueEndDate")
            )
            if list_dt and list_dt < cutoff:
                continue
            company = (
                row.get("companyName") or row.get("company") or sym
            ).strip()
            ticker = f"{sym}.NS"
            discovered.append(
                {
                    "nse_symbol": sym,
                    "ticker": ticker,
                    "company_name": company,
                    "sector": row.get("industry") or "",
                    "industry": row.get("industry") or "",
                    "universe_category": "RECENT_IPO_1Y",
                    "listing_date": list_dt,
                }
            )
    except Exception as exc:
        logger.warning(
            "Dynamic NSE past-issues lookup unavailable (%s); using seed list.",
            exc,
        )
    return discovered


def build_universe_dataframe(
    as_of_date: dt.date,
    batch_id: str,
    enrich_live_ipos: bool = True,
) -> pl.DataFrame:
    """Merge NIFTY 50 + Past 1-Year Listed IPOs into a unified Polars DataFrame with `sector`."""
    ingested_at = dt.datetime.now(dt.timezone.utc).isoformat()
    by_ticker: dict[str, dict[str, Any]] = {}

    for item in load_nifty50_seed():
        by_ticker[item["ticker"]] = {
            **item,
            "_ingested_at_utc": ingested_at,
            "_source_system": "nse_nifty50_master",
            "_batch_id": batch_id,
        }

    recent_candidates = load_recent_ipos_seed()
    if enrich_live_ipos:
        recent_candidates.extend(fetch_dynamic_past_1y_ipos(as_of_date))

    for item in recent_candidates:
        tk = item["ticker"]
        sector = item.get("sector") or ""
        industry = item.get("industry") or ""
        if not sector:
            sector, industry = _resolve_sector_via_yfinance(tk)

        if tk in by_ticker:
            by_ticker[tk]["universe_category"] = "NIFTY_50_AND_RECENT_IPO"
            if item.get("listing_date") and not by_ticker[tk].get("listing_date"):
                by_ticker[tk]["listing_date"] = item["listing_date"]
        else:
            by_ticker[tk] = {
                "ticker": tk,
                "nse_symbol": item["nse_symbol"],
                "company_name": item["company_name"],
                "sector": sector,
                "industry": industry or sector,
                "universe_category": "RECENT_IPO_1Y",
                "listing_date": item.get("listing_date"),
                "_ingested_at_utc": ingested_at,
                "_source_system": "nse_recent_ipo_1y",
                "_batch_id": batch_id,
            }

    df = pl.DataFrame(list(by_ticker.values()))
    return enforce_schema(df, EQUITY_MASTER_SCHEMA).sort(
        ["universe_category", "ticker"]
    )


def run_universe_and_reference_sync(
    writer: S3LandingWriter,
    as_of_date: dt.date,
    batch_id: str,
    enrich_live_ipos: bool = True,
) -> dict[str, Any]:
    """Build equity universe master + upload connected-companies reference data to S3."""
    universe_df = build_universe_dataframe(
        as_of_date=as_of_date,
        batch_id=batch_id,
        enrich_live_ipos=enrich_live_ipos,
    )
    s3_keys: list[str] = []

    master_key = s3_key_equity_master()
    writer.put_parquet(universe_df, master_key)
    s3_keys.append(master_key)

    recent_ipos_df = universe_df.filter(
        pl.col("universe_category").str.contains("RECENT_IPO")
    )
    listed_1y_key = s3_key_listed_ipos_past_1y(as_of_date)
    writer.put_parquet(recent_ipos_df, listed_1y_key)
    s3_keys.append(listed_1y_key)

    if SUPPLY_CHAIN_CSV_PATH.exists():
        csv_key = s3_key_supply_chain("csv")
        writer.put_file(SUPPLY_CHAIN_CSV_PATH, csv_key, content_type="text/csv")
        s3_keys.append(csv_key)

        sc_df = pl.read_csv(SUPPLY_CHAIN_CSV_PATH)
        pq_key = s3_key_supply_chain("parquet")
        writer.put_parquet(sc_df, pq_key)
        s3_keys.append(pq_key)

    return {
        "entities_processed": universe_df.height,
        "rows_written": universe_df.height,
        "s3_keys": s3_keys,
        "universe_df": universe_df,
    }
