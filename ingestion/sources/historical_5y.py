"""5-Year Historical Data Ingestion for NIFTY 50, Past 1-Year IPOs, and Macro Benchmarks."""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

import polars as pl
import yfinance as yf

from ingestion.common.config import (
    MACRO_INDICATORS,
    s3_key_historical_macro,
    s3_key_historical_ohlcv,
)
from ingestion.common.retry import with_retry
from ingestion.common.s3_writer import S3LandingWriter
from ingestion.common.schemas import (
    DAILY_MACRO_SCHEMA,
    OHLCV_SCHEMA,
    enforce_schema,
)
from ingestion.sources.universe import build_universe_dataframe

logger = logging.getLogger(__name__)


@with_retry(max_attempts=3, delays=(2.0, 4.0, 8.0))
def _fetch_ticker_history(ticker: str, years: int) -> list[dict[str, Any]]:
    t = yf.Ticker(ticker)
    hist = t.history(period=f"{years}y", interval="1d", auto_adjust=False)
    if hist is None or hist.empty:
        return []
    hist = hist.reset_index()
    date_col = "Date" if "Date" in hist.columns else hist.columns[0]
    rows: list[dict[str, Any]] = []
    for _, r in hist.iterrows():
        dt_val = r[date_col]
        trade_date = dt_val.date() if hasattr(dt_val, "date") else dt.date.fromisoformat(str(dt_val)[:10])
        close_val = float(r.get("Close", 0.0) or 0.0)
        if close_val <= 0:
            continue
        adj_val = r.get("Adj Close", close_val)
        rows.append(
            {
                "trade_date": trade_date,
                "open": round(float(r.get("Open", close_val) or close_val), 4),
                "high": round(float(r.get("High", close_val) or close_val), 4),
                "low": round(float(r.get("Low", close_val) or close_val), 4),
                "close": round(close_val, 4),
                "adj_close": round(float(adj_val if adj_val is not None else close_val), 4),
                "volume": int(r.get("Volume", 0) or 0),
            }
        )
    return rows


def run_historical_5y_backfill(
    writer: S3LandingWriter,
    as_of_date: dt.date,
    batch_id: str,
    scope: str = "all",
    years: int = 5,
    specific_ticker: str | None = None,
) -> dict[str, Any]:
    """
    Pulls 5-year historical OHLCV + Sector for NIFTY 50 (and listing-to-date for Recent 1Y IPOs),
    plus 5-year Macro history, and writes year-partitioned Snappy Parquet to S3 Landing Zone.
    """
    ingested_at = dt.datetime.now(dt.timezone.utc).isoformat()
    universe_df = build_universe_dataframe(as_of_date=as_of_date, batch_id=batch_id)

    if specific_ticker and specific_ticker.upper() not in ("ALL", ""):
        tk_norm = specific_ticker.strip().upper()
        if not tk_norm.endswith(".NS"):
            tk_norm = f"{tk_norm}.NS"
        universe_df = universe_df.filter(pl.col("ticker") == tk_norm)
    elif scope == "nifty50":
        universe_df = universe_df.filter(
            pl.col("universe_category").str.contains("NIFTY_50")
        )
    elif scope == "recent_ipos":
        universe_df = universe_df.filter(
            pl.col("universe_category").str.contains("RECENT_IPO")
        )

    s3_keys: list[str] = []
    total_rows = 0
    entities_count = 0

    if scope in ("all", "nifty50", "recent_ipos"):
        all_rows: list[dict[str, Any]] = []
        for meta in universe_df.to_dicts():
            tk = meta["ticker"]
            try:
                hist_rows = _fetch_ticker_history(tk, years=years)
                entities_count += 1
                for hr in hist_rows:
                    all_rows.append(
                        {
                            **hr,
                            "ticker": tk,
                            "nse_symbol": meta["nse_symbol"],
                            "company_name": meta["company_name"],
                            "sector": meta["sector"],
                            "industry": meta["industry"],
                            "universe_category": meta["universe_category"],
                            "listing_date": meta["listing_date"],
                            "delivery_pct": None,
                            "_ingested_at_utc": ingested_at,
                            "_source_system": "yfinance_historical_5y",
                            "_batch_id": batch_id,
                        }
                    )
            except Exception as exc:
                logger.warning("Skipping historical fetch for %s: %s", tk, exc)

        if all_rows:
            full_df = enforce_schema(all_rows, OHLCV_SCHEMA)
            full_df = full_df.with_columns(
                pl.col("trade_date").dt.year().alias("_year"),
                pl.when(pl.col("universe_category").str.contains("NIFTY_50"))
                .then(pl.lit("NIFTY_50"))
                .otherwise(pl.lit("RECENT_IPO_1Y"))
                .alias("_universe_group"),
            )
            partitions = full_df.partition_by(
                ["_universe_group", "_year"], as_dict=True
            )
            for (u_group, yr), part_df in partitions.items():
                clean_part = enforce_schema(
                    part_df.drop(["_year", "_universe_group"]), OHLCV_SCHEMA
                ).sort(["ticker", "trade_date"])
                s3_key = s3_key_historical_ohlcv(str(u_group), int(yr))
                writer.put_parquet(clean_part, s3_key)
                s3_keys.append(s3_key)
                total_rows += clean_part.height

    if scope in ("all", "macro"):
        macro_rows: list[dict[str, Any]] = []
        for ind_code, yf_sym in MACRO_INDICATORS.items():
            try:
                hist_rows = _fetch_ticker_history(yf_sym, years=years)
                entities_count += 1
                for hr in hist_rows:
                    macro_rows.append(
                        {
                            "trade_date": hr["trade_date"],
                            "indicator_code": ind_code,
                            "close_value": hr["close"],
                            "_ingested_at_utc": ingested_at,
                            "_source_system": "yfinance_macro_5y",
                            "_batch_id": batch_id,
                        }
                    )
            except Exception as exc:
                logger.warning("Macro 5Y fetch warning for %s: %s", ind_code, exc)

        if macro_rows:
            macro_df = enforce_schema(macro_rows, DAILY_MACRO_SCHEMA).sort(
                ["indicator_code", "trade_date"]
            )
            m_key = s3_key_historical_macro()
            writer.put_parquet(macro_df, m_key)
            s3_keys.append(m_key)
            total_rows += macro_df.height

    return {
        "entities_processed": entities_count,
        "rows_written": total_rows,
        "s3_keys": s3_keys,
    }
