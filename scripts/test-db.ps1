$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'postgres-common.ps1')
$config = Get-ProjectPostgresConfig
Invoke-ProjectPsql -Config $config -PsqlArgs @('-c', 'SELECT current_database() AS database, current_user AS username, version() AS server_version;', '-c', 'BEGIN; CREATE TEMP TABLE fund_lab_connection_check (value integer); INSERT INTO fund_lab_connection_check VALUES (1); SELECT value AS read_write_check FROM fund_lab_connection_check; ROLLBACK;')
Write-Host 'Database connection and temporary read/write check passed. No persistent tables were created.'
