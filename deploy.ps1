#Requires -Version 5.1
<#
.SYNOPSIS
  One-shot local deploy: build, start, wait for Odoo init + seed, branding, smoke checks.

.PARAMETER SkipBuild
  Run "docker compose up -d" without --build.

.PARAMETER SkipTests
  Skip pytest inside the api container.

.PARAMETER SkipRace
  Skip the 15/5 concurrent order demo script.

.PARAMETER CloudGuide
  Print free cloud deployment steps (Oracle Always Free + Cloudflare Tunnel) and exit.

.EXAMPLE
  .\deploy.ps1
  .\deploy.ps1 -SkipTests
  .\deploy.ps1 -CloudGuide
#>
param(
    [switch] $SkipBuild,
    [switch] $SkipTests,
    [switch] $SkipRace,
    [switch] $CloudGuide
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-DockerReady {
    docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Docker is not running. Start Docker Desktop and retry." -ForegroundColor Red
        exit 1
    }
}

function Wait-ComposeServiceExit {
    param(
        [string] $Service,
        [int] $MaxWaitSec = 1800
    )
    $elapsed = 0
    while ($elapsed -lt $MaxWaitSec) {
        $cid = docker compose ps -q $Service 2>$null
        if (-not $cid) {
            Start-Sleep -Seconds 5
            $elapsed += 5
            continue
        }
        $status = docker inspect -f "{{.State.Status}}" $cid 2>$null
        if ($status -eq "exited") {
            $code = [int](docker inspect -f "{{.State.ExitCode}}" $cid)
            if ($code -ne 0) {
                docker compose logs --tail 40 $Service
                throw "Service '$Service' exited with code $code"
            }
            Write-Host "    $Service finished successfully."
            return
        }
        if ($status -eq "running") {
            Write-Host "    $Service still running (${elapsed}s)..."
        }
        Start-Sleep -Seconds 15
        $elapsed += 15
    }
    throw "Timed out waiting for $Service after ${MaxWaitSec}s"
}

function Show-CloudGuide {
    $doc = Join-Path $Root "docs\DEPLOY.md"
    Write-Host @"

FREE CLOUD DEPLOY (summary) — full guide: docs/DEPLOY.md

1) Oracle Cloud Always Free (best fit for Odoo + Compose)
   - Ubuntu ARM VM, 6+ GB RAM, install Docker, clone repo, run:
     curl -fsSL https://get.docker.com | sh
     git clone <your-repo-url> inventory-middleware && cd inventory-middleware
     bash scripts/deploy_linux.sh

2) Cloudflare Tunnel (free HTTPS, no open firewall ports)
   - Keep stack on laptop/VM, install cloudflared, tunnel to localhost:8000 / :8501 / :8069

3) Demo-only: run .\deploy.ps1 locally + cloudflared quick tunnel for interviews

"@
    if (Test-Path $doc) {
        Write-Host "Opening $doc"
        Start-Process $doc
    }
}

if ($CloudGuide) {
    Show-CloudGuide
    exit 0
}

Write-Step "Checking Docker"
Test-DockerReady

$envFile = Join-Path $Root ".env"
$envExample = Join-Path $Root ".env.example"
if (-not (Test-Path $envFile) -and (Test-Path $envExample)) {
    Copy-Item $envExample $envFile
    Write-Host "Created .env from .env.example"
}

Write-Step "Starting stack (first boot: Odoo init can take 5–15 minutes)"
if ($SkipBuild) {
    docker compose up -d
} else {
    docker compose up -d --build
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Step "Waiting for one-shot jobs"
try {
    Wait-ComposeServiceExit -Service "odoo-init" -MaxWaitSec 2400
    Wait-ComposeServiceExit -Service "seed" -MaxWaitSec 600
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "Check: docker compose logs -f odoo-init odoo seed"
    exit 1
}

Write-Step "Waiting for Odoo HTTP health"
$odooOk = $false
for ($i = 0; $i -lt 40; $i++) {
    $hc = docker compose ps odoo --format "{{.Health}}" 2>$null
    if ($hc -match "healthy") { $odooOk = $true; break }
    Start-Sleep -Seconds 10
}
if (-not $odooOk) {
    Write-Host "Odoo not healthy yet; branding may retry later." -ForegroundColor Yellow
}

Write-Step "Applying OpenSource logo / Odoo website branding"
docker compose exec -T api python scripts/apply_odoo_branding.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "Branding failed — rerun: docker compose exec api python scripts/apply_odoo_branding.py" -ForegroundColor Yellow
}

if (-not $SkipTests) {
    Write-Step "Running pytest"
    docker compose exec -T api python -m pytest -q
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if (-not $SkipRace) {
    Write-Step "Flash-sale concurrency check (reset BLR laptop stock to 15)"
    docker compose exec -T inventory-db psql -U inventory -d inventory -c "UPDATE warehouse_stock SET available_qty=15 WHERE warehouse_code='WH-BLR-01' AND sku='SKU-LAPTOP-PRO14'" | Out-Null
    docker compose exec -T api python scripts/simulate_concurrent_orders.py
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Step "Deploy complete"
Write-Host @"

URLs
  API (Swagger):  http://localhost:8000/docs
  Dashboard:      http://localhost:8501   (opsadmin / changeme)
  Odoo ERP:       http://localhost:8069   (database: inventory, admin / admin)
  Postgres:       localhost:5433

Useful commands
  docker compose ps
  docker compose logs -f api worker
  docker compose exec api python scripts/apply_odoo_branding.py
  .\deploy.ps1 -CloudGuide

"@