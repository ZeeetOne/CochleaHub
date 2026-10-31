variable "region" {
  description = "AWS region; Paris keeps data in the EU (D20)."
  type        = string
  default     = "eu-west-3"
}

variable "instance_type" {
  description = <<-EOT
    Needs at least 4 GB RAM for PostgreSQL, Orthanc, the API (with local embeddings) and nginx.
    m7i-flex.large (2 vCPU, 8 GB) is free-tier eligible on accounts created from July 2025;
    if it is not offered in the region, use c7i-flex.large (4 GB) or t3.medium (paid plan).
  EOT
  type        = string
  default     = "m7i-flex.large"
}

variable "create_budget" {
  description = "Create the monthly budget alert. Set false on an AWS free plan, which never charges."
  type        = bool
  default     = true
}

variable "basic_auth_user" {
  description = "Username for the demo's HTTP basic auth at CloudFront."
  type        = string
  default     = "cochleahub"
}

variable "basic_auth_password" {
  description = "Password for the demo's HTTP basic auth (set by deploy.py)."
  type        = string
  sensitive   = true
}

variable "origin_secret" {
  description = "Header value CloudFront sends to the instance; nginx rejects requests without it."
  type        = string
  sensitive   = true
}

variable "postgres_password" {
  type      = string
  sensitive = true
}

variable "monthly_budget_usd" {
  description = "Monthly account-wide budget alert threshold."
  type        = string
  default     = "15"
}

variable "alert_email" {
  default     = ""
  description = "Where budget alerts are sent."
  type        = string
}
