variable "region" {
  description = "AWS region; an EU region keeps data in the EU (D20). The demo account is restricted to eu-north-1 by a service control policy (D23)."
  type        = string
  default     = "eu-north-1"
}

variable "instance_type" {
  description = <<-EOT
    Smallest type that runs PostgreSQL, Orthanc, the API (local embeddings) and nginx: t3.small
    (2 vCPU, 2 GB + 2 GB swap from user data), free-tier eligible. The API image is built on the
    laptop, never on the instance. If the API runs out of memory, use c7i-flex.large (4 GB) or
    m7i-flex.large (8 GB); both are free-tier eligible too, at a higher hourly price.
  EOT
  type        = string
  default     = "t3.small"
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
