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
  source            = "../../modules/iam"
  name              = local.name
  bronze_bucket_arn = data.aws_s3_bucket.landing.arn
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
