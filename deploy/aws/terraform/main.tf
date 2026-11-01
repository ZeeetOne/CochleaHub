# CochleaHub on AWS, cost-saving variant (D23).
#
#   browser ──HTTPS──> CloudFront ──┬── /            -> S3 (frontend, private, OAC)
#        (basic auth at the edge)   ├── /api/*       -> EC2 :80 nginx -> FastAPI
#                                   └── /dicom-web/* -> EC2 :80 nginx -> Orthanc (GET only)
#   meshes: S3 (private), fetched by the browser through short-lived presigned URLs
#
# One t3.small (free-tier eligible, 2 GB + swap) runs PostgreSQL, Orthanc, the API and nginx in Docker. Production would use RDS,
# ECS/Fargate and a private subnet for Orthanc (D8); this variant keeps the same interfaces at a
# few dollars a day and is meant to be destroyed after a demo (`terraform destroy`).

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 6.0" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = "cochleahub", ManagedBy = "terraform" }
  }
}

data "aws_caller_identity" "me" {}

resource "random_id" "suffix" {
  byte_length = 4
}

locals {
  name   = "cochleahub"
  suffix = random_id.suffix.hex
}

# --- storage ---------------------------------------------------------------------------------

resource "aws_s3_bucket" "meshes" {
  bucket        = "${local.name}-meshes-${local.suffix}"
  force_destroy = true
}

resource "aws_s3_bucket" "frontend" {
  bucket        = "${local.name}-frontend-${local.suffix}"
  force_destroy = true
}

