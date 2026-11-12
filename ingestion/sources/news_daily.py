"""Daily Financial News RSS Ingestion with SHA-256 Deduplication & Stock Universe Tagging."""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
from typing import Any

import feedparser
import polars as pl

from ingestion.common.config import RSS_FEEDS, s3_key_daily_news
from ingestion.common.nse_session import NSESession
from ingestion.common.s3_writer import S3LandingWriter
from ingestion.sources.universe import build_universe_dataframe

logger = logging.getLogger(__name__)


def _classify_category(text: str) -> str:
    upper = text.upper()
    if any(
        kw in upper
        for kw in ("Q1", "Q2", "Q3", "Q4", "PROFIT", "REVENUE", "EARNINGS", "DIVIDEND", "RESULTS", "EBITDA")
    ):
        return "EARNINGS"
    if any(
        kw in upper
        for kw in ("CEO", "CFO", "BOARD", "RESIGN", "APPOINT", "CHAIRMAN", "MD ")
    ):
        return "LEADERSHIP"
    if any(
        kw in upper
        for kw in ("WAR", "SANCTION", "TARIFF", "GEOPOLITIC", "OPEC", "BORDER", "TRADE DEAL")
    ):
        return "GEOPOLITICAL"
    return "MACRO"


def _build_keyword_map(universe_df: pl.DataFrame) -> dict[str, str]:
    """Map company/symbol keywords -> canonical Yahoo ticker (`.NS`)."""
    kw_map: dict[str, str] = {}
    for row in universe_df.to_dicts():
        tk = row["ticker"]
        sym = row["nse_symbol"].upper()
        if len(sym) >= 3:
            kw_map[sym] = tk
        comp = row["company_name"].upper()
        for suffix in (" LTD.", " LTD", " LIMITED", " CORPORATION", " INDIA", " ENTERPRISES"):
            comp = comp.replace(suffix, "")
        comp = comp.strip()
        if len(comp) >= 4:
            kw_map[comp] = tk
    return kw_map


def run_news_daily(
    writer: S3LandingWriter,
    trade_date: dt.date,
    batch_id: str,
    universe_df: pl.DataFrame | None = None,
) -> dict[str, Any]:
    """Fetch financial RSS headlines, match against NIFTY 50 + 1Y IPO tickers, and upload JSONL."""
    ingested_at = dt.datetime.now(dt.timezone.utc).isoformat()
    if universe_df is None:
        universe_df = build_universe_dataframe(
            as_of_date=trade_date, batch_id=batch_id, enrich_live_ipos=False
        )
    kw_map = _build_keyword_map(universe_df)
    http = NSESession(timeout=12)

    articles_by_id: dict[str, dict[str, Any]] = {}

    for feed_cfg in RSS_FEEDS:
        try:
            raw_xml = http.get_text(feed_cfg["url"])
            parsed = feedparser.parse(raw_xml)
            for entry in parsed.entries:
                url = (entry.get("link") or "").strip()
                headline = (entry.get("title") or "").strip()
                if not url or not headline:
                    continue
                article_id = hashlib.sha256(url.encode("utf-8")).hexdigest()
                if article_id in articles_by_id:
                    continue
                summary = (entry.get("summary") or entry.get("description") or "").strip()
                combined_text = f"{headline} {summary}".upper()
                mentions = sorted(
                    {
                        ticker
                        for kw, ticker in kw_map.items()
                        if kw in combined_text
                    }
                )
                published_str = (
                    entry.get("published")
                    or entry.get("updated")
                    or ingested_at
                )
                articles_by_id[article_id] = {
                    "article_id": article_id,
                    "published_at_utc": published_str,
                    "ticker_mentions": mentions,
                    "category": _classify_category(combined_text),
                    "source": feed_cfg["source"],
                    "headline": headline,
                    "summary": summary[:1000],
                    "url": url,
                    "_ingested_at_utc": ingested_at,
                    "_source_system": feed_cfg["system"],
                    "_batch_id": batch_id,
                }
        except Exception as exc:
            logger.warning("RSS feed %s failed: %s", feed_cfg["source"], exc)

    articles = list(articles_by_id.values())
    s3_key = s3_key_daily_news(trade_date)
    writer.put_json(articles, s3_key, json_lines=True)

    return {
        "entities_processed": len(RSS_FEEDS),
        "rows_written": len(articles),
        "s3_keys": [s3_key],
    }
