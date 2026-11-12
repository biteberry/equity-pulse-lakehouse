"""Polars schemas and Data Contract enforcement for Phase 1.1 Landing Zone."""

from __future__ import annotations

import polars as pl

EQUITY_MASTER_SCHEMA: dict[str, pl.DataType] = {
    "ticker": pl.Utf8,
    "nse_symbol": pl.Utf8,
    "company_name": pl.Utf8,
    "sector": pl.Utf8,
    "industry": pl.Utf8,
    "universe_category": pl.Utf8,
    "listing_date": pl.Date,
    "_ingested_at_utc": pl.Utf8,
    "_source_system": pl.Utf8,
    "_batch_id": pl.Utf8,
}

OHLCV_SCHEMA: dict[str, pl.DataType] = {
    "trade_date": pl.Date,
    "ticker": pl.Utf8,
    "nse_symbol": pl.Utf8,
    "company_name": pl.Utf8,
    "sector": pl.Utf8,
    "industry": pl.Utf8,
    "universe_category": pl.Utf8,
    "listing_date": pl.Date,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "adj_close": pl.Float64,
    "volume": pl.Int64,
    "delivery_pct": pl.Float64,
    "_ingested_at_utc": pl.Utf8,
    "_source_system": pl.Utf8,
    "_batch_id": pl.Utf8,
}

DAILY_MACRO_SCHEMA: dict[str, pl.DataType] = {
    "trade_date": pl.Date,
    "indicator_code": pl.Utf8,
    "close_value": pl.Float64,
    "_ingested_at_utc": pl.Utf8,
    "_source_system": pl.Utf8,
    "_batch_id": pl.Utf8,
}

FII_DII_FLOWS_SCHEMA: dict[str, pl.DataType] = {
    "trade_date": pl.Date,
    "category": pl.Utf8,
    "buy_value_cr": pl.Float64,
    "sell_value_cr": pl.Float64,
    "net_value_cr": pl.Float64,
    "_ingested_at_utc": pl.Utf8,
    "_source_system": pl.Utf8,
    "_batch_id": pl.Utf8,
}

IPO_PIPELINE_SCHEMA: dict[str, pl.DataType] = {
    "as_of_date": pl.Date,
    "company_name": pl.Utf8,
    "symbol": pl.Utf8,
    "sector": pl.Utf8,
    "ipo_status": pl.Utf8,
    "issue_type": pl.Utf8,
    "issue_open_date": pl.Date,
    "issue_close_date": pl.Date,
    "expected_allotment_date": pl.Date,
    "expected_listing_date": pl.Date,
    "price_band_low": pl.Float64,
    "price_band_high": pl.Float64,
    "issue_size_cr": pl.Float64,
    "lot_size": pl.Int64,
    "sub_qib_times": pl.Float64,
    "sub_nii_times": pl.Float64,
    "sub_retail_times": pl.Float64,
    "sub_total_times": pl.Float64,
    "_ingested_at_utc": pl.Utf8,
    "_source_system": pl.Utf8,
    "_batch_id": pl.Utf8,
}


def enforce_schema(df: pl.DataFrame, schema: dict[str, pl.DataType]) -> pl.DataFrame:
    """Cast and order columns strictly according to the target Polars schema."""
    if df.is_empty():
        return pl.DataFrame(schema=schema)
    exprs: list[pl.Expr] = []
    for col_name, dtype in schema.items():
        if col_name in df.columns:
            exprs.append(pl.col(col_name).cast(dtype, strict=False).alias(col_name))
        else:
            exprs.append(pl.lit(None, dtype=dtype).alias(col_name))
    return df.select(exprs)