resource "aws_s3_bucket" "deploy" {
  bucket        = "${local.name}-deploy-${local.suffix}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "all" {
  for_each                = { meshes = aws_s3_bucket.meshes.id, frontend = aws_s3_bucket.frontend.id, deploy = aws_s3_bucket.deploy.id }
  bucket                  = each.value
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# the browser downloads meshes from S3 with presigned URLs, from the CloudFront origin only
resource "aws_s3_bucket_cors_configuration" "meshes" {
  bucket = aws_s3_bucket.meshes.id
  cors_rule {
    allowed_methods = ["GET", "HEAD"]
    allowed_origins = ["https://${aws_cloudfront_distribution.site.domain_name}"]
    allowed_headers = ["*"]
    max_age_seconds = 3600
  }
}

resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "CloudFrontRead"
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.frontend.arn}/*"
      Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.site.arn } }
    }]
  })
}

resource "aws_ecr_repository" "api" {
  name                 = "${local.name}-api"
  force_delete         = true
  image_tag_mutability = "MUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "api" {
  repository = aws_ecr_repository.api.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "keep only the latest image (demo: storage is billed per GB)"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 1 }
      action       = { type = "expire" }
    }]
  })
}

# --- compute ---------------------------------------------------------------------------------

data "aws_vpc" "default" {
  default = true
}

data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

data "aws_ec2_managed_prefix_list" "cloudfront" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}

resource "aws_security_group" "app" {
  name        = "${local.name}-app"
  description = "HTTP from CloudFront only; no SSH (administration via SSM Session Manager)"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description     = "CloudFront origin-facing"
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    prefix_list_ids = [data.aws_ec2_managed_prefix_list.cloudfront.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_iam_role" "app" {
  name = "${local.name}-app"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "ec2.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.app.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "app" {
  name = "${local.name}-app"
  role = aws_iam_role.app.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Sid = "Meshes", Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
      Resource = [aws_s3_bucket.meshes.arn, "${aws_s3_bucket.meshes.arn}/*"] },
      # uploaded documents (D25) can be deleted; meshes cannot
      { Sid = "DocumentDelete", Effect = "Allow", Action = ["s3:DeleteObject"],
      Resource = "${aws_s3_bucket.meshes.arn}/documents/*" },
      { Sid = "Bundle", Effect = "Allow", Action = ["s3:GetObject", "s3:ListBucket"],
      Resource = [aws_s3_bucket.deploy.arn, "${aws_s3_bucket.deploy.arn}/*"] },
      { Sid = "EcrToken", Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
      { Sid = "EcrPull", Effect = "Allow", Action = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"],
      Resource = aws_ecr_repository.api.arn },
      { Sid = "Secrets", Effect = "Allow", Action = ["ssm:GetParameter"],
      Resource = "arn:aws:ssm:${var.region}:${data.aws_caller_identity.me.account_id}:parameter/${local.name}/*" },
    ]
  })
}

resource "aws_iam_instance_profile" "app" {
  name = "${local.name}-app"
  role = aws_iam_role.app.name
}

resource "aws_instance" "app" {
  ami                    = data.aws_ssm_parameter.al2023.value
  instance_type          = var.instance_type
  iam_instance_profile   = aws_iam_instance_profile.app.name
  vpc_security_group_ids = [aws_security_group.app.id]
  user_data              = file("${path.module}/user_data.sh")

  root_block_device {
    volume_type = "gp3"
    volume_size = 20 # images (~4 GB) + data (~0.5 GB) + room
    encrypted   = true
  }
  metadata_options {
    http_tokens                 = "required" # IMDSv2 only
    http_put_response_hop_limit = 2          # containers reach the instance role
  }
  tags = { Name = "${local.name}-app" }
}

# --- edge ------------------------------------------------------------------------------------

resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = "${local.name}-frontend"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_function" "edge" {
  name    = "${local.name}-edge"
  runtime = "cloudfront-js-2.0"
  publish = true
  code    = templatefile("${path.module}/edge.js", { basic_auth = base64encode("${var.basic_auth_user}:${var.basic_auth_password}") })
}

data "aws_cloudfront_cache_policy" "optimized" {
  name = "Managed-CachingOptimized"
}

data "aws_cloudfront_cache_policy" "disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_origin_request_policy" "all_viewer" {
  name = "Managed-AllViewerExceptHostHeader"
}

resource "aws_cloudfront_distribution" "site" {
  enabled             = true
  comment             = "CochleaHub"
  default_root_object = "index.html"
  price_class         = "PriceClass_100"
  http_version        = "http2and3"

  origin {
    origin_id                = "frontend"
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
  }
  origin {
    origin_id   = "app"
    domain_name = aws_instance.app.public_dns
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "http-only"
      origin_ssl_protocols   = ["TLSv1.2"]
      origin_read_timeout    = 60
    }
    custom_header {
      name  = "X-Origin-Verify"
      value = var.origin_secret
    }
  }

  default_cache_behavior {
    target_origin_id       = "frontend"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = data.aws_cloudfront_cache_policy.optimized.id
    compress               = true
    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.edge.arn
    }
  }

  dynamic "ordered_cache_behavior" {
    for_each = ["/api/*", "/dicom-web/*"]
    content {
      path_pattern             = ordered_cache_behavior.value
      target_origin_id         = "app"
      viewer_protocol_policy   = "redirect-to-https"
      allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
      cached_methods           = ["GET", "HEAD"]
      cache_policy_id          = data.aws_cloudfront_cache_policy.disabled.id
      origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer.id
      compress                 = true
      function_association {
        event_type   = "viewer-request"
        function_arn = aws_cloudfront_function.edge.arn
      }
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }
  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

# --- secrets and cost guard ------------------------------------------------------------------

resource "aws_ssm_parameter" "origin_secret" {
  name  = "/${local.name}/origin_secret"
  type  = "SecureString"
  value = var.origin_secret
}

resource "aws_ssm_parameter" "postgres_password" {
  name  = "/${local.name}/postgres_password"
  type  = "SecureString"
  value = var.postgres_password
}

# The Anthropic API key is written by deploy.py from the local .env, so it never enters
# Terraform state.

resource "aws_budgets_budget" "monthly" {
  count        = var.create_budget ? 1 : 0
  name         = "${local.name}-monthly"
  budget_type  = "COST"
  limit_amount = var.monthly_budget_usd
  limit_unit   = "USD"
  time_unit    = "MONTHLY"
  # account-wide on purpose: tag filters need cost-allocation tags activated first
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}
