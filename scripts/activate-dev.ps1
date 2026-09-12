$ErrorActionPreference = 'Stop'
# Dot-source this script to retain the Conda function in the current shell.
# Load Conda's own trusted shell hook; no global conda init is performed.
$condaExecutable = $env:CONDA_EXE
if (-not $condaExecutable -or -not (Test-Path -LiteralPath $condaExecutable -PathType Leaf)) {
    $condaCommand = Get-Command conda -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $condaCommand) {
        throw 'Conda was not found. Open a Conda-enabled PowerShell or add Conda to PATH.'
    }
    $condaExecutable = $condaCommand.Source
}
$hook = & $condaExecutable shell.powershell hook | Out-String
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($hook)) {
    throw 'Could not load the Conda PowerShell hook.'
}
$previousNativeArgumentMode = $PSNativeCommandArgumentPassing
try {
    # Conda 4.x's module passes empty optional arguments; PowerShell 7.3+
    # preserves those by default. Use legacy passing only for Conda calls.
    $PSNativeCommandArgumentPassing = 'Legacy'
    Invoke-Expression $hook
} finally {
    $PSNativeCommandArgumentPassing = $previousNativeArgumentMode
}
# Keep compatibility scoped to the loaded Conda module, including deactivate.
& (Get-Module Conda) { $script:PSNativeCommandArgumentPassing = 'Legacy' }
conda activate simulate-alipay
if ($env:CONDA_DEFAULT_ENV -ne 'simulate-alipay') {
    throw 'Activation failed. Create the environment first: conda env create -f environment.yml'
}
Write-Host 'Conda environment simulate-alipay is active. PostgreSQL uses the system installation.'
python --version
