output "resource_group_name" {
  value = local.rg_name
}

output "resource_group_location" {
  value = local.rg_location
}

output "container_app_fqdn" {
  value = azurerm_container_app.api.latest_revision_fqdn
}

output "api_base_url" {
  value = "https://${azurerm_container_app.api.latest_revision_fqdn}"
}

output "key_vault_name" {
  value = azurerm_key_vault.main.name
}

output "storage_account_name" {
  value = azurerm_storage_account.data.name
}

output "managed_identity_id" {
  value = azurerm_user_assigned_identity.aca.id
}
