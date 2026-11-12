# Phase 1.1 Implementation Plan: Multi-Source Data Ingestion to S3 Landing Zone

**Status:** Updated with Phase 1.1 Requirements (Ready for Review)  
**Prerequisite Completed:** Phase 0 Infrastructure (`m7i-flex.large` EC2 Worker, GitHub OIDC -> AWS SSM connection, `s3://equity-pulse-landing-<account-id>/` bucket, and Cost Guardrails)  
**Objective:** Build, test, and automate the **Phase 1.1** ingestion pipelines covering **NIFTY 50 + Past 1-Year Listed IPOs**, **5-Year Historical Backfill**, **Sector Enrichment**, and **Upcoming / Completed-Unlisted IPO Tracker**, orchestrated via GitHub Actions -> AWS SSM -> EC2 -> S3 Landing Bucket with automatic EC2 shutdown and rich GitHub Actions Workflow Summaries.

---

## 1. Phase 1.1 Scope & Core Requirements

1. **Equity Universe (`NIFTY 50` + `Past 1-Year Listed IPOs`):**
   - **NIFTY 50:** All 50 constituent stocks (`RELIANCE.NS`, `TCS.NS`, `HDFCBANK.NS`, etc.).
   - **Past 1-Year Listed IPOs:** Dynamically fetched from NSE Past IPO Issues API/Archives (companies listed on NSE within the trailing 365 days) merged with a curated fallback seed list so newly listed IPOs are automatically tracked alongside NIFTY 50.
   - Tracked with an `universe_category` attribute (`NIFTY_50` | `RECENT_IPO_1Y` | `BOTH`).
2. **Sector Attribute on Every Stock Record:**
   - Every stock record across Daily OHLCV, Historical Backfill, and Master Reference data carries a normalized `sector` attribute (e.g., `Financial Services`, `Information Technology`, `Oil & Gas`, `Automobile`, `Healthcare`, `Consumer Goods`, `Metals & Mining`, `Telecom`, `Power & Utilities`, `Capital Goods`, etc.), sourced from NSE Industry Classification / `yfinance` sector metadata.
3. **5-Year Historical Data Backfill (Manual On-Demand):**
   - Pulls the **last 5 years** of daily historical data (`open`, `high`, `low`, `close`, `adj_close`, `volume`, `sector`, `universe_category`) for all **NIFTY 50** entities (and available history from listing date for Past 1-Year IPOs), plus 5 years of core Macro/Index benchmarks (`NIFTY50`, `INDIA_VIX`, `USDINR`, `CRUDE_BRENT`, `GOLD`, `SP500`).
4. **IPO Pipeline Tracker (`Upcoming IPOs` + `Completed IPOs Waiting to List`):**
   - Captures:
     - **`UPCOMING` / `OPEN`:** IPOs announced or currently open for subscription (Issue Open/Close dates, Price Band, Issue Size Cr, Lot Size, Exchange, Category).
     - **`CLOSED_AWAITING_LISTING`:** Completed IPOs whose subscription window has closed and are awaiting allotment/stock exchange listing (Subscription times QIB/NII/Retail/Total, Expected Listing Date, Issue Price).
   - Sourced from **NSE Public IPO APIs** (`/api/ipo-current-issue`, `/api/all-upcoming-issues?category=ipo`, `/api/public-past-issues`) with fallback parsing from financial IPO calendar feeds (Chittorgarh / Moneycontrol IPO tracker).

---

## 2. End-to-End Execution Lifecycle (GitHub Actions -> EC2 -> S3 -> Stop -> Summary)

Every workflow follows a strict 5-stage lifecycle so EC2 never stays running after a job finishes:

