"""Daily Macro Indicators, Commodities, Global Indices, and NSE FII/DII Flows Ingestion."""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

import polars as pl
import yfinance as yf

from ingestion.common.config import (
    MACRO_INDICATORS,
    s3_key_daily_macro,
    s3_key_fii_dii_flows,
)
from ingestion.common.nse_session import NSESession
from ingestion.common.retry import with_retry
from ingestion.common.s3_writer import S3LandingWriter
from ingestion.common.schemas import (
    DAILY_MACRO_SCHEMA,
    FII_DII_FLOWS_SCHEMA,
    enforce_schema,
)

logger = logging.getLogger(__name__)


@with_retry(max_attempts=3, delays=(2.0, 4.0, 8.0))
def _fetch_macro_close(yf_symbol: str, trade_date: dt.date) -> tuple[dt.date, float] | None:
    start_dt = trade_date - dt.timedelta(days=7)
    end_dt = trade_date + dt.timedelta(days=1)
    t = yf.Ticker(yf_symbol)
    hist = t.history(start=start_dt.isoformat(), end=end_dt.isoformat(), interval="1d")
    if hist is None or hist.empty:
        return None
    hist = hist.reset_index()
    date_col = "Date" if "Date" in hist.columns else hist.columns[0]
    last_row = hist.iloc[-1]
    dt_val = last_row[date_col]
    obs_date = (
        dt_val.date()
        if hasattr(dt_val, "date")
        else dt.date.fromisoformat(str(dt_val)[:10])
    )
    close_val = float(last_row.get("Close", 0.0) or 0.0)
    if close_val <= 0:
        return None
    return obs_date, round(close_val, 4)


def _fetch_fii_dii_rows(
    trade_date: dt.date, ingested_at: str, batch_id: str
) -> list[dict[str, Any]]:
    session = NSESession(timeout=12)
    rows: list[dict[str, Any]] = []
    try:
        payload = session.get_json("/api/fiidiiTradeReact")
        items = payload if isinstance(payload, list) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            cat_raw = str(item.get("category") or "").upper()
            category = "FII" if "FII" in cat_raw or "FPI" in cat_raw else ("DII" if "DII" in cat_raw else cat_raw)
            if not category:
                continue
            buy_val = float(str(item.get("buyValue") or "0").replace(",", ""))
            sell_val = float(str(item.get("sellValue") or "0").replace(",", ""))
            net_val = float(str(item.get("netValue") or "0").replace(",", ""))
            rows.append(
                {
                    "trade_date": trade_date,
                    "category": category,
                    "buy_value_cr": round(buy_val, 2),
                    "sell_value_cr": round(sell_val, 2),
                    "net_value_cr": round(net_val, 2),
                    "_ingested_at_utc": ingested_at,
                    "_source_system": "nse_fii_dii_api",
                    "_batch_id": batch_id,
                }
            )
    except Exception as exc:
        logger.warning(
            "NSE FII/DII live endpoint unavailable (%s); recording empty/placeholder schema.",
            exc,
        )
    return rows


def run_flows_macro(
    writer: S3LandingWriter,
    trade_date: dt.date,
    batch_id: str,
) -> dict[str, Any]:
    """Ingest daily Macro/Commodities/Global Indices + FII/DII Institutional Flows."""
    ingested_at = dt.datetime.now(dt.timezone.utc).isoformat()
    macro_rows: list[dict[str, Any]] = []

    for ind_code, yf_sym in MACRO_INDICATORS.items():
        try:
            res = _fetch_macro_close(yf_sym, trade_date)
            if res is None:
                continue
            obs_date, close_val = res
            macro_rows.append(
                {
                    "trade_date": obs_date,
                    "indicator_code": ind_code,
                    "close_value": close_val,
                    "_ingested_at_utc": ingested_at,
                    "_source_system": "yfinance",
                    "_batch_id": batch_id,
                }
            )
        except Exception as exc:
            logger.warning("Macro indicator %s failed: %s", ind_code, exc)

    macro_df = enforce_schema(pl.DataFrame(macro_rows), DAILY_MACRO_SCHEMA).sort(
        "indicator_code"
    )
    macro_key = s3_key_daily_macro(trade_date)
    writer.put_parquet(macro_df, macro_key)

    fii_rows = _fetch_fii_dii_rows(trade_date, ingested_at, batch_id)
    fii_df = enforce_schema(pl.DataFrame(fii_rows), FII_DII_FLOWS_SCHEMA)
    fii_key = s3_key_fii_dii_flows(trade_date)
    writer.put_parquet(fii_df, fii_key)

    return {
        "entities_processed": len(MACRO_INDICATORS) + 2,
        "rows_written": macro_df.height + fii_df.height,
        "s3_keys": [macro_key, fii_key],
    }
