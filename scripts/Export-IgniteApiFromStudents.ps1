<#
.SYNOPSIS
  Export ignite-api ACA env/scale/image from Students (run while sub + CAE are enabled).

.EXAMPLE
  az login --tenant 3209b50b-b79b-43dc-9fc4-8d42c406dd61
  az account set --subscription 3636d316-ce18-4497-99d7-ec747ffc4289
  pwsh -File .\scripts\Export-IgniteApiFromStudents.ps1
#>
[CmdletBinding()]
param(
    [string]$StudentsSubscriptionId = "3636d316-ce18-4497-99d7-ec747ffc4289",
    [string]$OutFile = ""
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($OutFile)) {
    $OutFile = Join-Path $PSScriptRoot "ignite-api-payg-export.json"
}

az account set --subscription $StudentsSubscriptionId | Out-Null
$app = az containerapp show -g IgniteAPI -n ignite-api -o json | ConvertFrom-Json
if (-not $app.properties.template.containers[0].image) {
    throw "ignite-api template empty or CAE suspended. Re-enable Students subscription first."
}

$c = $app.properties.template.containers[0]
$export = [ordered]@{
    image      = $c.image
    cpu        = $c.resources.cpu
    memory     = $c.resources.memory
    minReplicas = $app.properties.template.scale.minReplicas
    maxReplicas = $app.properties.template.scale.maxReplicas
    targetPort = $app.properties.configuration.ingress.targetPort
    env        = @($c.env | ForEach-Object {
            @{
                name        = $_.name
                value       = $_.value
                secretRef   = $_.secretRef
            }
        })
}
$export | ConvertTo-Json -Depth 6 | Set-Content -Path $OutFile -Encoding UTF8
Write-Host "Wrote $OutFile" -ForegroundColor Green
Write-Host "Then: pwsh -File .\scripts\Deploy-IgniteApiAca.ps1 -ExportFile $OutFile"
