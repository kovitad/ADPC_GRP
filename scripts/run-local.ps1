param(
    [switch]$RegisterSigClient,
    [ValidateRange(1, 65535)]
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepositoryRoot

$VenvPython = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"
$Python = if (Test-Path -LiteralPath $VenvPython) { $VenvPython } else { "python" }
$ClientIdFile = Join-Path $RepositoryRoot ".local\servir_auth_client_id"
$RedirectUri = "http://127.0.0.1:$Port/api/v1/auth/callback"

& $Python -m grp.dev

if ($RegisterSigClient) {
    & $Python -m grp.oauth register-client `
        --redirect-uri $RedirectUri `
        --client-name "ADPC GRP local" `
        --output-file $ClientIdFile
}

if (-not (Test-Path -LiteralPath $ClientIdFile)) {
    throw "SIG OAuth client is missing. Re-run with -RegisterSigClient once."
}

$ClientId = (Get-Content -LiteralPath $ClientIdFile -Raw).Trim()
if (-not $ClientId) {
    throw "SIG OAuth client ID file is empty: $ClientIdFile"
}

$env:GRP_ENV = "dev"
$env:GRP_PUBLIC_BASE_URL = "http://127.0.0.1:$Port"
$env:STORAGE_ROOT = ".local/data"
$env:DATABASE_URL_FILE = ".local/secrets/database_url"
$env:SESSION_SECRET_FILE = ".local/secrets/session_secret"
$env:SIG_MCP_BASE_URL = "https://servirplatform.sig-gis.com/mcp"
$env:SERVIR_AUTH_ISSUER = "https://welcoming-splendor-62-staging.authkit.app"
$env:SERVIR_AUTH_CLIENT_ID = $ClientId
$env:SERVIR_AUTH_REDIRECT_URI = $RedirectUri
$env:SERVIR_AUTH_CLIENT_SECRET_FILE = ".local/secrets/servir_auth_client_secret"
$env:AI_KEY_FILE_ADPC = ".local/secrets/ai_key_adpc"

Write-Host "Starting GRP at http://127.0.0.1:$Port"
& $Python -m uvicorn api.main:app --host 127.0.0.1 --port $Port