```text
+-----------------------------------------------------------------------------------+
| STAGE 1: GITHUB WORKFLOW TRIGGER (Cron Schedule or Manual workflow_dispatch)      |
|  - Authenticates to AWS via OIDC (`equity-pulse-github-actions`)                  |
|  - Resolves EC2 Worker Instance ID (`tag:Role=ingestion-worker`)                  |
+-----------------------------------------+-----------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
| STAGE 2: START EC2 & CONNECT VIA AWS SSM                                          |
|  - `aws ec2 start-instances` -> `aws ec2 wait instance-status-ok`                 |
|  - Syncs latest repo code to `/opt/equity-pulse/repo` & updates `.venv` deps      |
+-----------------------------------------+-----------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
| STAGE 3: RUN INGESTION SCRIPT & UPLOAD TO S3 LANDING BUCKET                       |
|  - Executes Python CLI on EC2 via `aws ssm send-command`                          |
|  - Fetches external data with Exponential Backoff (`2s`, `4s`, `8s`)              |
|  - Enforces Polars Data Contracts (including `sector` & audit columns)            |
|  - Uploads Parquet/JSON directly to `s3://equity-pulse-landing-<account-id>/`     |
|    over the Free S3 Gateway VPC Endpoint (`s3:PutObject` ONLY)                    |
|  - Uploads `_logs/ingestion_audit/.../audit_<batch_id>.json` to S3                |
|  - Prints structured JSON summary marker (`===SUMMARY_JSON_START===`) to stdout   |
|  - Purges all temporary files in `/tmp`                                           |
+-----------------------------------------+-----------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
| STAGE 4: STOP EC2 INSTANCE (`if: always()`)                                       |
|  - Runs unconditionally even if Stage 3 fails or times out                        |
|  - `aws ec2 stop-instances` -> `aws ec2 wait instance-stopped`                    |
+-----------------------------------------+-----------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
| STAGE 5: WRITE GITHUB WORKFLOW SUMMARY (`$GITHUB_STEP_SUMMARY`)                   |
|  - Parses structured JSON telemetry from SSM output                               |
|  - Renders Markdown table on the GitHub Actions run page showing:                 |
|    Job Status, Trade Date, Entities Processed, Rows Written, S3 Keys,             |
|    Duration (sec), and EC2 Final State (`stopped`)                                |
+-----------------------------------------------------------------------------------+
```

---

## 3. GitHub Workflows Design (3 Dedicated Workflows + Reusable Composite Action)

Using **3 dedicated workflow files** (sharing common Start/SSM/Stop/Summary steps) provides clean cron scheduling in IST, tailored manual inputs for each pipeline, and separate run history in the GitHub Actions UI:

| Workflow File | Purpose & Scope | Schedule (IST & UTC) | Manual Trigger (`workflow_dispatch`) Inputs |
| :--- | :--- | :--- | :--- |
| **A. `.github/workflows/ingest-historical-5y.yml`** | **5-Year Historical Data Backfill** for NIFTY 50 (+ listing-to-date history for Past 1Y IPOs) & Macro benchmarks | **Manual Only** (Run on demand when needed) | • `scope`: `all`, `nifty50`, `recent_ipos`, `macro`<br>• `years`: default `5`<br>• `specific_ticker`: optional (e.g., `RELIANCE.NS` or `ALL`) |
| **B. `.github/workflows/ingest-daily-market.yml`** | **Daily Market EOD**: NIFTY 50 + Past 1-Year Listed IPOs (`daily_ohlcv` with `sector` + `delivery_pct`, `fii_dii_flows`, `daily_macro`, `news_daily`) | **Daily 10:00 PM IST (Mon–Fri)**<br>Cron: `30 16 * * 1-5` (UTC)<br>*(Excludes Sat & Sun)* | • `trade_date`: default `today` (`YYYY-MM-DD`)<br>• `jobs`: `all`, `market_eod`, `flows_macro`, `news_daily` |
| **C. `.github/workflows/ingest-daily-ipo.yml`** | **Daily IPO Pipeline**: Upcoming IPOs + Open IPOs + Completed IPOs waiting to list + Refresh Past 1Y Listed IPO master list | **Daily 11:00 PM IST (Every Day)**<br>Cron: `30 17 * * *` (UTC) | • `run_date`: default `today` (`YYYY-MM-DD`) |

> **Why this schedule works well for FinOps:**
> - At **10:00 PM IST (Mon–Fri)**, NSE Bhavcopy (delivery %), FII/DII provisional figures, and global macro closes are finalized. EC2 boots for ~4 minutes and stops.
> - At **11:00 PM IST (Daily)**, IPO subscription numbers (QIB/NII/Retail end-of-day figures) and new DRHP/RHP announcements are updated. EC2 boots for ~2 minutes and stops.
> - Total monthly EC2 runtime across all scheduled runs is **< 3 hours/month** (well within the 750 hrs/month AWS Free Tier).

---

## 4. S3 Landing Bucket Layout & Phase 1.1 Data Contracts

**Bucket Name:** `s3://equity-pulse-landing-<account-id>/`

