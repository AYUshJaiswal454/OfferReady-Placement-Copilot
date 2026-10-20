# One-command setup and start (Windows PowerShell):  powershell -ExecutionPolicy Bypass -File run.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path .venv)) { Write-Host "Creating virtualenv..."; python -m venv .venv }
. .\.venv\Scripts\Activate.ps1
pip install -q --upgrade pip
pip install -q -r requirements-dev.txt
try { python -m playwright install chromium | Out-Null } catch { Write-Host "Note: Chromium download failed; live-link checks will use the HTTP fallback." }
if (-not (Get-Command tesseract -ErrorAction SilentlyContinue)) { Write-Host "Note: tesseract not found; OCR of images is skipped (install from github.com/UB-Mannheim/tesseract)." }
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
if (-not (Test-Path data\.demo-seeded)) {
  Write-Host "Loading demo data (about 1-2 minutes)..."
  python scripts\seed_demo.py
  New-Item -ItemType Directory -Force data | Out-Null; New-Item -ItemType File -Force data\.demo-seeded | Out-Null
}
Write-Host ""
Write-Host "OfferReady is starting at http://localhost:8000"
Write-Host "  Student: demo@student.msot.edu / demo12345    Placement cell: admin@msot.edu / admin12345"
uvicorn app.main:app --host 0.0.0.0 --port 8000
