param(
    # SERVIR account emails to make Platform Admin in the local database.
    [string[]]$AdminEmail = @(),
    [switch]$Down
)

$ErrorActionPreference = "Stop"
# Docker writes progress to stderr; with Windows PowerShell "Stop" that aborts the script.
$NativeErrors = "Continue"
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepositoryRoot
$Compose = @("compose", "-f", "deploy/compose.desktop.yml")

if ($Down) {
    docker @Compose down
    return
}

$SecretRoot = Join-Path $RepositoryRoot ".local\docker\secrets"
New-Item -ItemType Directory -Force $SecretRoot | Out-Null

function New-SecretValue {
    $bytes = New-Object byte[] 36
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return [Convert]::ToBase64String($bytes).Replace("+", "A").Replace("/", "B").Replace("=", "")
}

function Write-SecretOnce([string]$Name, [scriptblock]$Value) {
    $path = Join-Path $SecretRoot $Name
    if (-not (Test-Path -LiteralPath $path)) {
        [System.IO.File]::WriteAllText($path, (& $Value))
    }
}

Write-SecretOnce "postgres_password" { New-SecretValue }
$Password = (Get-Content -LiteralPath (Join-Path $SecretRoot "postgres_password") -Raw).Trim()
Write-SecretOnce "database_url" { "postgresql+psycopg://grp:$Password@db:5432/grp" }
Write-SecretOnce "session_secret" { New-SecretValue }

# Reuse the localhost SIG client registered by run-local.ps1 -RegisterSigClient (same callback).
$ClientIdFile = Join-Path $RepositoryRoot ".local\servir_auth_client_id"
if (Test-Path -LiteralPath $ClientIdFile) {
    $env:SERVIR_AUTH_CLIENT_ID = (Get-Content -LiteralPath $ClientIdFile -Raw).Trim()
} else {
    Write-Warning "No SIG client ID found; sign-in will show 'unavailable'. Run .\scripts\run-local.ps1 -RegisterSigClient once."
}

$ErrorActionPreference = $NativeErrors
docker @Compose up -d --build --wait
if ($LASTEXITCODE -ne 0) { throw "docker compose up failed; see: docker compose -f deploy/compose.desktop.yml logs" }

foreach ($email in $AdminEmail) {
    docker @Compose exec api python -m grp.admin bootstrap-platform-admin --email $email
    docker @Compose exec api python -m grp.admin ensure-hub --actor-email $email --code adpc --name "ADPC Hub"
}

Write-Host ""
Write-Host "GRP is starting at http://127.0.0.1:8000  (admin: http://127.0.0.1:8000/admin)"
Write-Host "Logs: docker compose -f deploy/compose.desktop.yml logs -f api worker"
Write-Host "Stop: .\scripts\docker-desktop.ps1 -Down"