```text
s3://equity-pulse-landing-<account-id>/
├── _tfstate/
│   └── envs/dev/terraform.tfstate
├── reference_data/
│   ├── stock_universe/equity_master_latest.parquet          # NIFTY 50 + Past 1Y Listed IPOs + Sector + ISIN + Listing Date
│   └── connected_companies/supply_chain_graph.csv
├── market_data/
│   ├── historical_5y/
│   │   └── universe=<NIFTY_50|RECENT_IPO_1Y>/year=YYYY/ohlcv_YYYY.parquet
│   ├── daily_ohlcv/
│   │   └── year=YYYY/month=MM/ohlcv_YYYYMMDD.parquet
│   └── fii_dii_flows/
│       └── year=YYYY/month=MM/flows_YYYYMMDD.parquet
├── ipo_data/
│   ├── upcoming_and_unlisted/
│   │   └── year=YYYY/month=MM/ipo_pipeline_YYYYMMDD.parquet # Upcoming + Open + Completed waiting to list
│   └── listed_past_1y/
│       └── year=YYYY/month=MM/listed_ipos_YYYYMMDD.parquet  # Past 1-year listed IPO metadata & listing gains
├── macro_commodities/
│   ├── historical_5y/macro_5y.parquet
│   └── daily_macro/year=YYYY/month=MM/macro_YYYYMMDD.parquet
├── news_events/
│   └── raw_headlines/year=YYYY/month=MM/day=DD/news_YYYYMMDD.json
└── _logs/
    └── ingestion_audit/year=YYYY/month=MM/audit_<job>_YYYYMMDD_<batch_id>.json
```

### 4.1 Schema A: `daily_ohlcv` & `historical_5y` (Snappy Parquet)

Includes the new **`sector`** and **`universe_category`** attributes:

| Column Name | Data Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `trade_date` | `DATE` | No | Trading date (`YYYY-MM-DD`) |
| `ticker` | `STRING` | No | NSE Yahoo ticker (e.g., `RELIANCE.NS`, `HYUNDAI.NS`, `SWIGGY.NS`) |
| `nse_symbol` | `STRING` | No | Raw NSE symbol (e.g., `RELIANCE`, `HYUNDAI`, `SWIGGY`) |
| `company_name` | `STRING` | No | Official company name |
| `sector` | `STRING` | No | Normalized sector (e.g., `Information Technology`, `Financial Services`) |
| `industry` | `STRING` | Yes | Sub-industry classification |
| `universe_category`| `STRING` | No | `NIFTY_50`, `RECENT_IPO_1Y`, or `NIFTY_50_AND_RECENT_IPO` |
| `listing_date` | `DATE` | Yes | NSE listing date (populated especially for Past 1Y IPO stocks) |
| `open` | `FLOAT64` | No | Daily opening price |
| `high` | `FLOAT64` | No | Daily highest price |
| `low` | `FLOAT64` | No | Daily lowest price |
| `close` | `FLOAT64` | No | Daily closing price |
| `adj_close` | `FLOAT64` | Yes | Split/dividend adjusted close price |
| `volume` | `INT64` | No | Total traded share volume |
| `delivery_pct` | `FLOAT64` | Yes | Deliverable volume % from NSE Bhavcopy (`NULL` if unavailable/historical) |
| `_ingested_at_utc`| `TIMESTAMP`| No | UTC timestamp of ingestion |
| `_source_system` | `STRING` | No | `yfinance+nse_bhavcopy` |
| `_batch_id` | `STRING` | No | Unique execution batch UUID |

### 4.2 Schema B: `ipo_pipeline_YYYYMMDD.parquet` (Upcoming + Completed Waiting to List)

| Column Name | Data Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `as_of_date` | `DATE` | No | Snapshot date (`YYYY-MM-DD`) |
| `company_name` | `STRING` | No | Name of the issuing company |
| `symbol` | `STRING` | Yes | Proposed NSE/BSE symbol (if assigned) |
| `sector` | `STRING` | Yes | Company sector / industry |
| `ipo_status` | `STRING` | No | `UPCOMING` \| `OPEN_FOR_SUBSCRIPTION` \| `COMPLETED_WAITING_TO_LIST` |
| `issue_type` | `STRING` | No | `MAINBOARD` \| `SME` |
| `issue_open_date` | `DATE` | Yes | Subscription start date |
| `issue_close_date` | `DATE` | Yes | Subscription close date |
| `expected_allotment_date`| `DATE` | Yes | Tentative basis of allotment date |
| `expected_listing_date` | `DATE` | Yes | Tentative exchange listing date |
| `price_band_low` | `FLOAT64` | Yes | Lower bound of IPO price band (₹) |
| `price_band_high` | `FLOAT64` | Yes | Upper bound / cap price (₹) |
| `issue_size_cr` | `FLOAT64` | Yes | Total issue size in ₹ Crores |
| `lot_size` | `INT64` | Yes | Minimum bid lot quantity |
| `sub_qib_times` | `FLOAT64` | Yes | QIB subscription multiple (populated for open/completed IPOs) |
| `sub_nii_times` | `FLOAT64` | Yes | NII / HNI subscription multiple |
| `sub_retail_times` | `FLOAT64` | Yes | Retail subscription multiple |
| `sub_total_times` | `FLOAT64` | Yes | Overall subscription multiple |
| `_ingested_at_utc` | `TIMESTAMP`| No | UTC timestamp of ingestion |
| `_source_system` | `STRING` | No | `nse_ipo_api+ipo_calendar` |
| `_batch_id` | `STRING` | No | Unique execution batch UUID |

