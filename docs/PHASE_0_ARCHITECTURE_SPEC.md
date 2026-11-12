# Phase 0 Architecture Specification: Stock Market AI Lakehouse (Landing Ingestion Layer)

**Document Version:** 1.1  
**Status:** Implemented (Step 1 Infrastructure) / Ready for Step 2 (Ingestion & Compute)  
**Target Budget:** ₹200 – ₹500 INR / Month (~$2.50 – $6.00 USD)  
**Target Region:** `ap-south-1` (Mumbai)  

---

## 1. Executive Summary & Objective

The objective of **Phase 0** is to build an automated, low-cost, fault-tolerant data ingestion pipeline that collects multi-factor financial data and stores it in an immutable **Landing Zone** on Amazon S3 (`s3://equity-pulse-landing-<account-id>/`).

Following a **Spec-Driven Development** approach, this document defines the system boundaries, infrastructure constraints, security model, data contracts, storage partitions, cost guardrails, and acceptance criteria.

### Out of Scope for Phase 0
* Medallion downstream layers (Bronze/Silver/Gold buckets & technical indicator calculations like RSI, MACD) — *Deferred to Phase 1*
* AI sentiment scoring (FinBERT/LLMs) — *Deferred to Phase 1*
* ML model training and inference — *Deferred to Phase 2*

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
| 2. CI/CD & COMPUTE (GITHUB ACTIONS OIDC -> AWS SSM -> AWS EC2 FREE TIER)          |
|                                                                                   |
|  [GitHub Repo (Protected main)]                                                   |
|   ├── PR to main        --> [Terraform Plan (Auto, No Approval Gate)]             |
|   ├── Merge to main     --> [Terraform Plan + Apply (Gated by 'dev' Approval)]    |
|   └── ec2-trigger.yml   --> [AWS SSM Run Command (Start / Stop / Status / Run)]   |
|                                      |                                            |
|                                      v                                            |
|  [AWS VPC 10.20.0.0/16 (Public Subnet + IGW + Free S3 Gateway VPC Endpoint)]      |
|   └── [AWS EC2: m7i-flex.large (Free Tier - 2 vCPU, 8 GB RAM + 2 GB Swap)]        |
|        - Ubuntu 24.04 LTS, 20 GB Encrypted gp3, IMDSv2 Required                   |
|        - Security Group: 0 Inbound Rules (Port 22 Closed), Outbound 443/80        |
|        - IAM Instance Profile: SSM Core + s3:PutObject ONLY on Landing Bucket     |
+-----------------------------------------+-----------------------------------------+
                                          | (Boto3 PutObject via Free S3 Gateway Endpoint)
                                          v
