"""Unified CLI Entrypoint for Phase 1.1 S3 Landing Zone Ingestion."""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys

from ingestion.common.audit import AuditTracker
from ingestion.common.s3_writer import S3LandingWriter
from ingestion.sources.flows_macro import run_flows_macro
from ingestion.sources.historical_5y import run_historical_5y_backfill
from ingestion.sources.ipo_tracker import run_ipo_tracker
from ingestion.sources.market_eod import run_market_eod
from ingestion.sources.news_daily import run_news_daily
from ingestion.sources.universe import run_universe_and_reference_sync

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def _parse_trade_date(date_str: str | None) -> dt.date:
    if not date_str or date_str.strip().lower() in ("today", ""):
        return dt.datetime.now(IST).date()
    return dt.date.fromisoformat(date_str.strip())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Equity Pulse Lakehouse — Phase 1.1 Ingestion CLI"
    )
    parser.add_argument(
        "--job",
        required=True,
        choices=[
            "historical_5y",
            "daily_market_all",
            "market_eod",
            "flows_macro",
            "news_daily",
            "ipo_tracker",
            "universe_sync",
        ],
        help="Ingestion pipeline job to execute.",
    )
    parser.add_argument(
        "--date",
        default="today",
        help="Target trade/snapshot date in YYYY-MM-DD (default: today IST).",
    )
    parser.add_argument(
        "--scope",
        default="all",
        choices=["all", "nifty50", "recent_ipos", "macro"],
        help="Scope for `historical_5y` job.",
    )
    parser.add_argument(
        "--years",
        type=int,
        default=5,
        help="Number of historical years for `historical_5y` (default: 5).",
    )
    parser.add_argument(
        "--ticker",
        default="",
        help="Optional single ticker filter for `historical_5y` (e.g. RELIANCE.NS).",
    )
    parser.add_argument(
        "--bucket",
        default=None,
        help="Optional override for S3 Landing Bucket name.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and build Parquet/JSON without uploading to S3.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    args = build_parser().parse_args(argv)
    run_date = _parse_trade_date(args.date)
    now_ist = dt.datetime.now(IST)
    batch_id = f"run_{now_ist.strftime('%Y%m%d_%H%M%S')}"

    writer = S3LandingWriter(bucket=args.bucket, dry_run=args.dry_run)
    tracker = AuditTracker(writer=writer, batch_id=batch_id, run_date=run_date)

    if args.job == "historical_5y":
        tracker.run_job(
            "historical_5y",
            run_historical_5y_backfill,
            writer=writer,
            as_of_date=run_date,
            batch_id=batch_id,
            scope=args.scope,
            years=args.years,
            specific_ticker=args.ticker or None,
        )

    elif args.job == "daily_market_all":
        uni_rec = tracker.run_job(
            "universe_sync",
            run_universe_and_reference_sync,
            writer=writer,
            as_of_date=run_date,
            batch_id=batch_id,
        )
        tracker.run_job(
            "market_eod",
            run_market_eod,
            writer=writer,
            trade_date=run_date,
            batch_id=batch_id,
        )
        tracker.run_job(
            "flows_macro",
            run_flows_macro,
            writer=writer,
            trade_date=run_date,
            batch_id=batch_id,
        )
        tracker.run_job(
            "news_daily",
            run_news_daily,
            writer=writer,
            trade_date=run_date,
            batch_id=batch_id,
        )

    elif args.job == "market_eod":
        tracker.run_job(
            "market_eod",
            run_market_eod,
            writer=writer,
            trade_date=run_date,
            batch_id=batch_id,
        )

    elif args.job == "flows_macro":
        tracker.run_job(
            "flows_macro",
            run_flows_macro,
            writer=writer,
            trade_date=run_date,
            batch_id=batch_id,
        )

    elif args.job == "news_daily":
        tracker.run_job(
            "news_daily",
            run_news_daily,
            writer=writer,
            trade_date=run_date,
            batch_id=batch_id,
        )

    elif args.job == "ipo_tracker":
        tracker.run_job(
            "ipo_tracker",
            run_ipo_tracker,
            writer=writer,
            as_of_date=run_date,
            batch_id=batch_id,
        )

    elif args.job == "universe_sync":
        tracker.run_job(
            "universe_sync",
            run_universe_and_reference_sync,
            writer=writer,
            as_of_date=run_date,
            batch_id=batch_id,
        )

    summary = tracker.emit_stdout_summary()
    return 0 if summary["overall_status"] == "SUCCESS" else 1


if __name__ == "__main__":
    sys.exit(main())
