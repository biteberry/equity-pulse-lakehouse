output "instance_id" { value = module.ec2_worker.instance_id }
output "public_ip" { value = module.ec2_worker.public_ip }
output "bronze_bucket" { value = aws_s3_bucket.bronze.bucket }
output "vpc_id" { value = module.network.vpc_id }