---

## 5. Repository Structure to Create in Phase 1.1

```text
equity-pulse-lakehouse/
├── .github/
│   ├── actions/
│   │   └── run-on-ec2/
│   │       └── action.yml                  # Reusable composite action: Start EC2 -> SSM Run -> Stop EC2 -> Write Summary
│   └── workflows/
│       ├── terraform.yml                   # (Existing) Infra CI/CD
│       ├── ec2-trigger.yml                 # (Existing) Ad-hoc EC2 control
│       ├── ingest-historical-5y.yml        # Workflow A: Manual 5-year historical backfill
│       ├── ingest-daily-market.yml         # Workflow B: Mon-Fri 10:00 PM IST + Manual (NIFTY 50 + Past 1Y IPOs)
│       └── ingest-daily-ipo.yml            # Workflow C: Daily 11:00 PM IST + Manual (Upcoming + Unlisted Completed IPOs)
├── data/
│   └── reference/
│       ├── nifty50_constituents.json       # Curated NIFTY 50 list with fallback sector & ISIN metadata
│       ├── recent_ipos_seed.json           # Seed list of past 1-year mainboard IPOs (augmented dynamically via NSE API)
│       └── supply_chain_graph.csv          # Connected companies reference graph
├── ingestion/
│   ├── requirements.txt                    # polars, pyarrow, yfinance, requests, beautifulsoup4, lxml, feedparser, boto3
│   ├── cli.py                              # Unified CLI entrypoint with JSON summary output for GitHub Actions
│   ├── common/
│   │   ├── __init__.py
│   │   ├── config.py                       # Bucket resolution, S3 partition builders, constants
│   │   ├── nse_session.py                  # NSE India HTTP client with browser headers, cookie warm-up & retry
│   │   ├── retry.py                        # Exponential backoff decorator (2s, 4s, 8s)
│   │   ├── s3_writer.py                    # Boto3 PutObject-only uploader + /tmp file cleanup
│   │   └── audit.py                        # Writes audit JSON to S3 & emits GitHub Step Summary table
│   └── sources/
│       ├── __init__.py
│       ├── universe.py                     # Builds unified Stock Universe (NIFTY 50 + Past 1Y Listed IPOs + Sector)
│       ├── historical_5y.py                # Workflow A handler: 5-year OHLCV + Sector + Macro backfill (year-partitioned)
│       ├── market_eod.py                   # Workflow B handler: Daily OHLCV + Sector + Delivery % for NIFTY 50 + 1Y IPOs
│       ├── flows_macro.py                  # Workflow B handler: Daily Macro/Commodities + FII/DII flows
│       ├── news_daily.py                   # Workflow B handler: Daily Financial RSS headlines tagged with Universe tickers
│       └── ipo_tracker.py                  # Workflow C handler: Upcoming IPOs + Completed IPOs waiting to list
└── tests/
    └── test_ingestion_schemas.py           # Unit tests for Polars schemas, sector enrichment, and S3 key generation
```

---

## 6. How Each Requirement Is Solved Technically

### 6.1 Dynamic Universe Builder (`ingestion/sources/universe.py`)
1. **NIFTY 50 + Sector:**
   - Queries NSE `equity-stockIndices?index=NIFTY%2050` (via `nse_session.py` with cookie bootstrap) and merges with `data/reference/nifty50_constituents.json`.
   - Enriches missing `sector` / `industry` fields via `yfinance.Ticker(symbol).info.get("sector")` and caches the mapping.
2. **Past 1-Year Listed IPOs:**
   - Queries NSE `/api/public-past-issues` for issues whose `listingDate` falls within `[today - 365 days, today]`.
   - Filters to Mainboard EQ listed equities, maps their NSE symbol (`<SYMBOL>.NS`), resolves their `sector` via NSE quote metadata / `yfinance`, and combines them with NIFTY 50 into a deduplicated master DataFrame saved to `s3://.../reference_data/stock_universe/equity_master_latest.parquet`.

