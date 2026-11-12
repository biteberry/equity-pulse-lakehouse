terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
  # bucket supplied via: terraform init -backend-config="bucket=<state_bucket>"
  backend "s3" {
    key          = "_tfstate/envs/dev/terraform.tfstate"
    region       = "ap-south-1"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = "equity-pulse-lakehouse", ManagedBy = "terraform", Env = "dev" }
  }
}

data "aws_caller_identity" "current" {}

locals {
  name           = "equity-pulse-dev"
  landing_bucket = "equity-pulse-landing-${data.aws_caller_identity.current.account_id}"
}

# ---------- Landing bucket (existing: equity-pulse-landing-<account_id>) ----------
data "aws_s3_bucket" "landing" {
  bucket = local.landing_bucket
}

# ---------- GitHub Actions OIDC Role Policy (self-managed via Terraform) ----------
import {
  to = aws_iam_role_policy.github_actions
  id = "equity-pulse-github-actions:equity-pulse-terraform-least-privilege"
}

data "aws_iam_policy_document" "github_actions" {
  statement {
    sid    = "EquityPulseBuckets"
    effect = "Allow"
    actions = [
      "s3:ListBucket",
      "s3:GetBucket*",
      "s3:PutBucketVersioning",
      "s3:GetEncryptionConfiguration",
      "s3:GetLifecycleConfiguration",
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
    ]
    resources = [
      data.aws_s3_bucket.landing.arn,
      "${data.aws_s3_bucket.landing.arn}/*",
    ]
  }

  statement {
    sid    = "EC2AndSSMInMumbaiOnly"
    effect = "Allow"
    actions = [
      "ec2:*",
      "ssm:SendCommand",
      "ssm:GetCommandInvocation",
      "ssm:ListCommandInvocations",
      "ssm:DescribeInstanceInformation",
    ]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.region]
    }
  }

  statement {
    sid    = "ScopedIAMForWorkerOnly"
    effect = "Allow"
    actions = [
      "iam:GetRole",
      "iam:CreateRole",
      "iam:DeleteRole",
      "iam:TagRole",
      "iam:UntagRole",
      "iam:PassRole",
      "iam:AttachRolePolicy",
      "iam:DetachRolePolicy",
      "iam:PutRolePolicy",
      "iam:GetRolePolicy",
      "iam:DeleteRolePolicy",
      "iam:ListRolePolicies",
      "iam:ListAttachedRolePolicies",
      "iam:ListInstanceProfilesForRole",
      "iam:CreateInstanceProfile",
      "iam:DeleteInstanceProfile",
      "iam:GetInstanceProfile",
      "iam:AddRoleToInstanceProfile",
      "iam:RemoveRoleFromInstanceProfile",
      "iam:TagInstanceProfile",
    ]
    resources = [
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/equity-pulse-*",
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:instance-profile/equity-pulse-*",
    ]
  }

  statement {
    sid    = "BudgetsAlert"
    effect = "Allow"
    actions = [
      "budgets:ViewBudget",
      "budgets:ModifyBudget",
      "budgets:TagResource",
      "budgets:UntagResource",
      "budgets:ListTagsForResource",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "github_actions" {
  name   = "equity-pulse-terraform-least-privilege"
  role   = "equity-pulse-github-actions"
  policy = data.aws_iam_policy_document.github_actions.json
}

resource "aws_s3_bucket_versioning" "landing" {
  depends_on = [aws_iam_role_policy.github_actions]
  bucket     = data.aws_s3_bucket.landing.id
  versioning_configuration {
    status = "Suspended"
  }
}

# ---------- Stacks ----------
module "network" {
  source = "../../modules/network"
  name   = local.name
  az     = "${var.region}a"
}

module "security" {
  source   = "../../modules/security"
  name     = local.name
  vpc_id   = module.network.vpc_id
  ssh_cidr = var.ssh_cidr
}

module "iam" {
  source             = "../../modules/iam"
  name               = local.name
  landing_bucket_arn = data.aws_s3_bucket.landing.arn
}

module "ec2_worker" {
  source                = "../../modules/ec2_worker"
  name                  = local.name
  instance_type         = var.instance_type
  subnet_id             = module.network.public_subnet_id
  security_group_id     = module.security.worker_sg_id
  instance_profile_name = module.iam.instance_profile_name
}

# ---------- Budget alerts (50% / 90%) ----------
resource "aws_budgets_budget" "monthly" {
  depends_on   = [aws_iam_role_policy.github_actions]
  name         = "${local.name}-monthly"
  budget_type  = "COST"
  limit_amount = var.monthly_budget_usd
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = [50, 90]
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.alert_email]
    }
  }
}
