# Security group: NO inbound by default. Access via SSM (GitHub Actions -> AWS API -> SSM agent),
# so port 22 never needs to be open.

variable "name" { type = string }
variable "vpc_id" { type = string }
variable "ssh_cidr" {
  description = "Optional CIDR for emergency SSH (your-ip/32). null keeps SSH closed."
  type        = string
  default     = null
}

resource "aws_security_group" "worker" {
  name        = "${var.name}-worker-sg"
  description = "Ingestion worker - egress only"
  vpc_id      = var.vpc_id
  tags        = { Name = "${var.name}-worker-sg" }
}

resource "aws_vpc_security_group_egress_rule" "https" {
  security_group_id = aws_security_group.worker.id
  description       = "HTTPS to APIs, S3, SSM"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_egress_rule" "http" {
  security_group_id = aws_security_group.worker.id
  description       = "HTTP for apt mirrors / some RSS feeds"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_ingress_rule" "ssh" {
  count             = var.ssh_cidr == null ? 0 : 1
  security_group_id = aws_security_group.worker.id
  description       = "Emergency SSH"
  ip_protocol       = "tcp"
  from_port         = 22
  to_port           = 22
  cidr_ipv4         = var.ssh_cidr
}

output "worker_sg_id" { value = aws_security_group.worker.id }
