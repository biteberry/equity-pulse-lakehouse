# Phase 0 Implementation Guide

This document maps [PHASE_0_ARCHITECTURE_SPEC.md](file:///c:/Manivannan/Workspace/Stock_Market/GITHUB/equity-pulse-lakehouse/docs/PHASE_0_ARCHITECTURE_SPEC.md) into concrete implementation steps across the repository's stacks.

---

## Step 1: Infrastructure Provisioning & GitHub Workflow Trigger (Implemented)

### 1.1 Architecture & FinOps Design
- **Network (`terraform/modules/network`):** Dedicated VPC (`10.20.0.0/16`), single public subnet in `ap-south-1a`, Internet Gateway, and a **free S3 Gateway VPC Endpoint** so all S3 Bronze writes avoid internet data transfer costs. No NAT Gateway (saves ~₹2,700/mo).
- **Security Group (`terraform/modules/security`):** Zero inbound ports open by default (`0` ingress rules). Outbound `443`/`80` enabled for APIs, package updates, S3, and AWS SSM. Optional emergency SSH CIDR variable (`ssh_cidr`).
- **IAM (`terraform/modules/iam` & `terraform/bootstrap`):**
  - **EC2 Instance Profile:** Attached with `AmazonSSMManagedInstanceCore` (enables keyless control via AWS Systems Manager) and least-privilege `s3:PutObject` only on `s3://equity-pulse-landing-<account-id>/*`.
  - **GitHub OIDC Role:** Short-lived credentials via OpenID Connect (`aws-actions/configure-aws-credentials`) — zero static AWS keys stored in GitHub.
- **Free Tier EC2 (`terraform/modules/ec2_worker`):** Ubuntu 24.04 LTS (`m7i-flex.large` — 2 vCPU, 8 GB RAM, Free Tier eligible), 20 GB encrypted `gp3` volume, IMDSv2 enforced.
- **Bootstrap (`user_data.sh`):** Configures `Asia/Kolkata` timezone, allocates and mounts a **2 GB swap file** (`vm.swappiness=10`), installs Python 3 `venv`/`pip`/`jq`, starts `amazon-ssm-agent`, and prepares `/opt/equity-pulse/.venv`.
- **Cost Guardrails (`terraform/envs/dev`):** S3 Lifecycle rule transitions Bronze objects to `GLACIER_IR` after 90 days; AWS Budgets alerts configured at **50%** and **90%** of the $6 (~₹500) monthly cap.

### 1.2 GitHub Workflows
1. **[terraform.yml](file:///c:/Manivannan/Workspace/Stock_Market/GITHUB/equity-pulse-lakehouse/.github/workflows/terraform.yml):**
   - Runs `terraform fmt`, `init`, `validate`, and `plan` on PRs.
   - Auto-applies on push to `main`, or manually via `workflow_dispatch` (`plan` | `apply` | `destroy`) to create/tear down the EC2 instance and stack from GitHub.
2. **[ec2-trigger.yml](file:///c:/Manivannan/Workspace/Stock_Market/GITHUB/equity-pulse-lakehouse/.github/workflows/ec2-trigger.yml):**
   - Triggers the EC2 instance directly from GitHub Actions (`start`, `stop`, `status`, or `run` arbitrary shell/ingestion commands via **AWS SSM Run Command** without opening port 22).

---

## Step 2: Upcoming Stacks (Planned Next)

```text
equity-pulse-lakehouse/
├── compute/
│   ├── lambda/        # Lightweight serverless job wrappers
│   └── spark/         # PySpark jobs (Phase 1 Bronze -> Silver transformations)
├── ingestion/         # Source connectors (OHLCV, FII/DII, Macro, News, Fundamentals)
└── terraform/         # Completed Step 1 (Network, SG, IAM, EC2, S3 Bronze, Budgets)
```
