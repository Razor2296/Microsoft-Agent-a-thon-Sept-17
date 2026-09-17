variable "project_name" {
  type        = string
  description = "Short project name used in Azure resource names"
  default     = "ignitechat"
}

variable "environment" {
  type        = string
  description = "Environment name (dev, staging, prod)"
  default     = "dev"
}

variable "location" {
  type        = string
  description = "Azure region (must match existing resource group when reuse_existing_rg=true)"
  default     = "eastus"
}

variable "resource_group_name" {
  type        = string
  description = "Existing Azure resource group to reuse (cost-safe: does not create a new RG)"
  default     = "IgniteChat"
}

variable "reuse_existing_rg" {
  type        = bool
  description = "If true, deploy into an existing RG instead of creating a new one"
  default     = true
}

variable "tags" {
  type        = map(string)
  description = "Common resource tags"
  default = {
    project = "IgniteChat"
    managed = "terraform"
    cost    = "dev-low"
  }
}

variable "container_image" {
  type        = string
  description = "Fully qualified container image for the ACA API"
}

variable "acr_login_server" {
  type        = string
  description = "Azure Container Registry login server (e.g. myacr.azurecr.io)"
}

variable "ignite_api_key" {
  type        = string
  description = "API key shared by desktop clients and ACA"
  sensitive   = true
}

variable "container_cpu" {
  type        = number
  description = "vCPU allocation. Keep low for cost; raise only if Whisper is too slow."
  default     = 1.0
}

variable "container_memory" {
  type        = string
  description = "Memory allocation. 2Gi is enough for initial ACA smoke tests."
  default     = "2Gi"
}

variable "min_replicas" {
  type        = number
  description = "0 = scale-to-zero (no idle compute cost; cold start applies)"
  default     = 0
}

variable "max_replicas" {
  type        = number
  description = "Cap replicas hard to control spend"
  default     = 1
}

variable "file_share_quota_gb" {
  type        = number
  description = "Azure Files quota; keep small for sessions JSON only"
  default     = 5
}

variable "log_retention_days" {
  type        = number
  description = "Log Analytics retention (lower = cheaper)"
  default     = 7
}
