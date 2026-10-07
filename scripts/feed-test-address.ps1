# Start a temporary public test address for GRP's live feeds (ADR-0052, ADR-0061).
#
# It switches on the anonymous feed routes, starts grpcli.feed_relay (which answers only the feed
# paths), and opens a Cloudflare quick tunnel in front of the relay, never in front of the API.
# Paste the printed address into Share data -> Contribute a live feed -> the feed's card ->
# "Test it on Global Risk now". Press Ctrl+C to close the tunnel and the relay.
#
# A quick-tunnel address changes every time and stops when this script stops. Global Risk keeps
# a feed it has approved, so only send a test under a test name (..._test1).
param(
    [int]$Port = 8090
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Cloudflared = @(
    "C:\Program Files (x86)\cloudflared\cloudflared.exe",
    "C:\Program Files\cloudflared\cloudflared.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Cloudflared) {
    $Cloudflared = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
}
if (-not $Cloudflared) { throw "cloudflared is not installed. Install it with: winget install Cloudflare.cloudflared" }

function Test-Route([string]$Path) {
    try {
        (Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8000$Path" -TimeoutSec 30).StatusCode -eq 200
    } catch { $false }
}

# 1. The anonymous routes answer 404 until they are switched on.
if (-not (Test-Route "/api/v1/public/aq/sea/feed.json")) {
    Write-Host "Switching on the public feed routes (restarting GRP)..."
    $env:AIR_QUALITY_FEED_PUBLIC = "true"
    $env:FLOOD_FEED_PUBLIC = "true"
    & (Join-Path $PSScriptRoot "docker-desktop.ps1")
    if (-not (Test-Route "/api/v1/public/aq/sea/feed.json")) { throw "The air-quality feed route did not answer after the restart." }
}

$Logs = Join-Path $Root ".local\feed-test"
New-Item -ItemType Directory -Force -Path $Logs | Out-Null
$relay = $null
$tunnel = $null
try {
    # 2. The relay: only the feed paths, on its own port.
    $relay = Start-Process -FilePath $Python -ArgumentList "-u", "-m", "grpcli.feed_relay", "--port", $Port `
        -WorkingDirectory $Root -RedirectStandardOutput (Join-Path $Logs "relay.log") `
        -RedirectStandardError (Join-Path $Logs "relay.err.log") -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 2

    # 3. The tunnel, in front of the relay.
    $tunnelLog = Join-Path $Logs "tunnel.log"
    if (Test-Path $tunnelLog) { Remove-Item $tunnelLog }
    $tunnel = Start-Process -FilePath $Cloudflared -ArgumentList "tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:$Port" `
        -RedirectStandardError $tunnelLog -RedirectStandardOutput (Join-Path $Logs "tunnel.out.log") -PassThru -WindowStyle Hidden
    $address = $null
    foreach ($i in 1..30) {
        Start-Sleep -Seconds 2
        if (Test-Path $tunnelLog) {
            $match = Select-String -Path $tunnelLog -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" | Select-Object -First 1
            if ($match) { $address = $match.Matches[0].Value; break }
        }
    }
    if (-not $address) { throw "The tunnel did not print an address; see $tunnelLog" }

    Write-Host ""
    Write-Host "Test address: $address" -ForegroundColor Green
    Write-Host "  PM2.5 feed: $address/air-quality/feed.json"
    Write-Host "  Flood feed: $address/feed.json"
    try { Set-Clipboard -Value $address; Write-Host "  (copied to the clipboard)" } catch {}
    Write-Host ""
    Write-Host "Paste it into Share data -> Contribute a live feed -> 'Test it on Global Risk now'."
    Write-Host "Keep this window open while Global Risk reads the feed. Press Ctrl+C to stop."
    while ($true) {
        Start-Sleep -Seconds 5
        if ($tunnel.HasExited) { throw "The tunnel stopped." }
        if ($relay.HasExited) { throw "The relay stopped; see $Logs\relay.err.log" }
    }
} finally {
    foreach ($process in @($tunnel, $relay)) {
        if ($process -and -not $process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
    }
    Write-Host "Tunnel and relay stopped. The public feed routes stay on until GRP restarts; run .\scripts\docker-desktop.ps1 to switch them off."
}