+-----------------------------------------------------------------------------------+
| 3. LAKEHOUSE STORAGE: LANDING ZONE (AMAZON S3)                                    |
|                                                                                   |
|  s3://equity-pulse-landing-<account-id>/  (Versioning: Suspended)                 |
|   ├── _tfstate/           (Terraform Remote State & Native Lockfile)              |
|   ├── market_data/        (Parquet - Hive Partitioned)                            |
|   ├── macro_commodities/  (Parquet - Hive Partitioned)                            |
|   ├── news_events/        (JSON - Hive Partitioned)                               |
|   ├── fundamentals/       (JSON - Ticker Partitioned)                             |
|   ├── reference_data/     (CSV/Parquet - Static Reference)                        |
|   └── _logs/              (JSON - Ingestion Audit Logs)                           |
+-----------------------------------------------------------------------------------+
```

---

## 3. Infrastructure, Security & FinOps Specification

To strictly stay within the **₹200 – ₹500/month** budget and protect the AWS account when operating from a **public GitHub repository**, all components enforce the following guardrails:

| Component | AWS / Tool Specification | Security & Cost Guardrail Configuration | Est. Monthly Cost |
| :--- | :--- | :--- | :--- |
| **Compute** | AWS EC2 `m7i-flex.large` | Free Tier eligible (750 hrs/mo; 2 vCPU, 8 GB RAM). Ubuntu 24.04 LTS + **2 GB Swap file**. Start/stop on demand via `ec2-trigger.yml` to conserve compute & IPv4 hours. | ₹0 (Free Tier) |
| **Block Storage** | Amazon EBS `gp3` (Encrypted) | **20 GB** allocated (Free Tier cap is 30 GB). Zero local data retention; purge `/tmp` after each S3 upload. | ₹0 (Free Tier) |
| **Networking** | Custom VPC (`10.20.0.0/16`) | Single public subnet (`ap-south-1a`) + IGW + **Free S3 Gateway VPC Endpoint**. No NAT Gateway (saves ~₹2,700/mo) and no Elastic IP. | ₹0 |
| **Network Security**| EC2 Security Group | **0 Inbound rules** (Port 22 SSH closed by default). Outbound TCP `443` & `80` only. Managed via AWS Systems Manager (SSM) Agent. | ₹0 |
| **Object Storage** | Amazon S3 Standard (`equity-pulse-landing-*`) | All buckets must start with `equity-pulse-*`. **Versioning Suspended** so idempotent overwrites and `.tflock` files do not accumulate old versions. | ₹0 – ₹20 |
| **EC2 IAM Role** | IAM Instance Profile (`equity-pulse-dev-ec2-worker`) | Least-privilege: `AmazonSSMManagedInstanceCore` + **`s3:PutObject` ONLY** on `s3://equity-pulse-landing-<account-id>/*` (no `DeleteObject` or `GetObject`). | ₹0 |
| **GitHub Auth** | IAM OIDC (`equity-pulse-github-actions`) | Keyless OpenID Connect locked to repo `biteberry/equity-pulse-lakehouse`. Inline policy managed via Terraform; scoped strictly to `ap-south-1`, `equity-pulse-landing-*`, and `equity-pulse-*` roles. | ₹0 |
| **CI/CD Governance**| GitHub Branch Protection + Environments | `main` branch protected (PR required, no direct push/force-push). PR runs `terraform plan` automatically; merge to `main` requires manual reviewer approval on `dev` environment before `terraform apply`. | ₹0 |
| **Cost Monitoring**| AWS Budgets (`equity-pulse-dev-monthly`) | $6 USD (~₹500 INR) monthly cap with email alerts at **50% (~₹250)** and **90% (~₹450)** actual spend. | ₹0 (First 2 free) |

---

## 4. Data Ingestion & Source Specification

### 4.1 Ingestion Schedules (IST Timezone)

| Pipeline Job ID | Data Domain | Source Examples | Frequency | Cron Schedule (IST) | Output Format |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `job_market_eod` | Daily OHLCV, Delivery % | `yfinance`, NSE Bhavcopy | Mon–Fri (EOD) | `0 17 * * 1-5` | Snappy Parquet |
| `job_flows_macro`| FII/DII Net Flows, India VIX, Global Indices, USD/INR, Crude, Gold | `yfinance`, NSE Reports | Mon–Fri (EOD) | `15 17 * * 1-5` | Snappy Parquet |
| `job_news_daily` | Financial News, RSS, Geopolitical & Leadership Events | Moneycontrol/ET RSS, NewsAPI | Daily | `0 18 * * *` | UTF-8 JSONL |
| `job_fundamentals`| Quarterly Results, Balance Sheet, CapEx & R&D Filings | `yfinance` financials, Exchange Filings | Weekly (Sat) | `0 10 * * 6` | UTF-8 JSON |
| `job_reference` | Connected Companies (Suppliers, Subsidiaries, Peers) | Curated CSV/JSON in Git | On Git Push | Event-driven | CSV / Parquet |

---

## 5. S3 Storage Layout & Data Contracts (Landing Layer)

### 5.1 S3 Bucket Naming & Hive Partitioning
**Bucket Name:** `s3://equity-pulse-landing-<account-id>/`

