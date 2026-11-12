# Free-tier ingestion worker (Ubuntu 24.04, t3.micro, 20 GB gp3, 2 GB swap via user_data).

variable "name" { type = string }
variable "subnet_id" { type = string }
variable "security_group_id" { type = string }
variable "instance_profile_name" { type = string }
variable "instance_type" {
  type    = string
  default = "t3.micro"
}
variable "root_volume_gb" {
  type    = number
  default = 20
}

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }
}

resource "aws_instance" "worker" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [var.security_group_id]
  iam_instance_profile   = var.instance_profile_name
  user_data              = file("${path.module}/user_data.sh")

  metadata_options {
    http_tokens   = "required" # IMDSv2 only
    http_endpoint = "enabled"
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_gb
    encrypted             = true
    delete_on_termination = true
  }

  credit_specification { cpu_credits = "standard" } # no T3 Unlimited surprise charges

  lifecycle { ignore_changes = [ami] }

  tags = { Name = "${var.name}-worker", Role = "ingestion-worker" }
}

output "instance_id" { value = aws_instance.worker.id }
output "public_ip" { value = aws_instance.worker.public_ip }
