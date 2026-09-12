# Shared helpers. Never evaluate .env as PowerShell or print credentials.
function Get-ProjectPostgresConfig {
    $config = @{
        PGHOST = '127.0.0.1'; PGPORT = '5432'; PGDATABASE = 'simulate_alipay'
        PGUSER = 'postgres'; PGPASSWORD = ''; PG_BIN = ''
    }
    $envFile = Join-Path (Split-Path $PSScriptRoot -Parent) '.env'
    if (Test-Path -LiteralPath $envFile) {
        foreach ($line in Get-Content -LiteralPath $envFile -Encoding utf8) {
            if ($line -match '^\s*(PGHOST|PGPORT|PGDATABASE|PGUSER|PGPASSWORD|PG_BIN)\s*=(.*)$') {
                $key = $Matches[1]
                $value = $Matches[2].Trim()
                if ($value.Length -ge 2 -and (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'")))) {
                    $value = $value.Substring(1, $value.Length - 2)
                }
                $config[$key] = $value
            }
        }
    }
    foreach ($key in @($config.Keys)) {
        $value = [Environment]::GetEnvironmentVariable($key, 'Process')
        if (-not [string]::IsNullOrEmpty($value)) { $config[$key] = $value }
    }
    foreach ($key in @('PGHOST', 'PGPORT', 'PGDATABASE', 'PGUSER')) {
        if ([string]::IsNullOrWhiteSpace($config[$key])) { throw "$key must not be empty." }
    }
    $port = 0
    if (-not [int]::TryParse($config.PGPORT, [ref]$port) -or $port -lt 1 -or $port -gt 65535) {
        throw 'PGPORT must be between 1 and 65535.'
    }
    return $config
}

function Find-ProjectPsql {
    param([hashtable]$Config)
    if ($Config.PG_BIN) {
        $candidate = Join-Path $Config.PG_BIN 'psql.exe'
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
        throw 'PG_BIN does not contain psql.exe. Correct .env or the PG_BIN environment variable.'
    }
    $command = Get-Command psql -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command) { return $command.Source }
    $installations = @(Get-ItemProperty 'HKLM:\SOFTWARE\PostgreSQL\Installations\*' -ErrorAction SilentlyContinue)
    foreach ($installation in $installations) {
        $candidate = Join-Path $installation.'Base Directory' 'bin\psql.exe'
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    throw 'psql was not found. Install PostgreSQL and set PG_BIN in .env to its bin directory.'
}

function Invoke-ProjectPsql {
    param(
        [hashtable]$Config,
        [string]$Database = $Config.PGDATABASE,
        [string[]]$PsqlArgs = @(),
        [switch]$Interactive
    )
    $psql = Find-ProjectPsql -Config $Config
    $oldPassword = [Environment]::GetEnvironmentVariable('PGPASSWORD', 'Process')
    $oldTimeout = [Environment]::GetEnvironmentVariable('PGCONNECT_TIMEOUT', 'Process')
    try {
        [Environment]::SetEnvironmentVariable('PGPASSWORD', $Config.PGPASSWORD, 'Process')
        $env:PGCONNECT_TIMEOUT = '5'
        $connectionArgs = @('-X', '-h', $Config.PGHOST, '-p', $Config.PGPORT, '-U', $Config.PGUSER, '-d', $Database, '-v', 'ON_ERROR_STOP=1')
        if (-not $Interactive) { $connectionArgs += '-w' }
        & $psql @connectionArgs @PsqlArgs
        if ($LASTEXITCODE -ne 0) {
            throw "psql failed (exit $LASTEXITCODE). Check PostgreSQL service, connection settings, and credentials in .env."
        }
    } finally {
        [Environment]::SetEnvironmentVariable('PGPASSWORD', $oldPassword, 'Process')
        [Environment]::SetEnvironmentVariable('PGCONNECT_TIMEOUT', $oldTimeout, 'Process')
    }
}
