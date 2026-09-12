$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'postgres-common.ps1')
$config = Get-ProjectPostgresConfig
Invoke-ProjectPsql -Config $config -PsqlArgs $args -Interactive
