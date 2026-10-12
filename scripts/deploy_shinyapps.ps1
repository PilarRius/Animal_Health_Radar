# Deploy Animal Health Radar to personal shinyapps.io (account: pilarius).
# Does NOT use work accounts (eufmd / foodandagricultureorganization).
#
# Stages a lean bundle so gitignored data/processed + interim artefacts are included.
#
# Usage (from repo root):
#   1. Ensure .env.shinyapps has TOKEN + SECRET (gitignored)
#   2. .\scripts\deploy_shinyapps.ps1

$ErrorActionPreference = "Stop"
$Root = if ($PSScriptRoot) {
    Split-Path -Parent $PSScriptRoot
} else {
    Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}
Set-Location $Root
Write-Host "Repo root: $Root"

$EnvFile = Join-Path $Root ".env.shinyapps"
if (-not (Test-Path $EnvFile)) {
    Write-Error "Missing $EnvFile - copy .env.shinyapps.example and fill credentials."
}

# Load into locals. Do NOT set SHINYAPPS_TOKEN/SECRET/ACCOUNT in the process env:
# rsconnect treats those as CLI auth and then rejects --name.
$account = $null
$nickname = $null
$token = $null
$secret = $null
$appId = $null
$appTitle = "Animal Health Radar"

# Use foreach (not ForEach-Object) so assignments stay in script scope.
foreach ($raw in Get-Content $EnvFile) {
    $line = $raw.Trim()
    if (-not $line -or $line.StartsWith("#")) { continue }
    $parts = $line -split "=", 2
    if ($parts.Count -ne 2) { continue }
    $key = $parts[0].Trim()
    $val = $parts[1].Trim()
    switch ($key) {
        "SHINYAPPS_ACCOUNT"   { $account = $val }
        "SHINYAPPS_NICKNAME"  { $nickname = $val }
        "SHINYAPPS_TOKEN"     { $token = $val }
        "SHINYAPPS_SECRET"    { $secret = $val }
        "SHINYAPPS_APP_ID"    { $appId = $val }
        "SHINYAPPS_APP_TITLE" { if ($val) { $appTitle = $val } }
    }
}

foreach ($pair in @(
    @{ Name = "SHINYAPPS_ACCOUNT"; Value = $account },
    @{ Name = "SHINYAPPS_NICKNAME"; Value = $nickname },
    @{ Name = "SHINYAPPS_TOKEN"; Value = $token },
    @{ Name = "SHINYAPPS_SECRET"; Value = $secret },
    @{ Name = "SHINYAPPS_APP_ID"; Value = $appId }
)) {
    if ([string]::IsNullOrWhiteSpace($pair.Value)) {
        Write-Error "Set $($pair.Name) in .env.shinyapps before deploying."
    }
}

# Clear any leftover auth env vars from prior runs in this shell.
foreach ($key in @(
    "SHINYAPPS_TOKEN", "SHINYAPPS_SECRET", "SHINYAPPS_ACCOUNT",
    "CONNECT_TOKEN", "CONNECT_SECRET", "CONNECT_ACCOUNT",
    "RSC_TOKEN", "RSC_SECRET", "RSC_ACCOUNT"
)) {
    Remove-Item -Path "Env:$key" -ErrorAction SilentlyContinue
}

Write-Host "Ensuring shinyapps nickname '$nickname' (account=$account)..."
rsconnect add --account $account --name $nickname --token $token --secret $secret

$stage = Join-Path $Root "_shiny_deploy"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Path $stage | Out-Null

foreach ($d in @("dashboard", "src", "config")) {
    $dest = Join-Path $stage $d
    robocopy (Join-Path $Root $d) $dest /E /NFL /NDL /NJH /NJS /nc /ns /np `
        /XD __pycache__ .git /XF *.pyc | Out-Null
}
Copy-Item (Join-Path $Root "app.py"), (Join-Path $Root "requirements.txt") -Destination $stage
if (Test-Path (Join-Path $Root "pyproject.toml")) {
    Copy-Item (Join-Path $Root "pyproject.toml") -Destination $stage
}

New-Item -ItemType Directory -Force -Path (Join-Path $stage "data\processed"), (Join-Path $stage "data\interim") | Out-Null
Copy-Item (Join-Path $Root "data\processed\*.parquet") -Destination (Join-Path $stage "data\processed") -ErrorAction SilentlyContinue
Copy-Item (Join-Path $Root "data\processed\*.json") -Destination (Join-Path $stage "data\processed") -ErrorAction SilentlyContinue
Copy-Item (Join-Path $Root "data\interim\provenance.parquet"), (Join-Path $Root "data\interim\signals.parquet") `
    -Destination (Join-Path $stage "data\interim") -ErrorAction SilentlyContinue

if (-not (Test-Path (Join-Path $stage "data\processed\predictions.parquet"))) {
    Write-Error "Missing data/processed/predictions.parquet - run the pipeline before deploying."
}

Write-Host "Deploying '$appTitle' to app-id $appId via nickname '$nickname'..."
# Use argument array so the title with spaces is one argv.
$deployArgs = @(
    "deploy", "shiny", $stage,
    "--name", $nickname,
    "--app-id", $appId,
    "--title", $appTitle
)
& rsconnect @deployArgs
if ($LASTEXITCODE -ne 0) {
    Write-Error "rsconnect deploy failed with exit code $LASTEXITCODE"
}

Write-Host "Expected URL: https://$account.shinyapps.io/animal_health_radar/"
