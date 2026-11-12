# EC2 instance role: SSM managed core + least-privilege access to the Bronze bucket.

variable "name" { type = string }
variable "bronze_bucket_arn" { type = string }

data "aws_iam_policy_document" "ec2_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "worker" {
  name               = "${var.name}-ec2-worker"
  assume_role_policy = data.aws_iam_policy_document.ec2_trust.json
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.worker.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "bronze" {
  statement {
    sid       = "WriteBronzeOnly"
    actions   = ["s3:PutObject"]
    resources = ["${var.bronze_bucket_arn}/*"]
  }
}

resource "aws_iam_role_policy" "bronze" {
  name   = "bronze-write"
  role   = aws_iam_role.worker.id
  policy = data.aws_iam_policy_document.bronze.json
}

resource "aws_iam_instance_profile" "worker" {
  name = "${var.name}-ec2-worker"
  role = aws_iam_role.worker.name
}

output "instance_profile_name" { value = aws_iam_instance_profile.worker.name }
output "role_arn" { value = aws_iam_role.worker.arn }
