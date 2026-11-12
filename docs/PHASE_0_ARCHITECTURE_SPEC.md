# Phase 0 Architecture Specification: Stock Market AI Lakehouse (Bronze Ingestion Layer)

**Document Version:** 1.0  
**Status:** Draft / Ready for Implementation  
**Target Budget:** ₹200 – ₹500 INR / Month (~$2.50 – $6.00 USD)  
**Target Region:** `ap-south-1` (Mumbai)  

---

## 1. Executive Summary & Objective

The objective of **Phase 0** is to build an automated, low-cost, fault-tolerant data ingestion pipeline that collects multi-factor financial data and stores it in an immutable **Bronze Landing Zone** on Amazon S3. 

Following a **Spec-Driven Development** approach, this document defines the system boundaries, infrastructure constraints, data contracts, storage partitions, and acceptance criteria required before writing ingestion code.

### Out of Scope for Phase 0
* Technical indicator calculations (RSI, MACD, Moving Averages) — *Deferred to Phase 1 (Silver Layer)*
* AI sentiment scoring (FinBERT/LLMs) — *Deferred to Phase 1 (Silver Layer)*
* ML model training and inference — *Deferred to Phase 2 (Gold/ML Layer)*

---

## 2. System Architecture & Data Flow

```text
+-----------------------------------------------------------------------------------+

| 1. EXTERNAL DATA SOURCES                                                          |
|  [Market OHLCV & VIX]   [FII/DII & Global Indices]   [Macro: FX, Oil, Gold]       |
|  [News & RSS Feeds]     [Quarterly/Monthly Filings]  [Connected Companies Graph]  |
+-----------------------------------------+-----------------------------------------+
                                          | (HTTPS / REST / CSV / RSS)
                                          v
+-----------------------------------------------------------------------------------+

| 2. CI/CD & STATELESS COMPUTE (GITHUB -> AWS EC2 FREE TIER)                        |
|                                                                                   |
|  [GitHub Repo (main)] --(GitHub Actions SSH)--> [AWS EC2: t2.micro / t3.micro]    |
|                                                  - Ubuntu 24.04 LTS               |
|                                                  - 1 vCPU, 1GB RAM + 2GB Swap     |
|                                                  - Linux Crontab (IST Schedule)   |
|                                                  - Polars + Boto3 + IAM Role      |
+-----------------------------------------+-----------------------------------------+
                                          | (Boto3 PutObject - IAM Instance Profile)
                                          v
+-----------------------------------------------------------------------------------+

| 3. LAKEHOUSE STORAGE: BRONZE LANDING ZONE (AMAZON S3)                             |
|                                                                                   |
|  s3://equity-pulse-landing-<account-id>/                                          |
|   ├── market_data/          (Parquet - Hive Partitioned)                          |
|   ├── macro_commodities/    (Parquet - Hive Partitioned)                          |
|   ├── news_events/          (JSON - Hive Partitioned)                             |
|   ├── fundamentals/         (JSON - Ticker Partitioned)                           |
|   └── reference_data/       (CSV/JSON - Static Reference)                         |
+-----------------------------------------------------------------------------------+
```

---

## 3. Infrastructure & FinOps Specification

To strictly stay within the **₹200 – ₹500/month** budget, all infrastructure components must adhere to the following constraints:

| Component | AWS / Tool Specification | Cost Guardrail & Configuration | Est. Monthly Cost |
| :--- | :--- | :--- | :--- |
| **Compute** | AWS EC2 `t2.micro` or `t3.micro` | 12-month Free Tier eligible (750 hrs/mo). Configure **2 GB Linux Swap file** to prevent OOM errors on 1 GB RAM. | ₹0 (Free Tier) |
| **Block Storage** | Amazon EBS `gp3` | Allocate **20 GB** max (Free Tier cap is 30 GB). Zero local data retention; purge `/tmp` after each S3 upload. | ₹0 (Free Tier) |
| **Object Storage** | Amazon S3 Standard | Enable **S3 Intelligent-Tiering** or Lifecycle rule to transition raw Bronze files older than 90 days to Glacier Instant Retrieval. | ₹10 – ₹30 |
| **Security / IAM** | IAM Instance Profile | Attach EC2 role with least-privilege (`s3:PutObject`, `s3:ListBucket` on Bronze bucket only). No hardcoded AWS keys. | ₹0 |
| **CI/CD & Repo** | GitHub + GitHub Actions | Auto-deploy code to EC2 via SSH on `git push` to `main`. Store third-party API keys in GitHub Secrets / `.env`. | ₹0 |
| **Orchestration** | Linux `crontab` | Native OS cron jobs scheduled in IST (`Asia/Kolkata`). Avoids managed Airflow/Step Functions overhead. | ₹0 |
| **Cost Monitoring**| AWS Budgets | Configure billing alerts at **₹250 (50%)** and **₹450 (90%)** thresholds. | ₹0 |

---

## 4. Data Ingestion & Source Specification

### 4.1 Ingestion Schedules (IST Timezone)