### 6.2 5-Year Historical Data Ingestion (`ingestion/sources/historical_5y.py`)
- Fetches 5 years (`period="5y"`, `interval="1d"`) for all NIFTY 50 tickers (and full available history since listing date for Past 1-Year IPOs).
- Attaches `sector`, `industry`, `company_name`, `universe_category`, and `listing_date` to every row.
- Writes Snappy-compressed Parquet partitioned by `universe` and `year`:
  - `market_data/historical_5y/universe=NIFTY_50/year=2022/ohlcv_2022.parquet` ... `year=2026/ohlcv_2026.parquet`
  - `market_data/historical_5y/universe=RECENT_IPO_1Y/year=2025/ohlcv_2025.parquet` ... `year=2026/ohlcv_2026.parquet`
- Why partition by `year` for the 5-year backfill?
  - Keeps S3 `PUT` calls under ~15 requests (instead of 1,250+ daily files), staying well inside the AWS Free Tier (2,000 `PUT` requests/month) and making downstream Spark/Polars reads 50x faster.

### 6.3 Upcoming & Completed-Unlisted IPO Ingestion (`ingestion/sources/ipo_tracker.py`)
- Queries:
  1. **NSE Current & Upcoming Issues API:** `/api/ipo-current-issue` & `/api/all-upcoming-issues?category=ipo` -> classifies rows as `OPEN_FOR_SUBSCRIPTION` or `UPCOMING`.
  2. **NSE Recently Closed Issues / IPO Calendar:** Identifies IPOs where `issue_close_date < today` and (`listing_date IS NULL` or `listing_date > today`) -> classifies rows as `COMPLETED_WAITING_TO_LIST`.
  3. **Secondary Web/HTML Fallback:** Parses Chittorgarh / Moneycontrol Mainboard IPO status tables if NSE API omits tentative allotment/listing dates or sector tags.
- Writes to `s3://.../ipo_data/upcoming_and_unlisted/year=YYYY/month=MM/ipo_pipeline_YYYYMMDD.parquet`.

### 6.4 GitHub Workflow Summary (`$GITHUB_STEP_SUMMARY`)
At the end of every workflow run, the composite action parses the JSON summary from the EC2 SSM execution and writes a clean summary directly onto the GitHub Actions run page, for example:

```markdown
### 📊 Equity Pulse Ingestion Summary — `ingest-daily-market`
- **Batch ID:** `run_20261112_220005`
- **Execution Status:** ✅ `SUCCESS`
- **EC2 Worker Post-Run State:** 🛑 `stopped` (`i-0abc123def456`)

| Job | Entities | Rows Written | S3 Target Key | Duration | Status |
| :--- | :---: | :---: | :--- | :---: | :---: |
| `universe_sync` | 112 (50 NIFTY + 62 1Y IPOs) | 112 | `reference_data/stock_universe/equity_master_latest.parquet` | 14.2s | ✅ |
| `market_eod` | 112 | 112 | `market_data/daily_ohlcv/year=2026/month=11/ohlcv_20261112.parquet` | 28.5s | ✅ |
| `flows_macro` | 8 | 8 | `macro_commodities/daily_macro/year=2026/month=11/macro_20261112.parquet` | 6.1s | ✅ |
| `news_daily` | 45 articles | 45 | `news_events/raw_headlines/year=2026/month=11/day=12/news_20261112.json` | 9.4s | ✅ |
```

---

## 7. Implementation Sequence (Once You Approve)

1. **Step 1:** Create `data/reference/nifty50_constituents.json` (all 50 NIFTY tickers with Sector & Industry) and `data/reference/recent_ipos_seed.json`.
2. **Step 2:** Implement `ingestion/common/` (`config.py`, `retry.py`, `nse_session.py`, `s3_writer.py`, `audit.py`).
3. **Step 3:** Implement `ingestion/sources/` (`universe.py`, `historical_5y.py`, `market_eod.py`, `flows_macro.py`, `news_daily.py`, `ipo_tracker.py`) and `ingestion/cli.py`.
4. **Step 4:** Add unit tests (`tests/test_ingestion_schemas.py`) and verify schemas locally.
5. **Step 5:** Create the reusable EC2 runner `.github/actions/run-on-ec2/action.yml` and the 3 workflows:
   - `.github/workflows/ingest-historical-5y.yml` (Manual)
   - `.github/workflows/ingest-daily-market.yml` (10:00 PM IST Mon–Fri + Manual)
   - `.github/workflows/ingest-daily-ipo.yml` (11:00 PM IST Daily + Manual)
6. **Step 6:** Commit to a feature branch, open PR -> merge to `main`, and trigger a live verification run.
