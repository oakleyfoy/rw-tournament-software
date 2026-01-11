# PowerShell script to start servers (visible windows for debugging)

# Get script directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $scriptDir "backend"
$frontendDir = Join-Path $scriptDir "frontend"

# Kill existing processes on ports
Write-Host "Cleaning up existing processes on ports 8000 and 3000..." -ForegroundColor Yellow
Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | ForEach-Object {
    Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
}
Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue | ForEach-Object {
    Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
}

# Start both servers in parallel (hidden windows)
Write-Host ""
Write-Host "Starting Backend Server (port 8000)..." -ForegroundColor Green
$backendProcess = Start-Process -FilePath "python" -ArgumentList "-m", "uvicorn", "app.main:app", "--reload", "--host", "127.0.0.1", "--port", "8000" -WorkingDirectory $backendDir -WindowStyle Hidden -PassThru

Write-Host "Starting Frontend Server (port 3000)..." -ForegroundColor Green
$npmCmd = if (Get-Command npm.cmd -ErrorAction SilentlyContinue) { "npm.cmd" } else { "npm" }
$frontendProcess = Start-Process -FilePath $npmCmd -ArgumentList "run", "dev" -WorkingDirectory $frontendDir -WindowStyle Hidden -PassThru

# Open Chrome immediately - servers will be ready soon
Write-Host ""
Write-Host "Opening Chrome (servers starting in background)..." -ForegroundColor Cyan
$chromeProcess = $null

# Try to find Chrome
$chromeExe = $null
if (Get-Command chrome.exe -ErrorAction SilentlyContinue) {
    $chromeExe = "chrome.exe"
    Write-Host "Found Chrome in PATH" -ForegroundColor Gray
} else {
    $chromePaths = @(
        "${env:ProgramFiles}\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
        "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
    )
    foreach ($path in $chromePaths) {
        if (Test-Path $path) {
            $chromeExe = $path
            Write-Host "Found Chrome at: $path" -ForegroundColor Gray
            break
        }
    }
}

# Open Chrome
if ($chromeExe) {
    try {
        Write-Host "Launching Chrome with: $chromeExe" -ForegroundColor Gray
        $chromeProcess = Start-Process -FilePath $chromeExe -ArgumentList "http://localhost:3000" -PassThru -ErrorAction Stop
        Write-Host "Chrome launched successfully (PID: $($chromeProcess.Id))" -ForegroundColor Green
    } catch {
        Write-Host "Error launching Chrome: $_" -ForegroundColor Red
        # Fallback
        $chromeProcess = Start-Process "chrome" -ArgumentList "http://localhost:3000" -PassThru -ErrorAction SilentlyContinue
    }
} else {
    Write-Host "Chrome not found, trying generic 'chrome' command..." -ForegroundColor Yellow
    # Last resort
    $chromeProcess = Start-Process "chrome" -ArgumentList "http://localhost:3000" -PassThru -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "Chrome opened. Servers will keep running even if Chrome closes." -ForegroundColor Cyan
Write-Host ""
Write-Host "To stop servers, close this window or press Ctrl+C" -ForegroundColor Yellow
Write-Host "Server windows (backend and frontend) can also be closed individually." -ForegroundColor Gray
Write-Host ""
Write-Host "Servers are running. Press Ctrl+C to stop all servers..." -ForegroundColor Green

# Function to cleanup servers
function Stop-Servers {
    # Kill backend process
    if ($backendProcess -and !$backendProcess.HasExited) {
        Stop-Process -Id $backendProcess.Id -Force -ErrorAction SilentlyContinue
    }
    
    # Kill frontend process
    if ($frontendProcess -and !$frontendProcess.HasExited) {
        Stop-Process -Id $frontendProcess.Id -Force -ErrorAction SilentlyContinue
    }
    
    # Kill by port (most reliable method)
    try {
        Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | ForEach-Object {
            Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
        }
    } catch {}
    
    try {
        Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue | ForEach-Object {
            Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
        }
    } catch {}
    
    # Kill any remaining uvicorn processes using WMI
    try {
        Get-WmiObject Win32_Process -Filter "name='python.exe' AND commandline LIKE '%uvicorn%'" | ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
    } catch {}
    
    # Kill any remaining vite/node processes using WMI
    try {
        Get-WmiObject Win32_Process -Filter "name='node.exe' AND commandline LIKE '%vite%'" | ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
    } catch {}
}

# Wait for Ctrl+C or window close - servers keep running
try {
    # Keep script running until Ctrl+C
    while ($true) {
        Start-Sleep -Seconds 1
    }
} catch {
    # Handle Ctrl+C gracefully
} finally {
    Write-Host ""
    Write-Host "Shutting down..." -ForegroundColor Yellow
    Stop-Servers
}
