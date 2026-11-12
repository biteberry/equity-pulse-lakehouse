"""Configuration, constants, and S3 key builders for Phase 1.1 Landing Zone."""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path
import boto3

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_REF_DIR = REPO_ROOT / "data" / "reference"
NIFTY50_SEED_PATH = DATA_REF_DIR / "nifty50_constituents.json"
RECENT_IPOS_SEED_PATH = DATA_REF_DIR / "recent_ipos_seed.json"
SUPPLY_CHAIN_CSV_PATH = DATA_REF_DIR / "supply_chain_graph.csv"

AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")

# Macro & Market Benchmark Indicators
MACRO_INDICATORS: dict[str, str] = {
    "USDINR": "INR=X",
    "CRUDE_BRENT": "BZ=F",
    "GOLD": "GC=F",
    "INDIA_VIX": "^INDIAVIX",
    "NIFTY50": "^NSEI",
    "NIFTY_BANK": "^NSEBANK",
    "SP500": "^GSPC",
    "NASDAQ": "^IXIC",
}

# Financial News RSS Feeds
RSS_FEEDS: list[dict[str, str]] = [
    {
        "source": "Economic Times Markets",
        "system": "et_markets_rss",
        "url": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    },
    {
        "source": "Economic Times Stocks",
        "system": "et_stocks_rss",
        "url": "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
    },
    {
        "source": "Economic Times IPOs",
        "system": "et_ipo_rss",
        "url": "https://economictimes.indiatimes.com/markets/ipos/fpos/rssfeeds/14655708.cms",
    },
    {
        "source": "Moneycontrol Markets",
        "system": "mc_markets_rss",
        "url": "https://www.moneycontrol.com/rss/marketreports.xml",
    },
    {
        "source": "LiveMint Markets",
        "system": "livemint_markets_rss",
        "url": "https://www.livemint.com/rss/markets",
    },
]


def get_landing_bucket() -> str:
    """Resolve `equity-pulse-landing-<account-id>` dynamically via env var or STS."""
    explicit = os.getenv("EQUITY_PULSE_LANDING_BUCKET") or os.getenv("LANDING_BUCKET")
    if explicit:
        return explicit.strip()
    try:
        sts = boto3.client("sts", region_name=AWS_REGION)
        account_id = sts.get_caller_identity()["Account"]
        return f"equity-pulse-landing-{account_id}"
    except Exception:
        # Default fallback account ID from Phase 0 implementation
        return "equity-pulse-landing-307828758318"


# ---------- Deterministic S3 Landing Key Builders ----------


def s3_key_equity_master() -> str:
    return "reference_data/stock_universe/equity_master_latest.parquet"


def s3_key_supply_chain(ext: str = "csv") -> str:
    return f"reference_data/connected_companies/supply_chain_graph.{ext}"


def s3_key_historical_ohlcv(universe: str, year: int) -> str:
    return f"market_data/historical_5y/universe={universe}/year={year:04d}/ohlcv_{year:04d}.parquet"


def s3_key_historical_macro() -> str:
    return "macro_commodities/historical_5y/macro_5y.parquet"


def s3_key_daily_ohlcv(trade_date: dt.date) -> str:
    ymd = trade_date.strftime("%Y%m%d")
    return f"market_data/daily_ohlcv/year={trade_date.year:04d}/month={trade_date.month:02d}/ohlcv_{ymd}.parquet"


def s3_key_fii_dii_flows(trade_date: dt.date) -> str:
    ymd = trade_date.strftime("%Y%m%d")
    return f"market_data/fii_dii_flows/year={trade_date.year:04d}/month={trade_date.month:02d}/flows_{ymd}.parquet"


def s3_key_daily_macro(trade_date: dt.date) -> str:
    ymd = trade_date.strftime("%Y%m%d")
    return f"macro_commodities/daily_macro/year={trade_date.year:04d}/month={trade_date.month:02d}/macro_{ymd}.parquet"


def s3_key_daily_news(trade_date: dt.date) -> str:
    ymd = trade_date.strftime("%Y%m%d")
    return (
        f"news_events/raw_headlines/year={trade_date.year:04d}/"
        f"month={trade_date.month:02d}/day={trade_date.day:02d}/news_{ymd}.json"
    )


def s3_key_ipo_pipeline(as_of_date: dt.date) -> str:
    ymd = as_of_date.strftime("%Y%m%d")
    return f"ipo_data/upcoming_and_unlisted/year={as_of_date.year:04d}/month={as_of_date.month:02d}/ipo_pipeline_{ymd}.parquet"


def s3_key_listed_ipos_past_1y(as_of_date: dt.date) -> str:
    ymd = as_of_date.strftime("%Y%m%d")
    return f"ipo_data/listed_past_1y/year={as_of_date.year:04d}/month={as_of_date.month:02d}/listed_ipos_{ymd}.parquet"


def s3_key_audit_log(run_date: dt.date, job_name: str, batch_id: str) -> str:
    ymd = run_date.strftime("%Y%m%d")
    return (
        f"_logs/ingestion_audit/year={run_date.year:04d}/"
        f"month={run_date.month:02d}/audit_{job_name}_{ymd}_{batch_id}.json"
    )
