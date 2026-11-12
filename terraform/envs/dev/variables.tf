variable "region" {
  type    = string
  default = "ap-south-1"
}

variable "instance_type" {
  description = "Free-tier eligible: t3.micro (or t2.micro)"
  type        = string
  default     = "t3.micro"
}

variable "ssh_cidr" {
  description = "Optional emergency SSH CIDR (your-ip/32). null = SSH closed; use SSM."
  type        = string
  default     = null
}

variable "monthly_budget_usd" {
  description = "~₹500"
  type        = string
  default     = "6"
}

variable "alert_email" {
  type = string
}
