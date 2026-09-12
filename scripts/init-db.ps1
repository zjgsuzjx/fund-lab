$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'postgres-common.ps1')
$config = Get-ProjectPostgresConfig
$sqlFile = Join-Path $PSScriptRoot 'sql\init-db.sql'
Invoke-ProjectPsql -Config $config -Database 'postgres' -PsqlArgs @('-v', "db_name=$($config.PGDATABASE)", '-f', $sqlFile)
Write-Host 'Project database is ready. Existing databases and their contents are preserved.'
