param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$AdminArguments
)

$ErrorActionPreference = "Stop"
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepositoryRoot

$VenvPython = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"
$Python = if (Test-Path -LiteralPath $VenvPython) { $VenvPython } else { "python" }
$env:DATABASE_URL_FILE = ".local/secrets/database_url"

& $Python -m grpcli.admin @AdminArguments
exit $LASTEXITCODE