| Pipeline Job ID | Data Domain | Source Examples | Frequency | Cron Schedule (IST) | Output Format |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `job_market_eod` | Daily OHLCV, Delivery %, India VIX | `yfinance`, NSE Bhavcopy | Mon–Fri (EOD) | `0 17 * * 1-5` | Snappy Parquet |
| `job_flows_macro`| FII/DII Net Flows, Global Indices, USD/INR, Crude, Gold | `yfinance`, NSE Reports | Mon–Fri (EOD) | `15 17 * * 1-5` | Snappy Parquet |
| `job_news_daily` | Financial News, RSS, Geopolitical & Leadership Events | Moneycontrol/ET RSS, NewsAPI | Daily | `0 18 * * *` | UTF-8 JSON |
| `job_fundamentals`| Quarterly Results, Balance Sheet, CapEx & R&D Filings | `yfinance` financials, Exchange Filings | Weekly (Sat) | `0 10 * * 6` | UTF-8 JSON |
| `job_reference` | Connected Companies (Suppliers, Subsidiaries, Peers) | Curated CSV/JSON in Git | On Git Push | Event-driven | CSV / Parquet |

---

## 5. S3 Storage Layout & Data Contracts (Bronze Layer)

### 5.1 S3 Bucket Naming & Hive Partitioning
**Bucket Name:** `s3://equity-pulse-landing-<unique-id>/`

```text
s3://equity-pulse-landing-<unique-id>/
├── market_data/
│   ├── daily_ohlcv/year=YYYY/month=MM/ohlcv_YYYYMMDD.parquet
│   └── fii_dii_flows/year=YYYY/month=MM/flows_YYYYMMDD.parquet
├── macro_commodities/
│   └── daily_macro/year=YYYY/month=MM/macro_YYYYMMDD.parquet
├── news_events/
│   ├── raw_headlines/year=YYYY/month=MM/day=DD/news_YYYYMMDD.json
│   └── corporate_events/year=YYYY/month=MM/events_YYYYMMDD.json
├── fundamentals/
│   └── quarterly_financials/ticker=<SYMBOL>/financials_YYYYMMDD.json
├── reference_data/
│   └── connected_companies/supply_chain_graph.csv
└── _logs/
    └── ingestion_audit/year=YYYY/month=MM/audit_YYYYMMDD.json
```

### 5.2 Bronze Data Contracts (Schemas)

All ingested records must include standard **Data Engineering audit metadata** (`_ingested_at_utc`, `_source_system`, `_batch_id`).

#### A. `daily_ohlcv` Schema (Parquet)

| Column Name | Data Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `trade_date` | `DATE` | No | Trading date (`YYYY-MM-DD`) |
| `ticker` | `STRING` | No | Exchange symbol (e.g., `RELIANCE.NS`, `TCS.NS`) |
| `open` | `FLOAT64` | No | Daily opening price |
| `high` | `FLOAT64` | No | Daily highest price |
| `low` | `FLOAT64` | No | Daily lowest price |
| `close` | `FLOAT64` | No | Daily closing price |
| `adj_close` | `FLOAT64` | Yes | Split/dividend adjusted close price |
| `volume` | `INT64` | No | Total traded share volume |
| `delivery_pct` | `FLOAT64` | Yes | Percentage of deliverable volume to traded volume |
| `_ingested_at_utc`| `TIMESTAMP`| No | UTC timestamp of ingestion |
| `_source_system` | `STRING` | No | Source identifier (e.g., `yfinance`, `nse_bhavcopy`) |

#### B. `daily_macro` Schema (Parquet)

| Column Name | Data Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `trade_date` | `DATE` | No | Observation date (`YYYY-MM-DD`) |
| `indicator_code`| `STRING` | No | e.g., `USDINR`, `CRUDE_BRENT`, `GOLD`, `INDIA_VIX`, `SP500` |
| `close_value` | `FLOAT64` | No | Closing rate or index level |
| `_ingested_at_utc`| `TIMESTAMP`| No | UTC timestamp of ingestion |

#### C. `raw_headlines` Schema (JSON Lines)
```json
{
  "article_id": "sha256_hash_of_url",
  "published_at_utc": "2026-11-12T11:30:00Z",
  "ticker_mentions": ["RELIANCE.NS", "TCS.NS"],
  "category": "EARNINGS | MACRO | GEOPOLITICAL | LEADERSHIP",
  "source": "Economic Times RSS",
  "headline": "Example headline text",
  "summary": "Brief article snippet",
  "url": "https://...",
  "_ingested_at_utc": "2026-11-12T12:30:05Z"
}
```

---

## 6. Reliability, Error Handling & Observability

1. **Idempotency:** Re-running any daily job for a given `trade_date` must overwrite the exact partition file (`ohlcv_YYYYMMDD.parquet`) without creating duplicate records.
2. **Retry Policy:** External HTTP/API calls must implement exponential backoff (3 retries, delays of `2s`, `4s`, `8s`) to handle transient rate limits or network blips.
3. **Audit Logging:** After every cron execution, the worker writes a lightweight JSON summary to `s3://.../_logs/ingestion_audit/` recording `job_name`, `status` (`SUCCESS` / `FAILED`), `rows_written`, and `execution_duration_sec`.
4. **Memory Safety:** Ingestion workers must use **Polars** or standard Python `csv`/`json` modules instead of Pandas to keep peak RAM usage under **300 MB**.

---

## 7. Repository Structure Specification

```text
stock-ai-lakehouse/
├── .github/
│   └── workflows/
│       └── deploy_ec2.yml          # CI/CD pipeline triggered on push to main
├── docs/
│   ├── PHASE_0_ARCHITECTURE_SPEC.md
│   └── architecture.drawio
├── src/
│   ├── common/
│   │   ├── config.py               # Watchlist tickers, S3 paths, constants
│   │   ├── s3_writer.py            # Boto3 Parquet/JSON upload & /tmp cleanup
