# Phase 0 Implementation Plan & Guide

This document tracks the step-by-step implementation of [PHASE_0_ARCHITECTURE_SPEC.md](file:///c:/Manivannan/Workspace/Stock_Market/GITHUB/equity-pulse-lakehouse/docs/PHASE_0_ARCHITECTURE_SPEC.md) across three modular repository stacks:
1. **`terraform/`** — AWS Infrastructure, Networking, IAM, EC2 Worker, S3 Landing & Cost Guardrails *(Step 1 — Completed)*
2. **`ingestion/`** — Data Source Connectors, Validation, Retry & S3 Landing Writers *(Step 2 — Next)*
3. **`compute/`** — Execution Wrappers (`spark/` & `lambda/`) *(Step 3 — Planned)*

---

## Step 1: AWS Infrastructure, Security & GitHub Workflows (✅ Completed)

### 1.1 Implemented Architecture & Modules

| Module / File | Resources Provisioned | Key Design & Security Decisions |
| :--- | :--- | :--- |
| [terraform/modules/network/main.tf](file:///c:/Manivannan/Workspace/Stock_Market/GITHUB/equity-pulse-lakehouse/terraform/modules/network/main.tf) | `aws_vpc` (`10.20.0.0/16`), `aws_subnet` (`10.20.1.0/24` in `ap-south-1a`), `aws_internet_gateway`, `aws_route_table`, `aws_vpc_endpoint` (S3 Gateway) | • **No NAT Gateway** (saves ~₹2,700/mo).<br>• **Free S3 Gateway Endpoint** keeps all S3 uploads on the AWS internal network at ₹0 transfer cost. |
| [terraform/modules/security/main.tf](file:///c:/Manivannan/Workspace/Stock_Market/GITHUB/equity-pulse-lakehouse/terraform/modules/security/main.tf) | `aws_security_group` (`equity-pulse-dev-worker-sg`), egress rules (`443`, `80`) | • **Zero inbound rules (`0` open ports)** — Port 22 (SSH) is closed.<br>• Instance is controlled via **AWS Systems Manager (SSM) Agent** over outbound HTTPS. |
| [terraform/modules/iam/main.tf](file:///c:/Manivannan/Workspace/Stock_Market/GITHUB/equity-pulse-lakehouse/terraform/modules/iam/main.tf) | `aws_iam_role` (`equity-pulse-dev-ec2-worker`), `aws_iam_instance_profile`, `aws_iam_role_policy` (`landing-write`) | • Attaches `AmazonSSMManagedInstanceCore` for keyless SSM access.<br>• Grants **strictly `s3:PutObject` only** on `arn:aws:s3:::equity-pulse-landing-<account-id>/*` (no read/delete access). |
| [terraform/modules/ec2_worker/main.tf](file:///c:/Manivannan/Workspace/Stock_Market/GITHUB/equity-pulse-lakehouse/terraform/modules/ec2_worker/main.tf) & [user_data.sh](file:///c:/Manivannan/Workspace/Stock_Market/GITHUB/equity-pulse-lakehouse/terraform/modules/ec2_worker/user_data.sh) | `aws_instance` (`m7i-flex.large`, Ubuntu 24.04 LTS, 20 GB encrypted `gp3`) | • **Free-tier `m7i-flex.large`** (2 vCPU, 8 GB RAM).<br>• Enforces **IMDSv2** (`http_tokens = "required"`).<br>• `user_data.sh` configures `Asia/Kolkata` timezone, **2 GB swap file** (`/swapfile`), Python 3 `venv`/`pip`/`jq`, starts `amazon-ssm-agent`, and initializes `/opt/equity-pulse/.venv`. |
| [terraform/envs/dev/main.tf](file:///c:/Manivannan/Workspace/Stock_Market/GITHUB/equity-pulse-lakehouse/terraform/envs/dev/main.tf) | S3 backend (`_tfstate/envs/dev/terraform.tfstate`), `aws_iam_role_policy.github_actions`, `aws_s3_bucket_versioning.landing` (`Suspended`), `aws_budgets_budget.monthly` | • Uses existing `equity-pulse-landing-307828758318` bucket.<br>• **Suspends bucket versioning** to prevent cost bloat from daily file overwrites and `.tflock` lockfiles.<br>• Self-manages the `equity-pulse-github-actions` least-privilege IAM policy via Terraform.<br>• Configures $6/mo budget alerts at **50%** and **90%**. |

---

### 1.2 GitHub Governance & CI/CD Workflows

1. **Branch Protection on `main`:**
   - Direct commits and force-pushes to `main` are blocked (including for repository admins).
   - Every change must be pushed to a feature branch and merged via a **Pull Request**.
2. **Terraform Pipeline ([.github/workflows/terraform.yml](file:///c:/Manivannan/Workspace/Stock_Market/GITHUB/equity-pulse-lakehouse/.github/workflows/terraform.yml)):**
   - **On Pull Request (`pull_request` touching `terraform/**`):**
     - Automatically runs `terraform fmt -check`, `init`, `validate`, and `plan -out=tfplan` **without** requiring manual approval.
     - Posts the full Terraform Plan output as a comment on the PR.
   - **On PR Merge (`push` to `main` touching `terraform/**`):**
     - Runs `Terraform Plan` and uploads the binary `tfplan` artifact.
     - Pauses at `Terraform Apply` (`environment: dev`) requiring manual reviewer approval before applying the exact `tfplan` in AWS.
3. **EC2 Remote Trigger ([.github/workflows/ec2-trigger.yml](file:///c:/Manivannan/Workspace/Stock_Market/GITHUB/equity-pulse-lakehouse/.github/workflows/ec2-trigger.yml)):**
   - Triggered via `workflow_dispatch` with actions:
     - `start`: Starts the EC2 worker and waits until `instance-status-ok`.
     - `stop`: Stops the EC2 worker (frees compute hours and public IPv4 hours).
     - `status`: Prints current state, instance type, and public IP.
     - `run`: Starts the instance (if stopped) and executes any shell command remotely via **AWS SSM Run Command**, returning `stdout`/`stderr` in the GitHub Actions log.

---

### 1.3 FinOps & Cost Breakdown (Current Infrastructure)

| Item | Free Tier Coverage | Cost Behavior | How to Keep at ₹0 |
| :--- | :--- | :--- | :--- |
| **VPC, Subnet, IGW, S3 Gateway Endpoint, SG, IAM, SSM** | Always Free | ₹0 forever | No action needed. |
| **AWS Budget (`equity-pulse-dev-monthly`)** | First 2 budgets free | ₹0 | Keep total budgets ≤ 2. |
| **EC2 (`m7i-flex.large`) + Public IPv4** | 750 hrs/mo in AWS Free Tier | Consumes hours only while in `running` state | Use `ec2-trigger.yml` (`action: stop`) when idle so `running` hours stay well under 750 hrs/mo. |
| **EBS Root Volume (`20 GB gp3`)** | 30 GB/mo in 12-mo Free Tier | Allocated while instance exists (running or stopped) | Kept at 20 GB (10 GB below the 30 GB Free Tier cap). |
| **S3 (`equity-pulse-landing-307828758318`)** | 5 GB Standard + 2,000 `PUT` + 20,000 `GET`/mo | Versioning is `Suspended` so overwrites do not multiply storage | Keep raw files compact (Snappy Parquet) and clean up `/tmp` after uploads. |

---

## Step 2: Ingestion Stack (`ingestion/`) — Next Up

1. **`ingestion/common/`:**
   - `config.py`: Watchlist tickers, S3 landing bucket (`equity-pulse-landing-307828758318`), Hive partition builders.
   - `s3_writer.py`: Writes Polars DataFrames (Snappy Parquet) and JSONL to S3 via `boto3.client("s3").put_object(...)` (using only `s3:PutObject`), then cleans `/tmp`.
   - `retry.py`: Exponential backoff (`2s`, `4s`, `8s`) for external HTTP/API requests.
   - `audit.py`: Uploads run metadata JSON to `s3://equity-pulse-landing-307828758318/_logs/ingestion_audit/`.
2. **`ingestion/sources/`:**
   - `market_eod.py`, `flows_macro.py`, `news_daily.py`, `fundamentals.py`, `reference.py`.

---

## Step 3: Compute Stack (`compute/`) — Planned

1. **`compute/lambda/`:** Thin serverless handlers wrapping `ingestion/sources/*` for scheduled lightweight execution.
2. **`compute/spark/`:** PySpark job templates (`m7i-flex.large` local mode / Phase 1 downstream processing).
