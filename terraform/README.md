# Terraform – Phase 0 Infrastructure

```text
terraform/
├── bootstrap/        # one-time: state bucket + GitHub OIDC role (run locally)
├── modules/
│   ├── network/      # VPC, public subnet, IGW, route table, S3 gateway endpoint
│   ├── security/     # egress-only SG (optional emergency SSH)
│   ├── iam/          # EC2 role: SSM + Bronze bucket write; instance profile
│   └── ec2_worker/   # t3.micro Ubuntu 24.04, 20 GB gp3, IMDSv2, swap via user_data
└── envs/dev/         # wires modules + Bronze bucket + AWS Budget alerts
```

## 1. Bootstrap (once, locally, admin credentials)

```bash
cd terraform/bootstrap
terraform init
terraform apply -var="github_repo=<owner>/equity-pulse-lakehouse"
```

## 2. GitHub repo settings → Environments → `dev` → Secrets

| Secret | Value |
|---|---|
| `AWS_ROLE_ARN` | `github_actions_role_arn` output |
| `TF_STATE_BUCKET` | `state_bucket` output |
| `ALERT_EMAIL` | email for budget alerts |

## 3. Provision via GitHub Actions

- PR touching `terraform/**` → `plan`
- Push to `main` → `apply`
- Manual: **Actions → terraform → Run workflow** (`plan`/`apply`/`destroy`)

## 4. Trigger the EC2 worker

**Actions → ec2-trigger → Run workflow**: `start`, `stop`, `status`, or `run` (executes a shell command through SSM Run Command; output shown in the job log).

## Cost notes
- `t3.micro` + 20 GB `gp3` + 1 public IPv4: covered by Free Tier (750 hrs each) for 12 months.
- No NAT Gateway, no Elastic IP. S3 traffic goes via the free gateway endpoint.
- `cpu_credits = standard` prevents T3 Unlimited burst charges.
