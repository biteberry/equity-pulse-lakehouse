output "instance_id" { value = module.ec2_worker.instance_id }
output "public_ip" { value = module.ec2_worker.public_ip }
output "landing_bucket" { value = data.aws_s3_bucket.landing.bucket }
output "vpc_id" { value = module.network.vpc_id }
