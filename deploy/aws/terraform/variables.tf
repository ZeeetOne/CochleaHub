variable "region" {
  description = "AWS region; Paris keeps data in the EU (D20)."
  type        = string
  default     = "eu-west-3"
}

variable "instance_type" {
  description = "4 GB RAM: PostgreSQL, Orthanc, the API (with local embeddings) and nginx."
  type        = string
  default     = "t3.medium"
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
  description = "Where budget alerts are sent."
  type        = string
}