```text
s3://equity-pulse-landing-<account-id>/
├── _tfstate/
│   └── envs/dev/terraform.tfstate
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

### 5.2 Landing Data Contracts (Schemas)

All ingested records must include standard **Data Engineering audit metadata**:
* `_ingested_at_utc` (`TIMESTAMP` / ISO-8601 UTC string)
* `_source_system` (`STRING`)
* `_batch_id` (`STRING` — UUID/run identifier)

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
| `_batch_id` | `STRING` | No | Unique batch execution ID |

#### B. `daily_macro` Schema (Parquet)

| Column Name | Data Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `trade_date` | `DATE` | No | Observation date (`YYYY-MM-DD`) |
| `indicator_code`| `STRING` | No | e.g., `USDINR`, `CRUDE_BRENT`, `GOLD`, `INDIA_VIX`, `SP500` |
| `close_value` | `FLOAT64` | No | Closing rate or index level |
| `_ingested_at_utc`| `TIMESTAMP`| No | UTC timestamp of ingestion |
| `_source_system` | `STRING` | No | Source identifier (e.g., `yfinance`, `nse_reports`) |
| `_batch_id` | `STRING` | No | Unique batch execution ID |

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
  "_ingested_at_utc": "2026-11-12T12:30:05Z",
  "_source_system": "et_rss",
  "_batch_id": "run_20261112_180000"
}
```

---

## 6. Reliability, Error Handling & Observability

1. **Idempotency:** Re-running any daily job for a given `trade_date` must overwrite the exact partition file (`ohlcv_YYYYMMDD.parquet`) without creating duplicate records or S3 object versions.
2. **Retry Policy:** External HTTP/API calls must implement exponential backoff (3 retries, delays of `2s`, `4s`, `8s`) to handle transient rate limits or network blips.
3. **Audit Logging:** After every job execution, the worker writes a lightweight JSON summary to `s3://equity-pulse-landing-<account-id>/_logs/ingestion_audit/` recording `job_name`, `status` (`SUCCESS` / `FAILED`), `rows_written`, `execution_duration_sec`, and `_batch_id`.
4. **Memory Efficiency:** Ingestion workers use **Polars** or standard Python `csv`/`json` modules to keep memory footprint minimal, while `m7i-flex.large` (8 GB RAM + 2 GB swap) provides headroom for local Spark/Polars processing.

---

## 7. Repository Stack Structure

```text
equity-pulse-lakehouse/
├── .github/
│   └── workflows/
│       ├── terraform.yml           # PR Plan (auto) + Merge Plan & Apply (gated)
│       └── ec2-trigger.yml         # Start / Stop / Status / Run commands via AWS SSM
├── docs/
│   ├── PHASE_0_ARCHITECTURE_SPEC.md
│   └── PHASE_0_IMPLEMENTATION.md
├── terraform/                      # Stack 3: Infrastructure-as-Code (Implemented)
│   ├── bootstrap/main.tf
│   ├── modules/
│   │   ├── network/main.tf
│   │   ├── security/main.tf
│   │   ├── iam/main.tf
│   │   └── ec2_worker/
│   │       ├── main.tf
│   │       └── user_data.sh
│   └── envs/dev/
│       ├── main.tf
│       ├── variables.tf
│       └── outputs.tf
├── ingestion/                      # Stack 2: Source Connectors (Planned Next)
│   ├── common/
│   │   ├── config.py               # Watchlist tickers, S3 landing paths, constants
│   │   ├── s3_writer.py            # Boto3 PutObject upload & /tmp cleanup
│   │   ├── retry.py                # Exponential backoff decorator (2s, 4s, 8s)
│   │   └── audit.py                # Writes execution summary to _logs/ingestion_audit/
│   └── sources/
│       ├── market_eod.py
│       ├── flows_macro.py
│       ├── news_daily.py
│       ├── fundamentals.py
│       └── reference.py
└── compute/                        # Stack 1: Compute Wrappers (Planned Next)
    ├── lambda/                     # Serverless job handlers
    └── spark/                      # PySpark jobs
```
