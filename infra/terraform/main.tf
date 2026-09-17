terraform {
  required_version = ">= 1.5.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.117"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "azurerm" {
  features {
    key_vault {
      purge_soft_delete_on_destroy = true
    }
  }
}

data "azurerm_client_config" "current" {}

resource "random_string" "suffix" {
  length  = 6
  upper   = false
  special = false
}

locals {
  name_prefix = "${var.project_name}-${var.environment}"
  suffix      = random_string.suffix.result
  rg_name     = var.reuse_existing_rg ? data.azurerm_resource_group.existing[0].name : azurerm_resource_group.main[0].name
  rg_location = var.reuse_existing_rg ? data.azurerm_resource_group.existing[0].location : azurerm_resource_group.main[0].location
}

# Prefer reusing the caller's RG (e.g. IgniteChat) to avoid extra resource sprawl/cost.
data "azurerm_resource_group" "existing" {
  count = var.reuse_existing_rg ? 1 : 0
  name  = var.resource_group_name
}

resource "azurerm_resource_group" "main" {
  count    = var.reuse_existing_rg ? 0 : 1
  name     = coalesce(var.resource_group_name, "${local.name_prefix}-rg")
  location = var.location
  tags     = var.tags
}

resource "azurerm_log_analytics_workspace" "main" {
  name                = "${local.name_prefix}-law-${local.suffix}"
  location            = local.rg_location
  resource_group_name = local.rg_name
  sku                 = "PerGB2018"
  retention_in_days   = var.log_retention_days
  tags                = var.tags
}

resource "azurerm_container_app_environment" "main" {
  name                       = "${local.name_prefix}-cae-${local.suffix}"
  location                   = local.rg_location
  resource_group_name        = local.rg_name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  tags                       = var.tags
}

resource "azurerm_storage_account" "data" {
  name                     = substr(replace("${var.project_name}${var.environment}${local.suffix}", "-", ""), 0, 24)
  resource_group_name      = local.rg_name
  location                 = local.rg_location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  min_tls_version          = "TLS1_2"
  tags                     = var.tags
}

resource "azurerm_storage_share" "sessions" {
  name                 = "ignite-sessions"
  storage_account_name = azurerm_storage_account.data.name
  quota                = var.file_share_quota_gb
}

resource "azurerm_container_app_environment_storage" "sessions" {
  name                         = "ignite-sessions"
  container_app_environment_id = azurerm_container_app_environment.main.id
  account_name                 = azurerm_storage_account.data.name
  share_name                   = azurerm_storage_share.sessions.name
  access_key                   = azurerm_storage_account.data.primary_access_key
  access_mode                  = "ReadWrite"
}

resource "azurerm_key_vault" "main" {
  name                       = substr("${var.project_name}-${var.environment}-kv-${local.suffix}", 0, 24)
  location                   = local.rg_location
  resource_group_name        = local.rg_name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  soft_delete_retention_days = 7
  purge_protection_enabled   = false
  tags                       = var.tags

  access_policy {
    tenant_id = data.azurerm_client_config.current.tenant_id
    object_id = data.azurerm_client_config.current.object_id

    secret_permissions = ["Get", "List", "Set", "Delete", "Purge"]
  }
}

resource "azurerm_key_vault_secret" "api_key" {
  name         = "ignite-api-key"
  value        = var.ignite_api_key
  key_vault_id = azurerm_key_vault.main.id
}

resource "azurerm_user_assigned_identity" "aca" {
  name                = "${local.name_prefix}-mi"
  location            = local.rg_location
  resource_group_name = local.rg_name
  tags                = var.tags
}

resource "azurerm_key_vault_access_policy" "aca" {
  key_vault_id = azurerm_key_vault.main.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = azurerm_user_assigned_identity.aca.principal_id

  secret_permissions = ["Get", "List"]
}

resource "azurerm_container_app" "api" {
  name                         = "${local.name_prefix}-api"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = local.rg_name
  revision_mode                = "Single"
  tags                         = var.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.aca.id]
  }

  registry {
    server   = var.acr_login_server
    identity = azurerm_user_assigned_identity.aca.id
  }

  secret {
    name                = "ignite-api-key"
    key_vault_secret_id = azurerm_key_vault_secret.api_key.versionless_id
    identity            = azurerm_user_assigned_identity.aca.id
  }

  template {
    min_replicas = var.min_replicas
    max_replicas = var.max_replicas

    container {
      name   = "ignite-api"
      image  = var.container_image
      cpu    = var.container_cpu
      memory = var.container_memory

      env {
        name  = "IGNITE_RUNTIME_MODE"
        value = "server"
      }
      env {
        name  = "IGNITE_DATA_DIR"
        value = "/data"
      }
      env {
        name        = "IGNITE_API_KEY"
        secret_name = "ignite-api-key"
      }
      env {
        name  = "IGNITE_API_HOST"
        value = "0.0.0.0"
      }
      env {
        name  = "IGNITE_API_PORT"
        value = "8000"
      }

      volume_mounts {
        name = "sessions"
        path = "/data"
      }
    }

    volume {
      name         = "sessions"
      storage_type = "AzureFile"
      storage_name = azurerm_container_app_environment_storage.sessions.name
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "auto"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  depends_on = [azurerm_key_vault_access_policy.aca]
}
