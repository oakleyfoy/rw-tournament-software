# Restart backend and frontend servers
$ErrorActionPreference = "SilentlyContinue"
Write-Host "Stopping ALL Python/Node on 8000 and 3000..." -ForegroundColor Yellow

# Kill by port (repeat 3x to catch respawning workers)
1..3 | ForEach-Object {
    $pids8000 = (Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue).OwningProcess | Sort-Object -Unique
    $pids3000 = (Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue).OwningProcess | Sort-Object -Unique
    $pids8000 | Where-Object { $_ -gt 0 } | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
    $pids3000 | Where-Object { $_ -gt 0 } | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 1
}

# Clear Python cache so fresh code loads
Write-Host "Clearing Python cache..." -ForegroundColor Yellow
Get-ChildItem -Path ".\backend" -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Start-Sleep -Seconds 2
Write-Host "Ports cleared. Starting servers..." -ForegroundColor Green

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $scriptDir "backend"
$frontendDir = Join-Path $scriptDir "frontend"

# Start backend
Write-Host "Starting backend on port 8000..." -ForegroundColor Cyan
Start-Process -FilePath "python" -ArgumentList "-m", "uvicorn", "app.main:app", "--reload", "--host", "127.0.0.1", "--port", "8000" -WorkingDirectory $backendDir -WindowStyle Normal

Start-Sleep -Seconds 3

# Start frontend
Write-Host "Starting frontend on port 3000..." -ForegroundColor Cyan
$npmCmd = if (Get-Command npm.cmd -ErrorAction SilentlyContinue) { "npm.cmd" } else { "npm" }
Start-Process -FilePath $npmCmd -ArgumentList "run", "dev" -WorkingDirectory $frontendDir -WindowStyle Normal

Write-Host ""
Write-Host "Done. Backend: http://localhost:8000 | Frontend: http://localhost:3000" -ForegroundColor Green
