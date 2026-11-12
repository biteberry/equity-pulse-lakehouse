# Phase 0 Implementation Doc + Repo Stack Layout

Write `docs/PHASE_0_IMPLEMENTATION.md`, which turns the architecture spec into build steps, and scaffold three stacks (`compute`, `ingestion`, `terraform`). New stacks can be added later without restructuring.

## Open Questions

> [!IMPORTANT]
> **1. Spark and Lambda vs. the spec.** The arch spec puts all compute on **one EC2 micro with cron** and pushes transforms to Phase 1. Spark won't run reliably on 1 GB RAM, and EMR or Glue would break the ₹500 budget. My proposal:
> - **Lambda:** runs the lightweight ingestion jobs on an EventBridge schedule. This could replace EC2 and cron.
> - **Spark:** scaffold it now (local PySpark jobs plus a Glue/EMR Serverless placeholder). Only enable it in Phase 1 for Bronze→Silver.
>
> Should Lambda **replace** EC2 and cron, or **sit alongside** them?

> [!IMPORTANT]
> **2. Where ingestion code lives.** Proposal: `ingestion/` holds the pure source connectors (fetch, validate, write to S3). `compute/lambda/` holds thin handlers that call them, so the same code also runs locally or on EC2. Is that split OK?

> [!NOTE]
> **3. Spec fixes.** I'll also fix the gaps found in the arch spec:
> - finish the truncated §7
> - add `_batch_id` and `_source_system` to the schemas
> - settle the duplicate India VIX entry
> - add schemas for `fii_dii_flows`, `corporate_events` and `fundamentals`
> - rename the repo references to `equity-pulse-lakehouse`
>
> Should I go ahead?

## Proposed Repo Layout

```text
equity-pulse-lakehouse/
├── .github/workflows/            # ci.yml (lint/test), terraform.yml (plan/apply), deploy.yml
├── docs/
│   ├── PHASE_0_ARCHITECTURE_SPEC.md
│   └── PHASE_0_IMPLEMENTATION.md   [NEW]
├── compute/
│   ├── lambda/
│   │   ├── handlers/             # market_eod.py, flows_macro.py, news_daily.py, fundamentals.py
│   │   ├── layers/requirements.txt  # polars, boto3, yfinance, feedparser
│   │   └── build.sh              # zips handlers + layer for Terraform
│   └── spark/
│       ├── jobs/                 # bronze_to_silver_ohlcv.py (Phase 1 stub)
│       ├── conf/spark-defaults.conf
│       └── README.md
├── ingestion/
│   ├── common/                   # config.py, s3_writer.py, retry.py, audit.py, schemas.py
│   ├── sources/                  # market_eod.py, flows_macro.py, news.py, fundamentals.py, reference.py
│   ├── reference_data/connected_companies.csv
│   └── tests/
├── terraform/
│   ├── modules/                  # s3_bronze, iam, lambda_job, eventbridge_schedule, budgets, (ec2_worker)
│   ├── envs/dev/                 # main.tf, variables.tf, backend.tf, terraform.tfvars.example
│   └── README.md
├── pyproject.toml
└── README.md
```

## Implementation Doc Contents (`PHASE_0_IMPLEMENTATION.md`)

1. **Scope and decisions:** how this doc maps to the arch spec, plus the decision log for Spark and Lambda.
2. **Stack overview:** the responsibilities and interfaces of each stack.
3. **Terraform stack:**
   - remote state (S3 backend with lockfile)
   - modules and variables
   - bucket lifecycle (Glacier IR after 90 days)
   - least-privilege IAM
   - budgets at ₹250 and ₹450
4. **Ingestion stack:**
   - the connector interface
   - Polars schemas enforcing the data contracts
   - idempotent writes to S3 keys
   - retry with backoff (2/4/8s)
   - audit logs
   - a ~300 MB memory limit
5. **Compute stack:**
   - **Lambda:** runtime, memory/timeout settings, packaging, and EventBridge schedules in IST (cron converted to UTC)
   - **Spark:** local setup and the Phase 1 hand-off
6. **CI/CD:** lint and test, `terraform plan` on PRs, `apply` and deploy on `main`, and secrets handling.
7. **Work breakdown:** ordered tasks, each with acceptance criteria.
8. **Runbook:** how to backfill, rerun a date, and read the audit logs.
9. **Cost estimate** per component.

## Verification
- Check that every section of the arch spec maps to an item in the implementation doc.
- Run `terraform fmt` and `terraform validate` on the scaffold (only if `terraform` is installed).
- Run `pytest` on the ingestion stubs.
