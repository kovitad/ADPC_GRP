param(
    # SERVIR account emails to make Platform Admin in the local database.
    [string[]]$AdminEmail = @(),
    # SERVIR account emails to make Hub Admin of the adpc Hub (can then manage members).
    [string[]]$HubAdminEmail = @(),
    [switch]$Down,
    # Delete the local database and object volumes, then rebuild from empty. Everything
    # imported locally is lost, including every dataset version and assessment. Local
    # development only; it asks before it deletes.
    [switch]$Reset,
    # Import the delivered Thailand baseline and activate it, so a fresh stack is usable
    # without three Data Library imports and a Platform activation by hand.
    [switch]$LoadBaseline
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

if ($Reset) {
    Write-Host "This deletes the local GRP database and object storage volumes." -ForegroundColor Yellow
    Write-Host "Every imported dataset version, feature and assessment on this machine is lost."
    $answer = Read-Host "Type RESET to continue"
    if ($answer -cne "RESET") {
        Write-Host "Nothing was deleted."
        return
    }
    # A reset leaves an empty data library, so load the baseline back unless told otherwise.
    if (-not $PSBoundParameters.ContainsKey("LoadBaseline")) { $LoadBaseline = $true }
    # Docker writes progress to stderr, which "Stop" turns into a terminating error — and
    # aborting here would leave the volumes gone and nothing rebuilt.
    $ErrorActionPreference = $NativeErrors
    docker @Compose down -v
    $ErrorActionPreference = "Stop"
    if ($LASTEXITCODE -ne 0) { throw "docker compose down -v failed; nothing was rebuilt." }
    Write-Host "Volumes removed. Continuing with a fresh stack."
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

# Copy selected keys from the ignored .env into secret files. Values are never printed.
function Get-DotEnvValue([string]$Name) {
    $envFile = Join-Path $RepositoryRoot ".env"
    if (-not (Test-Path -LiteralPath $envFile)) { return $null }
    foreach ($line in Get-Content -LiteralPath $envFile) {
        if ($line -match "^\s*$([regex]::Escape($Name))\s*=\s*(.*)$") {
            $value = $Matches[1].Trim().Trim('"').Trim("'")
            if ($value) { return $value }
        }
    }
    return $null
}

function Write-SecretFromEnv([string]$SecretName, [string[]]$EnvNames) {
    foreach ($name in $EnvNames) {
        $value = Get-DotEnvValue $name
        if ($value) {
            [System.IO.File]::WriteAllText((Join-Path $SecretRoot $SecretName), $value)
            return $true
        }
    }
    return $false
}

$LocalAiKey = Join-Path $RepositoryRoot ".local/secrets/ai_key_adpc"
if (Test-Path -LiteralPath $LocalAiKey) {
    Copy-Item -LiteralPath $LocalAiKey -Destination (Join-Path $SecretRoot "ai_key_adpc") -Force
} elseif (-not (Write-SecretFromEnv "ai_key_adpc" @("OPENAI_API_KEY"))) {
    Write-Warning "No AI provider key found; the AI test call will report AI unavailable."
}
if (-not (Write-SecretFromEnv "langfuse_secret_key" @("LANGFUSE_SECRET_KEY"))) {
    Write-Warning "No LANGFUSE_SECRET_KEY in .env; Langfuse export stays off."
}
$env:LANGFUSE_HOST = Get-DotEnvValue "LANGFUSE_HOST"
if (-not $env:LANGFUSE_HOST) { $env:LANGFUSE_HOST = Get-DotEnvValue "LANGFUSE_BASE_URL" }
$env:LANGFUSE_PUBLIC_KEY = Get-DotEnvValue "LANGFUSE_PUBLIC_KEY"
$model = Get-DotEnvValue "AI_MODEL"
if (-not $model) { $model = Get-DotEnvValue "OPENAI_MODEL" }
if ($model) { $env:AI_MODEL = $model }

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

# Synthetic RP100 test case for Increment 1 (idempotent).
docker @Compose exec api python -m grpcli.seed synthetic-rp100

foreach ($email in $AdminEmail) {
    docker @Compose exec api python -m grpcli.admin bootstrap-platform-admin --email $email
    docker @Compose exec api python -m grpcli.admin ensure-hub --actor-email $email --code adpc --name "ADPC Hub"
}

foreach ($email in $HubAdminEmail) {
    $actor = if ($AdminEmail.Count -gt 0) { $AdminEmail[0] } else { $email }
    docker @Compose exec api python -m grpcli.admin assign-member --actor-email $actor --email $email --hub-code adpc --role admin
}

if ($LoadBaseline) {
    if ($AdminEmail.Count -eq 0) {
        Write-Warning "Skipping the baseline load: -LoadBaseline needs -AdminEmail."
    } else {
        docker @Compose exec api python -m grpcli.baseline load --actor-email $AdminEmail[0]
        if ($LASTEXITCODE -ne 0) { throw "Baseline load failed; see the output above." }
    }
}

Write-Host ""
Write-Host "GRP is running at http://127.0.0.1:8000  (admin: /admin, assessments: /assessments.html, planning: /planning.html)"
Write-Host "Logs: docker compose -f deploy/compose.desktop.yml logs -f api worker"
Write-Host "Stop: .\scripts\docker-desktop.ps1 -Down"
