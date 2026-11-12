"""Daily Market EOD Ingestion: NIFTY 50 + Past 1-Year Listed IPOs with Sector & NSE Delivery %."""

from __future__ import annotations

import csv
import datetime as dt
import io
import logging
from typing import Any

import polars as pl
import yfinance as yf

from ingestion.common.config import s3_key_daily_ohlcv
from ingestion.common.nse_session import NSESession
from ingestion.common.retry import with_retry
from ingestion.common.s3_writer import S3LandingWriter
from ingestion.common.schemas import OHLCV_SCHEMA, enforce_schema
from ingestion.sources.universe import build_universe_dataframe

logger = logging.getLogger(__name__)


def fetch_nse_delivery_pct_map(trade_date: dt.date) -> dict[str, float]:
    """
    Fetch NSE full daily Bhavcopy CSV (`sec_bhavdata_full_DDMMYYYY.csv`) and return
    a mapping of `NSE_SYMBOL -> delivery_pct`. Gracefully returns `{}` on holidays/404.
    """
    ddmmyyyy = trade_date.strftime("%d%m%Y")
    url = f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{ddmmyyyy}.csv"
    session = NSESession(timeout=12)
    delivery_map: dict[str, float] = {}
    try:
        csv_text = session.get_text(url)
        reader = csv.DictReader(io.StringIO(csv_text))
        for row in reader:
            cleaned = {str(k).strip().upper(): str(v).strip() for k, v in row.items() if k}
            series = cleaned.get("SERIES", "")
            if series != "EQ":
                continue
            sym = cleaned.get("SYMBOL", "")
            deliv_raw = cleaned.get("DELIV_PER", "")
            if sym and deliv_raw and deliv_raw != "-":
                try:
                    delivery_map[sym] = round(float(deliv_raw), 2)
                except ValueError:
                    continue
    except Exception as exc:
        logger.info(
            "NSE Bhavcopy delivery_pct not available for %s (%s); defaulting to NULL.",
            trade_date.isoformat(),
            exc,
        )
    return delivery_map


@with_retry(max_attempts=3, delays=(2.0, 4.0, 8.0))
def _fetch_latest_eod_bar(ticker: str, target_date: dt.date) -> dict[str, Any] | None:
    start_dt = target_date - dt.timedelta(days=7)
    end_dt = target_date + dt.timedelta(days=1)
    t = yf.Ticker(ticker)
    hist = t.history(
        start=start_dt.isoformat(),
        end=end_dt.isoformat(),
        interval="1d",
        auto_adjust=False,
    )
    if hist is None or hist.empty:
        return None
    hist = hist.reset_index()
    date_col = "Date" if "Date" in hist.columns else hist.columns[0]
    last_row = hist.iloc[-1]
    dt_val = last_row[date_col]
    bar_date = (
        dt_val.date()
        if hasattr(dt_val, "date")
        else dt.date.fromisoformat(str(dt_val)[:10])
    )
    close_val = float(last_row.get("Close", 0.0) or 0.0)
    if close_val <= 0:
        return None
    adj_val = last_row.get("Adj Close", close_val)
    return {
        "trade_date": bar_date,
        "open": round(float(last_row.get("Open", close_val) or close_val), 4),
        "high": round(float(last_row.get("High", close_val) or close_val), 4),
        "low": round(float(last_row.get("Low", close_val) or close_val), 4),
        "close": round(close_val, 4),
        "adj_close": round(float(adj_val if adj_val is not None else close_val), 4),
        "volume": int(last_row.get("Volume", 0) or 0),
    }


def run_market_eod(
    writer: S3LandingWriter,
    trade_date: dt.date,
    batch_id: str,
    universe_df: pl.DataFrame | None = None,
) -> dict[str, Any]:
    """Ingest daily OHLCV + Sector + Delivery % for NIFTY 50 + Past 1-Year Listed IPOs."""
    ingested_at = dt.datetime.now(dt.timezone.utc).isoformat()
    if universe_df is None:
        universe_df = build_universe_dataframe(as_of_date=trade_date, batch_id=batch_id)

    delivery_map = fetch_nse_delivery_pct_map(trade_date)
    records: list[dict[str, Any]] = []

    for meta in universe_df.to_dicts():
        tk = meta["ticker"]
        sym = meta["nse_symbol"]
        try:
            bar = _fetch_latest_eod_bar(tk, trade_date)
            if not bar:
                continue
            records.append(
                {
                    "trade_date": bar["trade_date"],
                    "ticker": tk,
                    "nse_symbol": sym,
                    "company_name": meta["company_name"],
                    "sector": meta["sector"],
                    "industry": meta["industry"],
                    "universe_category": meta["universe_category"],
                    "listing_date": meta["listing_date"],
                    "open": bar["open"],
                    "high": bar["high"],
                    "low": bar["low"],
                    "close": bar["close"],
                    "adj_close": bar["adj_close"],
                    "volume": bar["volume"],
                    "delivery_pct": delivery_map.get(sym),
                    "_ingested_at_utc": ingested_at,
                    "_source_system": "yfinance+nse_bhavcopy",
                    "_batch_id": batch_id,
                }
            )
        except Exception as exc:
            logger.warning("Failed EOD fetch for %s: %s", tk, exc)

    df = enforce_schema(records, OHLCV_SCHEMA).sort("ticker")
    s3_key = s3_key_daily_ohlcv(trade_date)
    writer.put_parquet(df, s3_key)

    return {
        "entities_processed": universe_df.height,
        "rows_written": df.height,
        "s3_keys": [s3_key],
    }
