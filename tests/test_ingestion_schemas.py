"""Unit tests for Phase 1.1 S3 key builders, Universe & Sector enrichment, and Polars schemas."""

from __future__ import annotations

import datetime as dt
import polars as pl

from ingestion.common.config import (
    s3_key_daily_macro,
    s3_key_daily_news,
    s3_key_daily_ohlcv,
    s3_key_equity_master,
    s3_key_fii_dii_flows,
    s3_key_historical_ohlcv,
    s3_key_ipo_pipeline,
    s3_key_listed_ipos_past_1y,
)
from ingestion.common.schemas import (
    DAILY_MACRO_SCHEMA,
    EQUITY_MASTER_SCHEMA,
    FII_DII_FLOWS_SCHEMA,
    IPO_PIPELINE_SCHEMA,
    OHLCV_SCHEMA,
    enforce_schema,
)
from ingestion.sources.universe import (
    build_universe_dataframe,
    load_nifty50_seed,
    load_recent_ipos_seed,
)


def test_seed_files_have_sector_and_valid_tickers() -> None:
    nifty = load_nifty50_seed()
    assert len(nifty) >= 50
    for item in nifty:
        assert item["ticker"].endswith(".NS")
        assert item["sector"], f"Missing sector for {item['ticker']}"
        assert item["universe_category"] == "NIFTY_50"

    recent_ipos = load_recent_ipos_seed()
    assert len(recent_ipos) >= 10
    for item in recent_ipos:
        assert item["ticker"].endswith(".NS")
        assert item["sector"], f"Missing sector for IPO {item['ticker']}"
        assert item["universe_category"] == "RECENT_IPO_1Y"


def test_build_universe_dataframe_schema() -> None:
    df = build_universe_dataframe(
        as_of_date=dt.date(2026, 11, 12),
        batch_id="test_batch_01",
        enrich_live_ipos=False,
    )
    assert df.height >= 60
    assert list(df.columns) == list(EQUITY_MASTER_SCHEMA.keys())
    assert df.filter(pl.col("sector").is_null() | (pl.col("sector") == "")).height == 0


def test_s3_partition_key_formats() -> None:
    d = dt.date(2026, 11, 12)
    assert s3_key_equity_master() == "reference_data/stock_universe/equity_master_latest.parquet"
    assert s3_key_historical_ohlcv("NIFTY_50", 2025) == "market_data/historical_5y/universe=NIFTY_50/year=2025/ohlcv_2025.parquet"
    assert s3_key_daily_ohlcv(d) == "market_data/daily_ohlcv/year=2026/month=11/ohlcv_20261112.parquet"
    assert s3_key_fii_dii_flows(d) == "market_data/fii_dii_flows/year=2026/month=11/flows_20261112.parquet"
    assert s3_key_daily_macro(d) == "macro_commodities/daily_macro/year=2026/month=11/macro_20261112.parquet"
    assert s3_key_daily_news(d) == "news_events/raw_headlines/year=2026/month=11/day=12/news_20261112.json"
    assert s3_key_ipo_pipeline(d) == "ipo_data/upcoming_and_unlisted/year=2026/month=11/ipo_pipeline_20261112.parquet"
    assert s3_key_listed_ipos_past_1y(d) == "ipo_data/listed_past_1y/year=2026/month=11/listed_ipos_20261112.parquet"


def test_enforce_schemas_with_sample_rows() -> None:
    ohlcv_sample = pl.DataFrame(
        [
            {
                "trade_date": dt.date(2026, 11, 12),
                "ticker": "RELIANCE.NS",
                "nse_symbol": "RELIANCE",
                "company_name": "Reliance Industries Ltd.",
                "sector": "Oil, Gas & Consumable Fuels",
                "industry": "Refineries & Marketing",
                "universe_category": "NIFTY_50",
                "listing_date": None,
                "open": 1280.0,
                "high": 1295.5,
                "low": 1275.0,
                "close": 1290.25,
                "adj_close": 1290.25,
                "volume": 12500000,
                "delivery_pct": 62.4,
                "_ingested_at_utc": "2026-11-12T16:30:00Z",
                "_source_system": "yfinance+nse_bhavcopy",
                "_batch_id": "run_test",
            }
        ]
    )
    enforced_ohlcv = enforce_schema(ohlcv_sample, OHLCV_SCHEMA)
    assert enforced_ohlcv.height == 1
    assert enforced_ohlcv["sector"][0] == "Oil, Gas & Consumable Fuels"

    ipo_sample = pl.DataFrame(
        [
            {
                "as_of_date": dt.date(2026, 11, 12),
                "company_name": "Example Tech India Ltd.",
                "symbol": "EXTECH",
                "sector": "Information Technology",
                "ipo_status": "COMPLETED_WAITING_TO_LIST",
                "issue_type": "MAINBOARD",
                "issue_open_date": dt.date(2026, 11, 8),
                "issue_close_date": dt.date(2026, 11, 10),
                "expected_allotment_date": dt.date(2026, 11, 11),
                "expected_listing_date": dt.date(2026, 11, 13),
                "price_band_low": 480.0,
                "price_band_high": 500.0,
                "issue_size_cr": 2500.0,
                "lot_size": 30,
                "sub_qib_times": 42.5,
                "sub_nii_times": 18.2,
                "sub_retail_times": 6.4,
                "sub_total_times": 21.8,
                "_ingested_at_utc": "2026-11-12T17:30:00Z",
                "_source_system": "nse_ipo_closed_unlisted",
                "_batch_id": "run_test",
            }
        ]
    )
    enforced_ipo = enforce_schema(ipo_sample, IPO_PIPELINE_SCHEMA)
    assert enforced_ipo.height == 1
    assert enforced_ipo["ipo_status"][0] == "COMPLETED_WAITING_TO_LIST"

    empty_macro = enforce_schema(pl.DataFrame(), DAILY_MACRO_SCHEMA)
    assert empty_macro.height == 0
    assert list(empty_macro.columns) == list(DAILY_MACRO_SCHEMA.keys())

    empty_flows = enforce_schema(pl.DataFrame(), FII_DII_FLOWS_SCHEMA)
    assert empty_flows.height == 0
    assert list(empty_flows.columns) == list(FII_DII_FLOWS_SCHEMA.keys())
