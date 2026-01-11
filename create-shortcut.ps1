# PowerShell script to create desktop shortcut for start-dev.bat

try {
    # Get the actual Desktop path (handles different Windows setups)
    $DesktopPath = [Environment]::GetFolderPath("Desktop")
    
    if (-not (Test-Path $DesktopPath)) {
        # Fallback to common location
        $DesktopPath = "$env:USERPROFILE\Desktop"
        if (-not (Test-Path $DesktopPath)) {
            throw "Desktop folder not found"
        }
    }
    
    $WshShell = New-Object -ComObject WScript.Shell
    $ShortcutPath = Join-Path $DesktopPath "RW Tournament Software.lnk"
    $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = Join-Path $PSScriptRoot "start-dev.bat"
    $Shortcut.WorkingDirectory = $PSScriptRoot
    $Shortcut.Description = "Start RW Tournament Software (Backend + Frontend)"
    $Shortcut.IconLocation = "shell32.dll,137"  # Application icon
    $Shortcut.Save()
    
    Write-Host "Desktop shortcut created successfully!" -ForegroundColor Green
    Write-Host "Look for 'RW Tournament Software' on your desktop at:" -ForegroundColor Green
    Write-Host $ShortcutPath -ForegroundColor Cyan
} catch {
    Write-Host "Error creating shortcut: $_" -ForegroundColor Red
    Write-Host "Trying alternative method..." -ForegroundColor Yellow
    
    # Alternative: Create in current directory and user can move it
    $WshShell = New-Object -ComObject WScript.Shell
    $ShortcutPath = Join-Path $PSScriptRoot "RW Tournament Software.lnk"
    $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = Join-Path $PSScriptRoot "start-dev.bat"
    $Shortcut.WorkingDirectory = $PSScriptRoot
    $Shortcut.Description = "Start RW Tournament Software (Backend + Frontend)"
    $Shortcut.IconLocation = "shell32.dll,137"
    $Shortcut.Save()
    
    Write-Host "Shortcut created in project folder instead:" -ForegroundColor Yellow
    Write-Host $ShortcutPath -ForegroundColor Cyan
    Write-Host "You can drag this to your desktop manually." -ForegroundColor Yellow
}

