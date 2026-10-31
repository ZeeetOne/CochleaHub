output "url" {
  value = "https://${aws_cloudfront_distribution.site.domain_name}"
}

output "distribution_id" {
  value = aws_cloudfront_distribution.site.id
}

output "instance_id" {
  value = aws_instance.app.id
}

output "ecr_repository_url" {
  value = aws_ecr_repository.api.repository_url
}

output "meshes_bucket" {
  value = aws_s3_bucket.meshes.bucket
}

output "frontend_bucket" {
  value = aws_s3_bucket.frontend.bucket
}

output "deploy_bucket" {
  value = aws_s3_bucket.deploy.bucket
}

output "region" {
  value = var.region
}
