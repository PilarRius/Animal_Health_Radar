# Deploy Animal Health Radar to personal shinyapps.io (account: pilarius).
# Does NOT use work accounts (eufmd / foodandagricultureorganization).
#
# Stages a lean bundle so gitignored data/processed + interim artefacts are included.
#
# Usage (from repo root):
#   1. Ensure .env.shinyapps has TOKEN + SECRET (gitignored)
#   2. .\scripts\deploy_shinyapps.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$EnvFile = Join-Path $Root ".env.shinyapps"
if (-not (Test-Path $EnvFile)) {
    Write-Error "Missing $EnvFile — copy .env.shinyapps.example and fill credentials."
}

Get-Content $EnvFile | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#")) { return }
    $parts = $line -split "=", 2
    if ($parts.Count -ne 2) { return }
    Set-Item -Path "Env:$($parts[0].Trim())" -Value $parts[1].Trim()
}

foreach ($key in @("SHINYAPPS_ACCOUNT", "SHINYAPPS_NICKNAME", "SHINYAPPS_TOKEN", "SHINYAPPS_SECRET")) {
    $val = [Environment]::GetEnvironmentVariable($key)
    if ([string]::IsNullOrWhiteSpace($val)) {
        Write-Error "Set $key in .env.shinyapps before deploying."
    }
}

$appTitle = if ($env:SHINYAPPS_APP_TITLE) { $env:SHINYAPPS_APP_TITLE } else { "Animal Health Radar" }

Write-Host "Ensuring shinyapps nickname '$env:SHINYAPPS_NICKNAME' (account=$env:SHINYAPPS_ACCOUNT)..."
rsconnect add `
    --account $env:SHINYAPPS_ACCOUNT `
    --name $env:SHINYAPPS_NICKNAME `
    --token $env:SHINYAPPS_TOKEN `
    --secret $env:SHINYAPPS_SECRET

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
    Write-Error "Missing data/processed/predictions.parquet — run the pipeline before deploying."
}

Write-Host "Deploying '$appTitle' via nickname '$env:SHINYAPPS_NICKNAME'..."
rsconnect deploy shiny $stage `
    --name $env:SHINYAPPS_NICKNAME `
    --title $appTitle

Write-Host "Expected URL: https://$($env:SHINYAPPS_ACCOUNT).shinyapps.io/animal_health_radar/"
